"""设备端口：A 模块与外界之间的**可替换入口**。

核心包（`speech_parser` / `iat_parser` / `referee_*`）不认识机器人，只认识这里定义的
两个协议。离线演示、测试、将来接 ROS 都实现同一组方法，因此上机时只需替换实现，
流程代码不用改。

两个端口：

`SpeechInput`
    产出 `Utterance`。**每条语音都必须带 `window_key`**——它是「开始收音时
    正开着哪个确认窗口」。迟到结果能不能串到下一轮，全靠这个字段判断，
    不能靠文本内容去猜。

`SpeechOutput`
    朗读并等待播放结束。真实设备目前**拿不到可靠的完成信号**
    （`/aiui/text_to_speak` 返回 True 只说明请求已提交），所以状态里专门留了
    `UNVERIFIED`：表示「请求已提交，播没播完不知道」，由上层决定要不要当成功处理。

上机当天要确认的就是这两件事：播放完成信号从哪来、识别结果从哪取。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator, Optional, Protocol, runtime_checkable


class PlaybackStatus(str, Enum):
    """一次朗读的结局。"""

    COMPLETED = "completed"    # 确认播完
    FAILED = "failed"          # 明确失败（服务报错、播放器中断）
    TIMEOUT = "timeout"        # 等完成信号超时
    UNVERIFIED = "unverified"  # 请求已提交，但没有可用的完成信号


class WindowAttribution(str, Enum):
    """`Utterance.window_key` 是**怎么**得到的——这决定它能不能用来提交确认。

    CAPTURE
        收音开始那一刻绑定的。可信。
    ARRIVAL
        识别结果**到达**时按当时的窗口推断的。语音可能在上一扇窗里说的，
        只是到达得晚，这时它会指向错误窗口。可信度有限，日志要标出来。
    UNKNOWN
        没有任何归属信息。**只能观察，不能用来提交确认。**
    """

    CAPTURE = "capture"
    ARRIVAL = "arrival"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlaybackResult:
    """朗读结果。"""

    status: PlaybackStatus
    text: str
    elapsed: float = 0.0
    detail: str = ""

    @property
    def completed(self) -> bool:
        """确定播完了——只有这种才能放心打开确认窗口。"""
        return self.status is PlaybackStatus.COMPLETED

    @property
    def uncertain(self) -> bool:
        """设备无法判断是否播完。"""
        return self.status is PlaybackStatus.UNVERIFIED

    @property
    def ok_to_continue(self) -> bool:
        return self.status in (PlaybackStatus.COMPLETED, PlaybackStatus.UNVERIFIED)


@dataclass(frozen=True)
class Utterance:
    """一句待识别的语音。

    window_key
        处于哪个确认窗口（`ConfirmWindow.key`）。不在确认窗口期间说话时为 None。

    window_source
        `window_key` 的来源。**不能默认当成可信**：实机上通常只能在结果到达时
        推断窗口，而这正是「在 A 的窗口里说话、B 窗口打开后才收到」会出错的场景。

    captured_at
        结果**到达**的单调时钟时刻（不是采集时刻——拿不到采集时刻时不要伪造）。
        会话用它做一件 key 做不到的事：如果结果在窗口生效**之前**就到了，
        它不可能属于这扇窗，直接判为过期。
    """

    text: str
    window_key: Optional[str] = None
    sequence: int = 0
    window_source: WindowAttribution = WindowAttribution.CAPTURE
    captured_at: Optional[float] = None


class InputError(RuntimeError):
    """输入源故障（设备断开、队列关闭等）。"""


class OutputError(RuntimeError):
    """输出源故障（TTS 服务不可用等）。"""


@runtime_checkable
class SpeechInput(Protocol):
    """语音输入端口。"""

    def stream(self) -> Iterator[Utterance]:
        """阻塞式逐条产出识别结果，直到输入结束。"""


@runtime_checkable
class SpeechOutput(Protocol):
    """语音输出端口（朗读 + 等待完成）。"""

    def speak(self, text: str) -> PlaybackResult:
        """朗读一句话并返回结局。实现方负责超时。"""


#: 复述文本生成器：拿到解析结果与窗口，返回要读出来的话
Reciter = Callable[[object, object], str]


def default_reciter(result, window) -> str:  # 类型放宽，避免 ports 依赖其他模块
    """默认复述模板（阶段二可调，措辞不是接口）。"""
    intent = getattr(result, "intent", None)
    value = getattr(result, "value", None)
    operator = getattr(result, "operator", None)

    if getattr(intent, "value", None) == "ASK":
        op = getattr(operator, "value", None)
        if op == "GT":
            return f"你是要问，比{value}大吗？请确认。"
        if op == "LT":
            return f"你是要问，比{value}小吗？请确认。"
        return f"你是要问，是{value}吗？请确认。"
    if getattr(intent, "value", None) == "FINAL":
        return f"你是要提交，{value}，对吗？请确认。"
    if getattr(intent, "value", None) == "EXIT":
        return "你要结束这一局，对吗？请确认。"
    return "请确认。"


DEFAULT_SPEAK_TIMEOUT = 10.0


class MonotonicClock:
    """可注入的时钟，方便测试。"""

    def __init__(self, time_fn: Callable[[], float] = time.monotonic) -> None:
        self._time = time_fn

    def __call__(self) -> float:
        return self._time()


__all__ = [
    "DEFAULT_SPEAK_TIMEOUT",
    "InputError",
    "MonotonicClock",
    "OutputError",
    "PlaybackResult",
    "PlaybackStatus",
    "Reciter",
    "SpeechInput",
    "SpeechOutput",
    "Utterance",
    "WindowAttribution",
    "default_reciter",
]
