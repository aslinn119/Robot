"""设备探测：在 C 还没接好时，先把「播报完成」和「识别出口」查清楚。

这个模块**不依赖 rospy**，只负责把观察结果写进同一套 JSONL 事件日志；
真正的订阅在 `scripts/device_probe.py`。

它回答三个现场问题：

1. TTS 服务返回之后，多久才有可用的「播完」信号？有没有这种信号？
2. `/aiui/iat` 这类候选话题到底会不会发消息？
3. 一条消息从 TTS 结束到识别结果到达，间隔是多少？

注意：**到达时间不等于采集时间**。本模块记录的 `arrived_at` 是消息到达时刻，
用它推断「这句话是在哪扇窗里说的」只能力争近似，日志里必须如实标注。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .eventlog import EventLog

DEFAULT_PROBE_TOPICS = "/aiui/nlp,/aiui/iat,/aiui/wakeup"
DEFAULT_TTS_SERVICE = "/aiui/text_to_speak"
DEFAULT_WATCH_SECONDS = 8.0


@dataclass(frozen=True)
class ProbeConfig:
    """诊断入口的启动参数。"""

    run_id: str
    log_path: str
    topics: Tuple[str, ...]
    watch_seconds: float
    tts_service: str
    include_text: bool


def resolve_probe_config(
    get_param: Callable[..., Any],
    *,
    now: Optional[float] = None,
) -> ProbeConfig:
    """从参数服务器读配置，**每个 key 都带默认值**。

    这里踩过一个坑：`rospy.get_param("~run_id")` 不传默认值时，参数没设置会抛
    `KeyError`，后面的 `or 备用值` 根本执行不到，脚本直接起不来。
    """
    run_id_default = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    run_id = str(get_param("~run_id", "") or run_id_default)

    log_default = os.path.expanduser(f"~/.ros/robot_speech/probe-{run_id}.jsonl")
    log_path = str(get_param("~log_path", "") or log_default)

    raw_topics = str(get_param("~topics", DEFAULT_PROBE_TOPICS) or "")
    topics = tuple(item.strip() for item in raw_topics.split(",") if item.strip())

    watch_seconds = float(get_param("~watch_seconds", DEFAULT_WATCH_SECONDS))
    tts_service = str(get_param("~tts_service", DEFAULT_TTS_SERVICE))
    include_text = bool(get_param("~log_raw_text", False))

    return ProbeConfig(
        run_id=run_id,
        log_path=log_path,
        topics=topics,
        watch_seconds=watch_seconds,
        tts_service=tts_service,
        include_text=include_text,
    )


class ProbeRecorder:
    """记录设备观察结果；所有输出都写进 `EventLog`。"""

    def __init__(
        self,
        log: EventLog,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._log = log
        self._clock = clock
        self._watch_label: Optional[str] = None
        self._watch_started: float = 0.0
        self._watch_count = 0
        self._watch_topic_counts: Dict[str, int] = {}
        self._topic_counts: Dict[str, int] = {}

    # -- 订阅记录 ----------------------------------------------------------

    def note_subscribed(self, topic: str) -> None:
        self._log.emit("probe.subscribed", data={"topic": topic})

    # -- 消息到达 ----------------------------------------------------------

    def note_message(self, topic: str, payload: Any, *, kind: str = "unknown") -> int:
        """记录一条到达的消息，返回 `payload` 的观测长度。

        只记长度和类型，不记内容——内容由 `EventLog(include_text=True)` 统一控制。
        """
        size = len(payload) if hasattr(payload, "__len__") else 1
        self._topic_counts[topic] = self._topic_counts.get(topic, 0) + 1
        in_watch = self._watch_label is not None
        if in_watch:
            self._watch_count += 1
            self._watch_topic_counts[topic] = self._watch_topic_counts.get(topic, 0) + 1

        self._log.emit(
            "probe.message",
            text=str(payload) if isinstance(payload, str) else None,
            data={
                "topic": topic,
                "kind": kind,
                "size": size,
                "arrived_at": round(self._clock(), 6),
                "in_watch": in_watch,
                "count_on_topic": self._topic_counts[topic],
            },
        )
        return size

    # -- 观察窗口 ----------------------------------------------------------

    def begin_watch(self, label: str, seconds: float) -> None:
        self._watch_label = label
        self._watch_started = self._clock()
        self._watch_count = 0
        self._watch_topic_counts = {}
        self._log.emit("probe.watch.begin", data={"label": label, "seconds": seconds})

    def end_watch(self) -> Dict[str, Any]:
        """结束观察窗口，返回这段时间里各类消息的数量。"""
        label = self._watch_label
        elapsed = 0.0 if label is None else self._clock() - self._watch_started
        summary = {
            "label": label,
            "messages": self._watch_count,
            "by_topic": dict(self._watch_topic_counts),
        }
        self._log.emit(
            "probe.watch.end",
            result="completed" if label is not None else "not_watching",
            data={**summary, "elapsed": round(elapsed, 6)},
        )
        self._watch_label = None
        self._watch_count = 0
        self._watch_topic_counts = {}
        return summary

    @property
    def messages_in_watch(self) -> int:
        return self._watch_count

    # -- 汇总 --------------------------------------------------------------

    def topic_summary(self) -> List[Dict[str, Any]]:
        return [
            {"topic": topic, "count": count}
            for topic, count in sorted(self._topic_counts.items())
        ]


__all__ = [
    "DEFAULT_PROBE_TOPICS",
    "DEFAULT_TTS_SERVICE",
    "DEFAULT_WATCH_SECONDS",
    "ProbeConfig",
    "ProbeRecorder",
    "resolve_probe_config",
]
