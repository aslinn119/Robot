# ============================================================================
# 【已废弃 · v0.2】本模块依据的 A↔C 接口是 v0.2 的**进程内直接调用**，
# TEAM_INTERFACE v1.0（2026-11-26）发布后已被取代。
# 现行入口 scripts/speech_agent.py 使用 command_agent + http_client + team_protocol，
# **不再导入本模块**。保留它是为了对照历史设计，新代码不要使用。
# 现行协议见仓库根目录 TEAM_INTERFACE.md。
# ============================================================================
"""一轮对话的编排：解析 → 提议 → 复述 → 等播完 → 开窗 → 确认。

这一层只做**时序**，不做判定：

- 谁该确认、确认有没有过期，由窗口身份（`Utterance.window_key`）决定，
  不靠文本猜。
- **默认只有在观察到播报完成后才开窗**。拿不到完成信号时不开窗、要求重来；
  只有显式打开 `allow_unverified_playback` 的诊断模式才会在未知状态下继续，
  而且日志里会单独标出来。
- 确认交给 C 判断，A 不预判对错。

设备接入在 `ports.py` 的两个协议里，本模块不 import rospy。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .eventlog import EventLog
from .intents import ParseResult
from .ports import (
    PlaybackResult,
    PlaybackStatus,
    Reciter,
    SpeechInput,
    SpeechOutput,
    Utterance,
    WindowAttribution,
    default_reciter,
)
from .referee_client import (
    ConfirmWindow,
    NoPendingToConfirm,
    SentRequest,
    SpeechRefereeClient,
)
from .referee_protocol import Action, action_for
from .speech_parser import parse

#: 一次 turn 的结局。用字符串而不是枚举，方便直接写进日志文件。
STATUS_INPUT_REJECTED = "input_rejected"
STATUS_PROPOSED = "proposed"
STATUS_PROPOSED_UNVERIFIED = "proposed_unverified"
STATUS_RECITE_FAILED = "recite_failed"
STATUS_RECITE_UNVERIFIED_BLOCKED = "recite_unverified_blocked"
STATUS_REFEREE_REJECTED = "referee_rejected"
STATUS_CONFIRMED = "confirmed"
STATUS_CONFIRM_REJECTED = "confirm_rejected"
STATUS_STALE_CONFIRM = "stale_confirm"
STATUS_UNKNOWN_WINDOW = "unknown_window"
STATUS_NO_PENDING = "no_pending"
STATUS_CANCELLED = "cancelled"
STATUS_CANCEL_REJECTED = "cancel_rejected"
STATUS_LOCAL_CONTROL = "local_control"
STATUS_CONTEXT_REQUIRED = "context_required"
STATUS_NO_RECITATION = "no_pending_recitation"
STATUS_PENDING_CHANGED = "pending_changed"
STATUS_PENDING_GONE = "pending_gone"
STATUS_ATTRIBUTION_UNTRUSTED = "attribution_untrusted"
STATUS_ATTRIBUTION_INFERRED = "attribution_inferred"


@dataclass
class TurnRecord:
    """一轮的完整记录。上机时这份记录就是「各环节的时间和事件」。"""

    text: str
    status: str = ""
    window_key: Optional[str] = None
    detail: str = ""
    spoken: str = ""
    request_id: str = ""
    events: List[Tuple[str, float]] = field(default_factory=list)

    def mark(self, name: str, clock: Callable[[], float]) -> None:
        self.events.append((name, clock()))

    @property
    def duration(self) -> float:
        if len(self.events) < 2:
            return 0.0
        return self.events[-1][1] - self.events[0][1]


@dataclass
class SessionReport:
    """整场运行的记录。"""

    turns: List[TurnRecord] = field(default_factory=list)

    def add(self, record: TurnRecord) -> None:
        self.turns.append(record)

    @property
    def statuses(self) -> List[str]:
        return [turn.status for turn in self.turns]

    def __len__(self) -> int:
        return len(self.turns)


class GameSession:
    """把解析、裁判客户端、输入、播报串成一轮轮对话。"""

    def __init__(
        self,
        client: SpeechRefereeClient,
        input_source: SpeechInput,
        speaker: SpeechOutput,
        *,
        clock: Callable[[], float] = time.monotonic,
        reciter: Reciter = default_reciter,
        log: Optional[EventLog] = None,
        allow_unverified_playback: bool = False,
        allow_inferred_attribution: bool = False,
    ) -> None:
        self._client = client
        self._input = input_source
        self._speaker = speaker
        self._clock = clock
        self._reciter = reciter

        self._log = log if log is not None else EventLog(clock=clock)
        self._log.bind_game(client.game_id)
        self._allow_unverified = allow_unverified_playback
        self._allow_inferred = allow_inferred_attribution

        self._window: Optional[ConfirmWindow] = None
        self._window_opened_at: Optional[float] = None
        self._closed_keys: set[str] = set()

        # 复述没播完（或完成状态未知）时窗口先不生效，等重试
        self._pending_window: Optional[ConfirmWindow] = None
        self._recite_text: str = ""

        self._last_sent: Optional[SentRequest] = None
        self._turn = 0

        self._log.anchor()
        self._log.emit(
            "session.start",
            data={
                "allow_unverified_playback": allow_unverified_playback,
                "allow_inferred_attribution": allow_inferred_attribution,
                "clock": "monotonic",
            },
        )

    # -- 只读状态 ----------------------------------------------------------

    @property
    def log(self) -> EventLog:
        return self._log

    @property
    def window(self) -> Optional[ConfirmWindow]:
        return self._window

    @property
    def window_key(self) -> Optional[str]:
        return self._window.key if self._window is not None else None

    @property
    def awaiting_recitation(self) -> bool:
        return self._pending_window is not None

    @property
    def is_finished(self) -> bool:
        return bool(self._client.state.get("finished"))

    @property
    def request_count(self) -> int:
        return self._client.request_count

    @property
    def last_sent(self) -> Optional[SentRequest]:
        """最近一次真正发给 C 的请求，可用于网络重试。"""
        return self._last_sent

    # -- 主流程 ------------------------------------------------------------

    def run(self) -> SessionReport:
        """一直跑到输入结束或本局结束。"""
        report = SessionReport()
        for utterance in self._input.stream():
            report.add(self.process(utterance))
            if self.is_finished:
                break
        self._log.emit(
            "session.end",
            result="finished" if self.is_finished else "input_exhausted",
            data={"turns": len(report)},
        )
        return report

    def process(self, utterance: Utterance) -> TurnRecord:
        """处理一句输入，返回这一轮记录。"""
        self._turn += 1
        self._log.set_turn(self._turn)

        record = TurnRecord(text=utterance.text, window_key=utterance.window_key)
        record.mark("input", self._clock)
        self._log.emit(
            "input.received",
            window=utterance.window_key,
            text=utterance.text,
            data={
                "chars": len(utterance.text),
                "sequence": utterance.sequence,
                "window_source": utterance.window_source.value,
                "captured_at": utterance.captured_at,
            },
        )

        result = parse(utterance.text)
        record.mark("parsed", self._clock)
        self._log.emit(
            "input.parsed",
            result=result.intent.value if result.accepted else "rejected",
            window=utterance.window_key,
            data={
                "intent": result.intent.value,
                "operator": result.operator.value if result.operator else None,
                "value": result.value,
                "reason": result.reason.value if result.reason else None,
            },
        )

        if not result.accepted:
            record.status = STATUS_INPUT_REJECTED
            record.detail = result.reason.value if result.reason is not None else ""
            record.spoken = self._say("没听清，请再说一遍。")
            return self._finish(record)

        action = action_for(result, confirm_window_open=self._window is not None)

        if action is Action.PROPOSE:
            return self._finish(self._handle_propose(result, record))
        if action is Action.CONFIRM:
            return self._finish(self._handle_confirm(utterance, record))
        if action is Action.CANCEL:
            return self._finish(self._handle_cancel(utterance, record))
        if action is Action.LOCAL:
            return self._finish(self._handle_local(result, record))

        record.status = STATUS_CONTEXT_REQUIRED
        record.spoken = self._say("现在还不能回答是或不是。")
        return self._finish(record)

    def retry_recitation(self) -> TurnRecord:
        """重播复述：**为同一个待确认项重新开一扇窗**，不重新提议。

        每次重开都会分配新的 `window_id`，所以上一扇窗带回来的结果仍然会被拒收。
        """
        self._turn += 1
        self._log.set_turn(self._turn)

        record = TurnRecord(text="<retry recitation>")
        record.mark("retry", self._clock)
        self._log.emit("retry.requested")

        source = self._pending_window or self._window
        if source is None or not self._recite_text:
            record.status = STATUS_NO_RECITATION
            self._log.emit("retry.rejected", result="no_recitation")
            return record

        pending_key = source.pending_key
        self._abandon_recitation("reopened")
        self._close_window("reopened")

        try:
            window = self._create_window()
        except NoPendingToConfirm:
            record.status = STATUS_PENDING_GONE
            self._log.emit("retry.rejected", result="pending_gone")
            return record

        if window.pending_key != pending_key:
            # 待确认项已经换了，这扇窗不能用来重播旧的复述
            self._closed_keys.add(window.key)
            self._log.emit(
                "window.close",
                window=window.key,
                pending=window.pending_key,
                result="pending_changed",
            )
            record.status = STATUS_PENDING_CHANGED
            self._log.emit("retry.rejected", result="pending_changed")
            return record

        playback = self._speak(
            self._recite_text,
            purpose="recite.retry",
            window=window.key,
            pending=window.pending_key,
        )
        record.mark("recited", self._clock)
        record.spoken = self._recite_text

        if playback.completed or (playback.uncertain and self._allow_unverified):
            self._activate(
                window, result="ok" if playback.completed else "unverified"
            )
            record.status = (
                STATUS_PROPOSED if playback.completed else STATUS_PROPOSED_UNVERIFIED
            )
            record.detail = playback.status.value
            return record

        self._pending_window = window
        record.status = (
            STATUS_RECITE_UNVERIFIED_BLOCKED
            if playback.uncertain
            else STATUS_RECITE_FAILED
        )
        record.detail = playback.status.value
        return record

    # -- 各类动作 ----------------------------------------------------------

    def _handle_propose(self, result: ParseResult, record: TurnRecord) -> TurnRecord:
        # 新问题取代旧窗口：旧窗口作废，它带回来的确认不能再生效
        self._close_window("superseded")
        self._abandon_recitation("superseded")

        sent = self._client.propose(result)
        self._last_sent = sent
        record.request_id = sent.request_id
        record.mark("proposed", self._clock)
        self._log.emit(
            "propose.sent",
            request_id=sent.request_id,
            result="sent",
            data={"payload": sent.event.get("payload")},
        )
        self._log_response(sent, "propose")

        if not sent.ok:
            record.status = STATUS_REFEREE_REJECTED
            record.detail = sent.code
            record.spoken = self._say("这个说法裁判没有接受，请换一句。")
            return record

        window = self._create_window()
        recite = self._reciter(result, window)
        self._recite_text = recite
        playback = self._speak(
            recite, purpose="recite", window=window.key, pending=window.pending_key
        )
        record.mark("recited", self._clock)
        record.spoken = recite

        if playback.completed:
            self._activate(window)
            record.status = STATUS_PROPOSED
            record.detail = playback.status.value
            return record

        if playback.uncertain and self._allow_unverified:
            # 诊断模式：明确记录「没看到播完就开窗了」
            self._activate(window, result="unverified")
            self._log.emit(
                "window.open.unverified",
                window=window.key,
                pending=window.pending_key,
                result="warning",
                data={"reason": "no_playback_signal", "mode": "diagnostic"},
            )
            record.status = STATUS_PROPOSED_UNVERIFIED
            record.detail = playback.status.value
            return record

        self._pending_window = window
        self._log.emit(
            "window.deferred",
            window=window.key,
            pending=window.pending_key,
            result="no_playback_proof",
            data={"playback": playback.status.value},
        )
        if playback.uncertain:
            record.status = STATUS_RECITE_UNVERIFIED_BLOCKED
            record.spoken = self._say("没听到播报结束，请再说一次。")
        else:
            record.status = STATUS_RECITE_FAILED
            record.spoken = self._say("没播出来，请再说一次。")
        record.detail = playback.status.value
        return record

    def _handle_confirm(self, utterance: Utterance, record: TurnRecord) -> TurnRecord:
        verdict = self._classify(utterance)

        if verdict == "untrusted":
            record.status = STATUS_ATTRIBUTION_UNTRUSTED
            self._log_untrusted(utterance, "confirm")
            record.spoken = self._say("这条听不出属于哪个问题，请再说一次。")
            return record
        if verdict == "inferred":
            record.status = STATUS_ATTRIBUTION_INFERRED
            self._log_inferred_rejected(utterance, "confirm")
            record.spoken = self._say("这条确认可能对不上当前问题，请再说一次。")
            return record
        if verdict == "stale":
            record.status = STATUS_STALE_CONFIRM
            self._log_stale(utterance, self._stale_reason(utterance))
            record.spoken = self._say("这条确认已经过期了。")
            return record
        if verdict == "unknown":
            record.status = STATUS_UNKNOWN_WINDOW
            self._log_stale(utterance, "unknown_window")
            record.spoken = self._say("这条确认对不上当前的问题。")
            return record
        if self._window is None:
            record.status = STATUS_NO_PENDING
            self._log_stale(utterance, "no_open_window")
            record.spoken = self._say("现在没有要确认的内容。")
            return record

        window = self._window
        self._log_attribution(utterance, "confirm")
        sent = self._client.confirm(window)
        self._last_sent = sent
        record.request_id = sent.request_id
        record.mark("confirmed", self._clock)
        self._log.emit(
            "confirm.sent",
            request_id=sent.request_id,
            window=window.key,
            pending=window.pending_key,
            result="sent",
            data={"payload": sent.event.get("payload")},
        )
        self._log_response(sent, "confirm")
        self._close_window("confirmed" if sent.ok else "confirm_failed")

        if sent.ok:
            record.status = STATUS_CONFIRMED
            record.spoken = self._describe_after_confirm(sent)
            return record

        record.status = STATUS_CONFIRM_REJECTED
        record.detail = sent.code
        record.spoken = self._say("这条确认没有生效。")
        return record

    def _handle_cancel(self, utterance: Utterance, record: TurnRecord) -> TurnRecord:
        verdict = self._classify(utterance)

        if verdict == "untrusted":
            record.status = STATUS_ATTRIBUTION_UNTRUSTED
            self._log_untrusted(utterance, "cancel")
            record.spoken = self._say("这条听不出属于哪个问题，请再说一次。")
            return record
        if verdict == "inferred":
            record.status = STATUS_ATTRIBUTION_INFERRED
            self._log_inferred_rejected(utterance, "cancel")
            record.spoken = self._say("这条取消可能对不上当前问题，请再说一次。")
            return record
        if verdict == "stale":
            record.status = STATUS_STALE_CONFIRM
            self._log_stale(utterance, self._stale_reason(utterance))
            record.spoken = self._say("这条取消已经过期了。")
            return record
        if verdict == "unknown":
            record.status = STATUS_UNKNOWN_WINDOW
            self._log_stale(utterance, "unknown_window")
            record.spoken = self._say("这条取消对不上当前的问题。")
            return record
        if self._window is None:
            record.status = STATUS_NO_PENDING
            self._log_stale(utterance, "no_open_window")
            record.spoken = self._say("现在没有要取消的内容。")
            return record

        window = self._window
        self._log_attribution(utterance, "cancel")
        sent = self._client.cancel(window)
        self._last_sent = sent
        record.request_id = sent.request_id
        record.mark("cancelled", self._clock)
        self._log.emit(
            "cancel.sent",
            request_id=sent.request_id,
            window=window.key,
            pending=window.pending_key,
            result="sent",
            data={"payload": sent.event.get("payload")},
        )
        self._log_response(sent, "cancel")
        self._close_window("cancelled" if sent.ok else "cancel_failed")

        if sent.ok:
            record.status = STATUS_CANCELLED
            record.spoken = self._say("好，这个问题取消了。")
            return record

        record.status = STATUS_CANCEL_REJECTED
        record.detail = sent.code
        record.spoken = self._say("这条取消没有生效。")
        return record

    def _handle_local(self, result: ParseResult, record: TurnRecord) -> TurnRecord:
        record.status = STATUS_LOCAL_CONTROL
        record.detail = result.intent.value
        if result.intent.value == "PAUSE":
            record.spoken = self._say("好，先停一下。")
        else:
            record.spoken = self._say("好，我们继续。")
        return record

    # -- 日志与播报 --------------------------------------------------------

    def _speak(
        self,
        text: str,
        *,
        purpose: str,
        window: Optional[str] = None,
        pending: Optional[str] = None,
    ) -> PlaybackResult:
        """所有播报的唯一出口，保证每条播报都有 request/result 两条日志。"""
        self._log.emit(
            "speak.request",
            window=window,
            pending=pending,
            text=text,
            data={"purpose": purpose, "chars": len(text)},
        )
        started = self._clock()
        try:
            playback = self._speaker.speak(text)
        except Exception as exc:  # 播报失败不能打断流程
            self._log.emit(
                "speak.result",
                window=window,
                result="error",
                data={"purpose": purpose, "detail": repr(exc)},
            )
            return PlaybackResult(
                status=PlaybackStatus.FAILED,
                text=text,
                elapsed=self._clock() - started,
                detail="exception",
            )

        elapsed = playback.elapsed or (self._clock() - started)
        self._log.emit(
            "speak.result",
            window=window,
            result=playback.status.value,
            data={
                "purpose": purpose,
                "elapsed": round(elapsed, 6),
                "detail": playback.detail,
            },
        )
        return playback

    def _say(self, text: str) -> str:
        self._speak(text, purpose="prompt")
        return text

    def _create_window(self) -> ConfirmWindow:
        """向客户端要一扇窗（分配身份），但**还没让它生效**。"""
        window = self._client.open_confirm_window()
        self._log.emit(
            "window.create",
            window=window.key,
            pending=window.pending_key,
            result="ok",
            data={
                "pending_id": window.pending_id,
                "version": window.version,
                "window_id": window.window_id,
                "kind": window.kind,
                "number": window.number,
            },
        )
        return window

    def _activate(self, window: ConfirmWindow, *, result: str = "ok") -> None:
        """让窗口正式可收确认。日志里这一步才是「开窗」的证据。"""
        self._window = window
        self._window_opened_at = self._clock()
        self._log.emit(
            "window.activate",
            window=window.key,
            pending=window.pending_key,
            result=result,
            data={"captured_at": self._window_opened_at},
        )

    def _close_window(self, reason: str) -> None:
        if self._window is None:
            return
        self._closed_keys.add(self._window.key)
        self._log.emit(
            "window.close",
            window=self._window.key,
            pending=self._window.pending_key,
            result=reason,
        )
        self._window = None

    def _abandon_recitation(self, reason: str) -> None:
        if self._pending_window is None:
            return
        self._closed_keys.add(self._pending_window.key)
        self._log.emit(
            "window.close",
            window=self._pending_window.key,
            pending=self._pending_window.pending_key,
            result=reason,
        )
        self._pending_window = None

    def _log_response(self, sent: SentRequest, action: str) -> None:
        self._log.emit(
            "referee.response",
            request_id=sent.request_id,
            result="ok" if sent.ok else "rejected",
            data={
                "action": action,
                "code": sent.code,
                "duplicate": sent.duplicate,
                "message": str(sent.response.get("message", "")),
            },
        )

    def _log_stale(self, utterance: Utterance, reason: str) -> None:
        self._log.emit(
            "input.stale",
            window=utterance.window_key,
            result="rejected",
            data={"reason": reason, "sent_to_referee": False},
        )

    def _finish(self, record: TurnRecord) -> TurnRecord:
        self._log.emit(
            "turn.end",
            request_id=record.request_id or None,
            window=record.window_key,
            result=record.status,
            data={"detail": record.detail} if record.detail else None,
        )
        return record

    # -- 内部 --------------------------------------------------------------

    def _classify(self, utterance: Utterance) -> str:
        """判断一条输入的窗口归属。

        两条独立的判据：

        1. `window_key` 对不对得上当前/已关闭的窗口；
        2. **到达时间是否早于窗口生效时间**——早于就不可能属于这扇窗。

        第 2 条是 key 做不到的：实机上 key 往往按到达时刻推断，正好会指向新窗口。
        """
        if utterance.window_source is WindowAttribution.UNKNOWN:
            return "untrusted"

        # 「到达时推断」的窗口默认不可用来提交：玩家可能在上一扇窗里说的这句话，
        # 只是结果到得晚。只有显式放行的实验模式才接受。
        if (
            utterance.window_source is WindowAttribution.ARRIVAL
            and not self._allow_inferred
        ):
            return "inferred"

        key = utterance.window_key

        if key is not None:
            if self._window is not None and key == self._window.key:
                return "stale" if self._arrived_before_window(utterance) else "current"
            if key in self._closed_keys:
                return "stale"
            return "unknown"

        if self._arrived_before_window(utterance):
            return "stale"
        return "current"

    def _arrived_before_window(self, utterance: Utterance) -> bool:
        if utterance.captured_at is None or self._window_opened_at is None:
            return False
        return utterance.captured_at < self._window_opened_at

    def _stale_reason(self, utterance: Utterance) -> str:
        if self._window is not None and utterance.window_key == self._window.key:
            return "arrived_before_window"
        return "window_closed"

    def _log_attribution(self, utterance: Utterance, action: str) -> None:
        captured = utterance.window_source is WindowAttribution.CAPTURE
        self._log.emit(
            "input.attribution",
            window=utterance.window_key,
            result="captured" if captured else "inferred",
            data={
                "action": action,
                "source": utterance.window_source.value,
                "captured_at": utterance.captured_at,
                "submitted": True,
                "note": "arrival_time_inferred" if not captured else "bound_at_capture",
            },
        )

    def _log_untrusted(self, utterance: Utterance, action: str) -> None:
        self._log.emit(
            "input.attribution",
            window=utterance.window_key,
            result="unknown",
            data={
                "action": action,
                "source": utterance.window_source.value,
                "submitted": False,
                "note": "observation_only",
            },
        )

    def _log_inferred_rejected(self, utterance: Utterance, action: str) -> None:
        self._log.emit(
            "input.attribution",
            window=utterance.window_key,
            result="inferred",
            data={
                "action": action,
                "source": utterance.window_source.value,
                "submitted": False,
                "note": "requires_capture_binding",
            },
        )

    def _describe_after_confirm(self, sent: SentRequest) -> str:
        state = self._client.state
        if state.get("finished"):
            result = state.get("result")
            text = {"win": "机器人赢了。", "lose": "你赢了。", "exit": "本局结束。"}.get(
                str(result), "本局结束。"
            )
            return self._say(text)

        history = state.get("history") or []
        if history:
            answer = history[-1].get("answer") if isinstance(history[-1], dict) else None
            return self._say("是的。" if answer else "不是。")
        return self._say("好的。")


__all__ = [
    "GameSession",
    "SessionReport",
    "TurnRecord",
]
