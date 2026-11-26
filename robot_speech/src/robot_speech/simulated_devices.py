"""离线开发用的模拟设备。

它们实现 `ports.SpeechInput` / `ports.SpeechOutput`，让整条流程在没有机器人的
情况下可运行、可断言。**模拟设备不等于实机验证**：这里能证明的是流程时序，
不能证明 `/aiui/text_to_speak` 什么时候真的播完。
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Iterable, Iterator, List, Optional, Sequence, Union

from .ports import (
    PlaybackResult,
    PlaybackStatus,
    Utterance,
)

_StatusOrName = Union[PlaybackStatus, str]


def _as_status(value: _StatusOrName) -> PlaybackStatus:
    if isinstance(value, PlaybackStatus):
        return value
    try:
        return PlaybackStatus(value)
    except ValueError as exc:
        raise ValueError(f"未知的播放状态: {value!r}") from exc


class SimulatedSpeaker:
    """按脚本返回播放结局的模拟喇叭。

    `script` 里每个元素是下一次 `speak()` 的结局；用完之后一律使用 `default`。
    这样就能复现「第一次播报失败、重试成功」这类时序，而不需要真的等待。
    """

    def __init__(
        self,
        script: Optional[Sequence[_StatusOrName]] = None,
        *,
        default: _StatusOrName = PlaybackStatus.COMPLETED,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._script: List[PlaybackStatus] = [_as_status(item) for item in (script or ())]
        self._default = _as_status(default)
        self._clock = clock
        self.spoken: List[str] = []
        self.results: List[PlaybackResult] = []

    def speak(self, text: str) -> PlaybackResult:
        started = self._clock()
        status = self._script.pop(0) if self._script else self._default
        result = PlaybackResult(
            status=status,
            text=text,
            elapsed=max(0.0, self._clock() - started),
            detail="simulated",
        )
        self.spoken.append(text)
        self.results.append(result)
        return result

    @property
    def call_count(self) -> int:
        return len(self.spoken)

    @property
    def last_text(self) -> Optional[str]:
        return self.spoken[-1] if self.spoken else None


class ScriptedInput:
    """按脚本产出语音的输入源。

    脚本元素可以是：

    - `str`：普通句子，`window_key` 为 None
    - `Utterance`：完整指定（含窗口绑定）
    - 无参可调用对象：**延迟求值**，可以在流程跑到那一步时再决定内容
      （例如根据当前窗口 key 构造一条迟到确认）
    """

    def __init__(self, items: Iterable[Any]) -> None:
        self._items = list(items)
        self._pending: Optional[Iterator[Any]] = None
        self._poll_index = 0

    def stream(self) -> Iterator[Utterance]:
        for index, item in enumerate(self._items, start=1):
            if callable(item):
                item = item()
            if isinstance(item, Utterance):
                if item.sequence == 0:
                    item = replace(item, sequence=index)
                yield item
            else:
                yield Utterance(text=str(item), sequence=index)

    def __iter__(self) -> Iterator[Utterance]:
        return self.stream()

    def poll(self, timeout: float = 0.0) -> Optional[Utterance]:
        """非阻塞取一条（端口可选方法，供带超时的收音使用）。"""
        if self._poll_index >= len(self._items):
            return None
        item = self._items[self._poll_index]
        self._poll_index += 1
        if callable(item):
            item = item()
        if isinstance(item, Utterance):
            return replace(item, sequence=item.sequence or self._poll_index)
        return Utterance(text=str(item), sequence=self._poll_index)


__all__ = ["ScriptedInput", "SimulatedSpeaker"]
