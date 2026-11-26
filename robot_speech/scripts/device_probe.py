#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设备探测入口：**不需要 C，也不需要游戏逻辑**。

上机当天、C 的接口还没接好之前，用它把三件事**分开**记下来：

1. **服务接受**——`/aiui/text_to_speak` 的响应里 `is_success` 到底是什么；
2. **现场听到播完**——人工按回车打点，这才是「播完」的可靠参照；
3. **有没有机器信号**——观察窗口内各路话题有没有消息，什么时候到。

这三件事不能混为一谈：`is_success: True` 只说明请求被接受，不代表播完。

用法（机器人上，先加载环境）：

    source /opt/ros/noetic/setup.bash
    source ~/robot_ros_application/catkin_ws/devel/setup.bash
    cd <本模块根目录>            # 例如 robot_speech/
    python3 scripts/device_probe.py

**本目录没有 package.xml / CMakeLists.txt**，所以 `rosrun robot_speech device_probe.py`
只有在脚本被放进 catkin 工作空间里某个已构建的包时才可用；那种启动方式需要现场验证。

可选参数：

    _topics:="/aiui/nlp,/aiui/iat,/aiui/wakeup"
    _watch_seconds:=8
    _tts_service:=/aiui/text_to_speak
    _log_raw_text:=true

终端里输入一句话回车 → 调 TTS 并开始观察；**听到播完时再按一次回车**打点；
输入 `q` 退出。

**本脚本只观察，不判断对错，也不提交任何游戏请求。**
到达时间不等于采集时间，日志里的窗口归属只能当近似。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import rospy  # noqa: E402

try:  # noqa: E402
    from rospy.msg import AnyMsg
except ImportError:  # pragma: no cover
    AnyMsg = None  # type: ignore[assignment]

from robot_speech import EventLog  # noqa: E402
from robot_speech.probe import ProbeRecorder, resolve_probe_config  # noqa: E402


@dataclass(frozen=True)
class TtsOutcome:
    """一次 TTS 调用的结果。`status` 只描述「请求被接受与否」，不描述播完。"""

    status: str  # accepted / rejected / failed / accepted_unknown
    elapsed: float
    is_success: Optional[bool] = None
    detail: str = ""

    @property
    def submitted(self) -> bool:
        return self.status in ("accepted", "accepted_unknown")


class ProbeSpeaker:
    """只调 TTS 并记录服务返回，**不断言播完**。"""

    def __init__(self, service: str, log: EventLog) -> None:
        from ros_AIUI_node.srv import textToSpeak

        self._proxy = rospy.ServiceProxy(service, textToSpeak)
        self._service = service
        self._log = log

    def speak(self, text: str) -> "TtsOutcome":
        started = time.monotonic()
        try:
            response = self._proxy(text)
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._log.emit(
                "tts.service",
                result="failed",
                data={
                    "service": self._service,
                    "detail": str(exc),
                    "elapsed": round(elapsed, 6),
                },
            )
            return TtsOutcome(status="failed", elapsed=elapsed, is_success=None, detail=str(exc))

        elapsed = time.monotonic() - started

        # 关键：不能「没抛异常就算成功」。要看响应里的字段。
        success = getattr(response, "is_success", None)
        if success is None:
            status = "accepted_unknown"
            detail = "响应里没有 is_success 字段，请核对 srv 定义"
        elif bool(success):
            status = "accepted"
            detail = ""
        else:
            status = "rejected"
            detail = "服务明确返回 is_success=False"

        self._log.emit(
            "tts.service",
            result=status,
            data={
                "service": self._service,
                "elapsed": round(elapsed, 6),
                "is_success": None if success is None else bool(success),
                "raw_response": repr(response),
                "detail": detail,
                "means": "request_submitted_only",
                "open_question": "where does playback completion come from?",
            },
        )
        return TtsOutcome(
            status=status,
            elapsed=elapsed,
            is_success=None if success is None else bool(success),
            detail=detail,
        )


def _wait_for_enter(deadline: float) -> Optional[bool]:
    """等到超时或收到回车。True=按了回车，False=超时，None=stdin 不可用。"""
    try:
        import select
    except ImportError:  # pragma: no cover
        return None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            ready, _, _ = select.select([sys.stdin], [], [], min(remaining, 0.2))
        except (OSError, ValueError):  # pragma: no cover
            return None
        if ready:
            sys.stdin.readline()
            return True


