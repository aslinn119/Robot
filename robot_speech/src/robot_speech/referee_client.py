"""A → C 会话层：request_id、确认窗口绑定、重试。

设计要点（都来自 v0.2 的硬约束，不是自选动作）：

1. **确认绑定发生在开窗时，不在收到「是」时。**
   `open_confirm_window()` 立刻快照当前 `pending_id` + `version`，之后用户说什么、
   中间又提了多少新问题，确认发出去的都是开窗那一刻绑定的那一组。
   v0.2 原话：「异步适配器必须在打开收音窗口时绑定这些字段，不能收到迟到的
   「是」后才查询并绑定新问题。」

2. **重试复用同一个事件 dict。**
   去重键是 `game_id + request_id + 完全相同内容`。重试如果重新生成 timestamp，
   会被判成「相同编号改变内容」→ `request_conflict`。所以 `resend()` 原样重发。

3. **重复响应里的 state 是旧快照。**
   v0.2：「响应 state 是处理时快照，UI 刷新应调用 public_state」。
   命中 `duplicate=true` 时本类会忽略响应里的 state，重新取 `public_state()`。

4. **本层不判断阶段、不判断对错、不计数。**
   交不交给 C、C 拒还是收，都由 C 决定；A 只负责把绑定好的事件发出去并记录结果。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from .intents import ParseResult
from .referee_protocol import (
    EVENT_CANCEL,
    EVENT_CONFIRM,
    EVENT_PROPOSE,
    Action,
    UnmappableIntent,
    action_for,
    build_event,
    confirm_payload,
    propose_payload,
)


class RefereeClientError(RuntimeError):
    """客户端本地错误（还没发请求就失败了）。"""


class NoPendingToConfirm(RefereeClientError):
    """当前没有待确认内容，无法打开确认窗口。"""


@dataclass(frozen=True)
class ConfirmWindow:
    """一次确认窗口打开时的绑定快照。

    这个对象一旦创建就不再变化；迟到的确认仍然带着它的身份，
    这正是要验证的行为。

    两个身份要分清楚：

    `pending_key`
        C 的待确认项（`game_id|pending_id|version`）。同一个待确认项被重开窗口时，
        这个值**不变**。

    `key`
        本次**开窗**的身份（`pending_key#window_id`），每次开窗都不同。
        同一个待确认项如果因为重播/超时重开过窗口，两次窗口的 key 必须不一样，
        否则第一扇窗的迟到结果会被误认为第二扇窗的输入。
    """

    game_id: str
    pending_id: str
    version: int
    window_id: str = ""
    kind: Optional[str] = None
    number: Optional[int] = None

    @property
    def pending_key(self) -> str:
        """C 那边待确认项的身份。"""
        return f"{self.game_id}|{self.pending_id}|{self.version}"

    @property
    def key(self) -> str:
        """本次开窗的身份；`window_id` 为空时退化成待确认项身份。"""
        if not self.window_id:
            return self.pending_key
        return f"{self.pending_key}#{self.window_id}"

    def describe(self) -> str:
        target = f"{self.kind}({self.number})" if self.kind else "unknown"
        return f"pending={self.pending_id} v={self.version} {target}"


@dataclass(frozen=True)
class SentRequest:
    """一次已发出的请求及其响应，可原样重发。"""

    event: Mapping[str, Any]
    response: Mapping[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.response.get("ok"))

    @property
    def code(self) -> str:
        return str(self.response.get("code", ""))

    @property
    def duplicate(self) -> bool:
        return bool(self.response.get("duplicate"))

    @property
    def request_id(self) -> str:
        return str(self.event.get("request_id", ""))


class SpeechRefereeClient:
    """A 模块与 C 裁判之间的最小适配层。

    `referee` 只需要提供 `handle(event) -> dict` 与 `public_state() -> dict`，
    也就是 v0.2 的 `RefereeService` 接口。测试里用 `tests/support/fake_referee.py`。
    """

    def __init__(
        self,
        referee: Any,
        game_id: str,
        *,
        request_prefix: str = "A",
        clock: Callable[[], float] = time.time,
        include_timestamp: bool = True,
    ) -> None:
        self._referee = referee
        self._game_id = game_id
        self._prefix = request_prefix
        self._clock = clock
        self._include_timestamp = include_timestamp
        self._counter = 0
        self._window_counter = 0
        self._state: Dict[str, Any] = dict(referee.public_state())

    # -- 只读状态 ----------------------------------------------------------

    @property
    def game_id(self) -> str:
        return self._game_id

    @property
    def request_count(self) -> int:
        """已发出的请求数（含重试），用于核对「重试不该产生新请求」。"""
        return self._counter

    @property
    def state(self) -> Dict[str, Any]:
        return dict(self._state)

    @property
    def has_pending(self) -> bool:
        return self._state.get("pending") is not None

    def is_stale(self, window: ConfirmWindow) -> bool:
        """窗口绑定的内容是否已经不是当前待确认项（只用于日志/提示，不用于拦截）。"""
        pending = self._state.get("pending")
        if not isinstance(pending, Mapping):
            return True
        return (
            pending.get("pending_id") != window.pending_id
            or pending.get("version") != window.version
        )

    # -- 发请求 ------------------------------------------------------------

    def propose(self, result: ParseResult) -> SentRequest:
        """把 ASK / FINAL / EXIT 解析结果转成 propose 发出。"""
        action = action_for(result, confirm_window_open=self.has_pending)
        if action is not Action.PROPOSE:
            raise UnmappableIntent(
                f"{result} 应走 {action.value}，不能当 propose 发送"
            )
        return self.send_propose(propose_payload(result))

    def send_propose(self, payload: Mapping[str, Any]) -> SentRequest:
        """直接发送一个 payload（给复用解析结果之外的场景留口子）。"""
        return self._send(EVENT_PROPOSE, dict(payload))

    def open_confirm_window(self) -> ConfirmWindow:
        """快照当前待确认内容，返回一个不再变化的窗口。

        每次调用都会分配新的 `window_id`：同一个待确认项被重开窗口时，
        两扇窗的 `key` 必须不同。
        """
        pending = self._state.get("pending")
        if not isinstance(pending, Mapping):
            raise NoPendingToConfirm("当前没有待确认内容")

        pending_id = pending.get("pending_id")
        version = pending.get("version")
        if not pending_id or not isinstance(version, int):
            raise RefereeClientError(f"待确认项缺少 pending_id/version: {pending!r}")

        self._window_counter += 1
        return ConfirmWindow(
            game_id=self._game_id,
            pending_id=str(pending_id),
            version=int(version),
            window_id=f"w-{self._window_counter:04d}",
            kind=self._pending_field(pending, "kind"),
            number=self._pending_field(pending, "number"),
        )

    def confirm(self, window: ConfirmWindow) -> SentRequest:
        """用窗口里绑定的值发 confirm。

        **不检查窗口是否已过期**：过期与否由 C 判断，A 擅自拦截会让「迟到确认」
        永远测不出来。想知道是否过期请调用 `is_stale()` 记日志。
        """
        return self._send(EVENT_CONFIRM, confirm_payload(window.pending_id, window.version))

    def cancel(self, window: ConfirmWindow) -> SentRequest:
        """用窗口里绑定的值发 cancel（撤销尚未确认的提议）。"""
        return self._send(EVENT_CANCEL, confirm_payload(window.pending_id, window.version))

    def resend(self, sent: SentRequest) -> SentRequest:
        """原样重发同一个事件（网络重试），必须复用原 request_id 与原内容。"""
        if not isinstance(sent.event, Mapping):
            raise RefereeClientError("SentRequest 缺少事件内容")
        return self._deliver(dict(sent.event))

    # -- 内部 --------------------------------------------------------------

    def _send(self, event_type: str, payload: Dict[str, Any]) -> SentRequest:
        timestamp = self._clock() if self._include_timestamp else None
        event = build_event(
            game_id=self._game_id,
            request_id=self._next_request_id(),
            event_type=event_type,
            payload=payload,
            timestamp=timestamp,
        )
        return self._deliver(event)

    def _deliver(self, event: Dict[str, Any]) -> SentRequest:
        response = self._referee.handle(dict(event))
        if not isinstance(response, Mapping):
            raise RefereeClientError(f"C 返回了非字典响应: {response!r}")
        self._sync_state(response)
        return SentRequest(event=event, response=response)

    def _sync_state(self, response: Mapping[str, Any]) -> None:
        if response.get("duplicate"):
            # 重复响应带的是处理时快照，不能用来刷新画面
            self._state = dict(self._referee.public_state())
            return
        state = response.get("state")
        if isinstance(state, Mapping):
            self._state = dict(state)

    def _next_request_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:04d}"

    @staticmethod
    def _pending_field(pending: Mapping[str, Any], key: str) -> Optional[Any]:
        """pending 的字段位置尚未冻结：兼容平铺与嵌在 payload 里两种写法。"""
        if key in pending:
            return pending[key]
        nested = pending.get("payload")
        if isinstance(nested, Mapping):
            return nested.get(key)
        return None


__all__ = [
    "ConfirmWindow",
    "NoPendingToConfirm",
    "RefereeClientError",
    "SentRequest",
    "SpeechRefereeClient",
]
