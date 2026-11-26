#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 模块的 **ROS 适配层**（不是可执行入口）。

只做「设备 ↔ 端口」的接线，不含业务逻辑，也不自己编排流程：

- `RosSpeaker`：`/aiui/text_to_speak` + `/aiui/play_end` → `SpeechOutput`
- `RosInput`：`/aiui/nlp` → `SpeechInput`

可执行入口是 `scripts/speech_agent.py`（TEAM_INTERFACE v1.0 的命令循环），
它从本文件导入这两个适配器。

> 上机实测（2026-11-26）：
> - 播报完成信号 = `/aiui/play_end`（`std_msgs/Empty`，一播一条，说完才发），
>   实测 `speak()` 返回 `COMPLETED`、`elapsed=6.7s`；
> - `/aiui/text_to_speak` 约 1 秒返回，请求字段 `text`，响应 `is_success`，
>   返回成功**不等于**播完；
> - `/aiui/nlp` 能出**自由语音**（实测「大于五吗」原样返回）；
> - `/aiui/iat` 的 publisher 建了但代码里没有 publish 调用，**永远无输出**。

已知可用的设备接口（来自 `A_speech/aiui_reference/` 源码 + 实测）：

| 类型 | 名称 | 说明 |
| --- | --- | --- |
| 服务 | `/aiui/text_to_speak` | `text: String` → `is_success`，返回成功≠播完 |
| 话题 | `/aiui/play_end` | `std_msgs/Empty`，播报结束 |
| 话题 | `/aiui/nlp` | `std_msgs/String`，自由语音的识别文本 |
| 服务 | `/aiui/direct_control` | 把文本当 NLP 结果，调试用 |
| 话题 | `/micarrays/wakeup` | 唤醒事件 |
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from typing import Callable, Iterator, Optional

# 让 `python3 scripts/speech_node.py` 在模块根目录下也能找到包。
# 本目录没有 package.xml / setup.py，所以不能依赖 ROS 的包解析。
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import rospy  # noqa: E402
from std_msgs.msg import Empty, String  # noqa: E402

from robot_speech import (  # noqa: E402
    EventLog,
    PlaybackResult,
    PlaybackStatus,
    Utterance,
    WindowAttribution,
)

try:  # 厂商服务类型；离线环境没有这个包
    from ros_AIUI_node.srv import textToSpeak
except ImportError:  # pragma: no cover - 只会在非机器人环境触发
    textToSpeak = None  # type: ignore[assignment]