def main() -> int:
    rospy.init_node("speech_device_probe")

    # 每个 key 都有默认值：不带任何参数也能起来
    config = resolve_probe_config(rospy.get_param)

    os.makedirs(os.path.dirname(os.path.abspath(config.log_path)), exist_ok=True)
    stream = open(config.log_path, "a", encoding="utf-8")
    log = EventLog(stream, session=f"probe-{config.run_id}", include_text=config.include_text)
    log.anchor()
    log.emit(
        "session.start",
        data={
            "mode": "device_probe",
            "topics": list(config.topics),
            "watch_seconds": config.watch_seconds,
            "tts_service": config.tts_service,
        },
    )
    rospy.loginfo("日志：%s", config.log_path)

    recorder = ProbeRecorder(log)

    if AnyMsg is None:  # pragma: no cover
        rospy.logerr("rospy.msg.AnyMsg 不可用，无法按未知类型订阅")
        return 2

    def _make_callback(topic: str):
        def _callback(msg) -> None:  # noqa: ANN001
            try:
                payload = msg._buff
            except AttributeError:  # pragma: no cover
                payload = b""
            recorder.note_message(topic, payload, kind=type(msg).__name__)

        return _callback

    for topic in config.topics:
        rospy.Subscriber(topic, AnyMsg, _make_callback(topic))
        recorder.note_subscribed(topic)
        rospy.loginfo("已订阅 %s", topic)

    try:
        speaker: Optional[ProbeSpeaker] = ProbeSpeaker(config.tts_service, log)
    except Exception as exc:  # pragma: no cover
        rospy.logerr("TTS 服务不可用（仍可观察话题）: %s", exc)
        speaker = None

    def _stdin_loop() -> None:
        print(
            "输入一句话回车 → 调 TTS；听到播完后再回车打点；q 退出。观察窗口 %ss。"
            % config.watch_seconds
        )
        while not rospy.is_shutdown():
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.2)
                continue
            text = line.strip()
            if not text:
                continue
            if text.lower() in ("q", "quit", "exit"):
                rospy.signal_shutdown("user")
                return

            submitted_at = time.monotonic()
            outcome: Optional[TtsOutcome] = None
            if speaker is not None:
                outcome = speaker.speak(text)
                print(
                    "  TTS 服务 : %s%s (%.2fs)%s"
                    % (
                        outcome.status,
                        "（请求已接受，不代表播完）" if outcome.status == "accepted" else "",
                        outcome.elapsed,
                        f" — {outcome.detail}" if outcome.detail else "",
                    )
                )
            else:
                print("  TTS 服务 : 不可用（只观察话题）")

            recorder.begin_watch("after_tts", config.watch_seconds)

            # 只有**确实发出了播报请求**才启用「听到播完」打点。
            # speaker 不可用（outcome is None）或服务拒绝时，打点没有依据。
            can_hear = outcome is not None and outcome.submitted
            if can_hear:
                print("  …观察中（听到播完请按回车）")
            else:
                print("  …TTS 未提交，仅观察话题（不出现播完打点）")

            pressed = _wait_for_enter(submitted_at + config.watch_seconds)
            heard = pressed is True and can_hear
            elapsed = time.monotonic() - submitted_at

            log.emit(
                "tts.observed",
                result="observed" if heard else "not_observed",
                data={
                    "source": "operator",
                    "machine_signal": False,
                    "applicable": can_hear,
                    "elapsed": round(elapsed, 6),
                    "note": "人工确认听到播完（现场参照，不是机器信号）"
                    if heard
                    else ("TTS 未提交，不适用" if not can_hear else "窗口内没有打点"),
                },
            )

            summary = recorder.end_watch()

            # 三个口径分开打印，不要混成一句
            if can_hear:
                reference = "%s（相对提交 %.2fs，现场参照，不是机器信号）" % (
                    "听到播完" if heard else "未打点/超时",
                    elapsed,
                )
            else:
                reference = "不适用（TTS 未提交）"
            print("  人工参照 : %s" % reference)
            print("  完成信号 : 未观察到（本版本未接入完成信号检测）")
            print(
                "  话题消息 : %d 条 %s（到达计数，不等于播完信号）"
                % (summary["messages"], summary["by_topic"] or "{}")
            )

    worker = threading.Thread(target=_stdin_loop, name="probe-stdin", daemon=True)
    worker.start()

    try:
        rospy.spin()
    finally:
        log.emit("session.end", data={"topics": recorder.topic_summary()})
        log.close()
        print("日志：%s" % config.log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
