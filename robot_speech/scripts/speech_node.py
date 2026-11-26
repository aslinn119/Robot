#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 模块的 ROS 入口（**薄壳**）。

本文件只做「设备 ↔ 端口」的接线，不含业务逻辑：

- 流程编排：`robot_speech.session.GameSession`
- 文本解析：`robot_speech.speech_parser`
- A→C 事件：`robot_speech.referee_client`

上机当天需要在这里改/确认三处，代码里都标了 `TODO(上机)`：

1. **播报完成信号**——`RosSpeaker.completion_probe`
   `/aiui/text_to_speak` 返回 True 只表示请求已提交，不等于播完。
   目前没有完成信号时返回 `UNVERIFIED`：流程继续，但日志会标出来。
2. **识别结果出口**——`RosInput`
   当前只能订阅已有的 `/aiui/nlp`（语义结果，**不是**自由听写）。
   真正的 IAT 出口尚未确认。
3. **A↔C 传输**——`build_referee()`
   小组自定义话题/服务名尚未冻结，这里故意留成未实现。

已知可用的设备接口（来自 `A_speech/aiui_reference/` 源码）：

| 类型 | 名称 | 说明 |
| --- | --- | --- |
| 服务 | `/aiui/text_to_speak` | `text: String`，返回成功≠播完 |
| 服务 | `/aiui/direct_control` | 把文本当 NLP 结果，调试用 |
| 话题 | `/aiui/nlp` | `std_msgs/String` 语义结果 |
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
from std_msgs.msg import String  # noqa: E402

from robot_speech import (  # noqa: E402
    EventLog,
    GameSession,
    PlaybackResult,
    PlaybackStatus,
    SpeechRefereeClient,
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
    ) -> None:
        if textToSpeak is None:
            raise RuntimeError("未找到 ros_AIUI_node.srv.textToSpeak，请在机器人上运行")
        self._service_name = service_name
        self._timeout = timeout
        self._probe = completion_probe
        self._clock = clock
        self._log = log
        self._proxy = rospy.ServiceProxy(service_name, textToSpeak)

        # 启动时先等服务就位，避免第一句话直接吃一个异常。
        # 服务晚于本节点启动时只告警，不阻断（播报失败会在 speak() 里按 FAILED 处理）。
        try:
            rospy.wait_for_service(service_name, timeout=wait_timeout)
        except rospy.ROSException:
            rospy.logwarn("等待服务 %s 超时（%.1fs），稍后调用可能失败", service_name, wait_timeout)

    def speak(self, text: str) -> PlaybackResult:
        started = self._clock()

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

        if self._probe is None:
            # TODO(上机): 确认完成信号从哪来。
            # 候选：订阅某个播放状态话题、读 Player.is_playing（在 AIui_node 进程内，
            # 外部拿不到）、或自行统计 PCM 时长 + 余量。
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


def build_referee(module: str = "", path: str = ""):
    """构造 A→C 的传输层。

    今天（v0.2）C 只提供**本地 Python 接口**：`referee_client` 接受任何有
    `handle(event)` 与 `public_state()` 的对象，所以直接把 `RefereeService()` 传进来即可。

    参数（ROS 参数服务器）：

        ~referee_module  例如 event_service        （空 = 未接，抛错退出）
        ~referee_path    可选，C 的包目录

    等全组把 A↔C 的 ROS 话题/服务冻结后，在这里换成 service 客户端即可，
    `GameSession` 一行都不用改。
    """
    if not module:
        raise NotImplementedError(
            "A→C 传输层未配置：用 ~referee_module:=event_service 指定 C 的模块；"
            "若 C 的代码不在 PYTHONPATH 里，再给 ~referee_path:=<包目录>。"
            "离线验证请用 tests/support/fake_referee.py。"
        )

    if path:
        resolved = os.path.abspath(os.path.expanduser(path))
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

    try:
        imported = __import__(module, fromlist=["RefereeService"])
    except ImportError as exc:
        raise NotImplementedError(f"无法导入 {module}（是否漏了 ~referee_path？）: {exc}") from exc

    factory = getattr(imported, "RefereeService", None)
    if factory is None:
        raise NotImplementedError(f"{module} 里没有 RefereeService")

    referee = factory()
    rospy.loginfo("已接入 C 的裁判实现：%s.%s", module, "RefereeService")
    return referee


class _SessionHolder:
    """让输入端能拿到「当前窗口 key」。"""

    def __init__(self) -> None:
        self.session: Optional[GameSession] = None

    def window_key(self) -> Optional[str]:
        return self.session.window_key if self.session is not None else None


def main() -> int:
    rospy.init_node("robot_speech_node", anonymous=False)

    try:
        referee = build_referee(
            module=str(rospy.get_param("~referee_module", "")),
            path=str(rospy.get_param("~referee_path", "")),
        )
    except NotImplementedError as exc:
        rospy.logerr("%s", exc)
        return 2

    game_id = rospy.get_param("~game_id", "")
    if not game_id:
        rospy.logerr("缺少参数 ~game_id")
        return 2

    # 日志：每次启动一个文件 + 唯一会话 ID，避免多次试跑的 seq 混在一起
    run_id = rospy.get_param("~run_id", "") or time.strftime("%Y%m%d-%H%M%S")
    default_path = os.path.expanduser(f"~/.ros/robot_speech/{run_id}.jsonl")
    log_path = rospy.get_param("~log_path", "") or default_path
    log_raw = bool(rospy.get_param("~log_raw_text", False))
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    log_stream = open(log_path, "a", encoding="utf-8")
    log = EventLog(log_stream, session=f"robot-{run_id}", include_text=log_raw)
    rospy.loginfo("事件日志: %s（会话 %s，原始文本 %s）", log_path, f"robot-{run_id}",
                  "开" if log_raw else "关")

    speaker = RosSpeaker(
        service_name=rospy.get_param("~tts_service", "/aiui/text_to_speak"),
        timeout=rospy.get_param("~speak_timeout", 8.0),
        log=log,
    )

    holder = _SessionHolder()
    input_source = RosInput(
        holder.window_key,
        topic=rospy.get_param("~nlp_topic", "/aiui/nlp"),
        drain_before_listen=rospy.get_param("~drain_before_listen", True),
        log=log,
    )

    client = SpeechRefereeClient(referee, game_id)
    session = GameSession(
        client,
        input_source,
        speaker,
        log=log,
        # 默认关闭：必须观察到播完才开窗。上机诊断时才临时打开。
        allow_unverified_playback=bool(rospy.get_param("~allow_unverified_playback", False)),
    )
    holder.session = session

    def _shutdown() -> None:
        rospy.loginfo("robot_speech_node 关闭")

    rospy.on_shutdown(_shutdown)

    # 放 worker 线程：rospy 回调里不能长时间阻塞
    def _run() -> None:
        report = session.run()
        rospy.loginfo("对话结束，共 %d 轮: %s", len(report), report.statuses)

    worker = threading.Thread(target=_run, name="speech-session", daemon=True)
    worker.start()

    try:
        rospy.spin()
    finally:
        # 退出时补一条收尾记录并关文件（EventLog 每行都 flush，这里主要是把句柄关干净）
        log.emit("session.end", data={"reason": "shutdown"})
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