class RosSpeaker:
    """把 `/aiui/text_to_speak` 接到 `SpeechOutput` 端口。"""

    def __init__(
        self,
        service_name: str = "/aiui/text_to_speak",
        *,
        timeout: float = 8.0,
        completion_probe: Optional[Callable[[float], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        log: Optional[EventLog] = None,
        wait_timeout: float = 5.0,
        play_end_topic: str = "/aiui/play_end",
    ) -> None:
        if textToSpeak is None:
            raise RuntimeError("未找到 ros_AIUI_node.srv.textToSpeak，请在机器人上运行")
        self._service_name = service_name
        self._timeout = timeout
        self._probe = completion_probe
        self._clock = clock
        self._log = log
        self._proxy = rospy.ServiceProxy(service_name, textToSpeak)

        # 播报结束信号：厂商节点在 /aiui/play_end 上发 std_msgs/Empty。
        # 2026-11-26 实测：一次 text_to_speak 调用只产生一条，且基本在说完之后出现；
        # 该服务本身约 1 秒就返回，**不等于播完**。
        self._play_end_topic = play_end_topic
        self._play_end_queue: "queue.Queue[float]" = queue.Queue()
        self._play_end_sub = None
        if play_end_topic:
            self._play_end_sub = rospy.Subscriber(
                play_end_topic, Empty, self._on_play_end, queue_size=10
            )

        # 启动时先等服务就位，避免第一句话直接吃一个异常。
        # 服务晚于本节点启动时只告警，不阻断（播报失败会在 speak() 里按 FAILED 处理）。
        try:
            rospy.wait_for_service(service_name, timeout=wait_timeout)
        except rospy.ROSException:
            rospy.logwarn("等待服务 %s 超时（%.1fs），稍后调用可能失败", service_name, wait_timeout)

    # -- 播报结束信号 ------------------------------------------------------

    def _on_play_end(self, _msg) -> None:
        self._play_end_queue.put(self._clock())

    def _drain_play_end(self) -> None:
        while True:
            try:
                self._play_end_queue.get_nowait()
            except queue.Empty:
                return

    def _playback_deadline(self, text: str) -> float:
        """按字数估一个上限；固定 8 秒会让长句一定误判超时。"""
        estimate = 3.0 + 0.35 * len(text)
        return max(self._timeout, min(15.0, estimate))

    def _wait_play_end(self, timeout: float) -> Optional[float]:
        deadline = self._clock() + timeout
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return None
            try:
                return self._play_end_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

    def speak(self, text: str) -> PlaybackResult:
        started = self._clock()

        # 先清掉上一次播报残留的结束信号，避免张冠李戴
        self._drain_play_end()

        try:
            response = self._proxy(text)
        except Exception as exc:  # 服务不可用、超时等
            rospy.logerr("text_to_speak 调用失败: %s", exc)
            if self._log is not None:
                self._log.emit(
                    "tts.service",
                    result="failed",
                    data={"service": self._service_name, "detail": str(exc)},
                )
            return PlaybackResult(
                status=PlaybackStatus.FAILED,
                text=text,
                elapsed=self._clock() - started,
                detail=str(exc),
            )

        elapsed = self._clock() - started

        # 不抛异常不等于成功：要读响应里的 is_success（与 device_probe.py 保持一致）
        success = getattr(response, "is_success", None)
        if success is None:
            service_status = "accepted_unknown"
        else:
            service_status = "accepted" if bool(success) else "rejected"

        if self._log is not None:
            self._log.emit(
                "tts.service",
                result=service_status,
                data={
                    "service": self._service_name,
                    "elapsed": round(elapsed, 6),
                    "is_success": None if success is None else bool(success),
                    "raw_response": repr(response),
                    # 注意：成功只代表「请求已提交」，不代表播完
                    "means": "request_submitted_only",
                },
            )

        if success is not None and not bool(success):
            return PlaybackResult(
                status=PlaybackStatus.FAILED,
                text=text,
                elapsed=elapsed,
                detail="is_success_false",
            )

        if self._probe is None and self._play_end_topic:
            # 靠厂商的 /aiui/play_end 判定：实测一次播报一条、且在说完之后
            finished_at = self._wait_play_end(self._playback_deadline(text))
            if finished_at is None:
                if self._log is not None:
                    self._log.emit(
                        "tts.play_end",
                        result="timeout",
                        data={"timeout": self._playback_deadline(text)},
                    )
                return PlaybackResult(
                    status=PlaybackStatus.TIMEOUT,
                    text=text,
                    elapsed=self._clock() - started,
                    detail="play_end_timeout",
                )
            playback_elapsed = finished_at - started
            if self._log is not None:
                self._log.emit(
                    "tts.play_end",
                    result="completed",
                    data={"topic": self._play_end_topic, "elapsed": round(playback_elapsed, 3)},
                )
            return PlaybackResult(
                status=PlaybackStatus.COMPLETED,
                text=text,
                elapsed=playback_elapsed,
                detail="play_end",
            )

        if self._probe is None:
            rospy.logwarn_throttle(
                5.0,
                "播报完成信号未知：已提交请求，按 UNVERIFIED 处理（%r）",
                text,
            )
            if self._log is not None:
                self._log.emit(
                    "tts.probe",
                    result="absent",
                    data={
                        "reason": "no_completion_signal",
                        "is_success_unknown": success is None,
                    },
                )
            return PlaybackResult(
                status=PlaybackStatus.UNVERIFIED,
                text=text,
                elapsed=elapsed,
                detail="no_completion_signal",
            )

        try:
            finished = self._probe(self._timeout)
        except TimeoutError:
            if self._log is not None:
                self._log.emit("tts.probe", result="timeout", data={"timeout": self._timeout})
            return PlaybackResult(
                status=PlaybackStatus.TIMEOUT,
                text=text,
                elapsed=self._clock() - started,
                detail="probe_timeout",
            )

        if self._log is not None:
            self._log.emit(
                "tts.probe",
                result="completed" if finished else "not_finished",
                data={"timeout": self._timeout},
            )

        return PlaybackResult(
            status=PlaybackStatus.COMPLETED if finished else PlaybackStatus.TIMEOUT,
            text=text,
            elapsed=self._clock() - started,
            detail="probe",
        )


class RosInput:
    """把 `/aiui/nlp` 的文本接到 `SpeechInput` 端口。

    ⚠️ `/aiui/nlp` 是**语义结果**，只在命中技能时有内容；自由听写的结果不从这里来。
    这个类现在的价值是「把已有出口接上、把时序跑顺」，不是解决 IAT。

    **窗口归属是「到达时推断」的，不是「采集时绑定」的。**
    打标在 ROS 回调里完成（不是出队时——出队可能已过了好几秒），但仍然只知道
    「消息到达那一刻哪扇窗开着」。玩家在窗口 A 说「确认」、结果在窗口 B 打开后才到，
    这里会把它标成 B。为此：

    - 结果记为 `WindowAttribution.ARRIVAL`，日志里明确标 `inferred`；
    - 同时带上到达时刻，会话用「到达早于窗口生效」这条独立判据把它判为过期。
      这条判据不依赖 key，能挡住上面的错误。

    只有设备能报告「收音开始」时才可能真正做到采集时绑定（`attribution=CAPTURE`）。

    `drain_before_listen` 默认开启：每次开始收之前清掉积压。
    它只能清掉**已经积压**的消息；**之后才到达**的回声或旧识别仍可能进入窗口。
    """

    def __init__(
        self,
        window_key_provider: Callable[[], Optional[str]],
        *,
        topic: str = "/aiui/nlp",
        drain_before_listen: bool = True,
        idle_timeout: Optional[float] = None,
        log: Optional[EventLog] = None,
        attribution: WindowAttribution = WindowAttribution.ARRIVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._provider = window_key_provider
        self._drain = drain_before_listen
        self._idle_timeout = idle_timeout
        self._log = log
        self._attribution = attribution
        self._clock = clock
        self._sequence = 0
        rospy.Subscriber(topic, String, self._on_message)

    def _on_message(self, msg: String) -> None:
        # 关键：在回调里就把到达时刻和当时的窗口一起记下来
        self._queue.put((msg.data, self._clock(), self._provider()))

    def poll(self, timeout: float = 0.3) -> Optional[Utterance]:
        """带超时取一条语音；超时返回 None。

        `stream()` 在没有消息时不会返回，直接 next() 会永久阻塞，
        既等不到 `max_listen_ms` 也查不了取消。`speech.listen` 用这个方法。
        """
        try:
            text, arrived_at, window_key = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if not text:
            return None
        self._sequence += 1
        return Utterance(
            text=text,
            window_key=window_key,
            sequence=self._sequence,
            window_source=self._attribution,
            captured_at=arrived_at,
        )

    @property
    def drain_before_listen(self) -> bool:
        return self._drain

    def drain(self) -> int:
        """清空积压，返回丢弃的条数。"""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def stream(self) -> Iterator[Utterance]:
        while not rospy.is_shutdown():
            if self._drain:
                dropped = self.drain()
                if dropped and self._log is not None:
                    self._log.emit(
                        "input.drained",
                        result="discarded",
                        data={"count": dropped, "scope": "backlog_only"},
                    )

            try:
                text, arrived_at, window_key = self._queue.get(
                    timeout=self._idle_timeout or 0.5
                )
            except queue.Empty:
                if self._idle_timeout is not None:
                    return
                continue

            if not text:
                continue

            self._sequence += 1
            yield Utterance(
                text=text,
                window_key=window_key,
                sequence=self._sequence,
                window_source=self._attribution,
                captured_at=arrived_at,
            )

