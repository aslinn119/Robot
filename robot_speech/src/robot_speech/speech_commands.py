"""两条语音命令的实现：`speech.say` 与 `speech.listen`（TEAM_INTERFACE §6）。

这一层只做「命令 → 设备 → 结果」的翻译，不含游戏逻辑：

- `speech.say`：朗读，**必须在确实播完之后**才回 success；判不出来就回
  `CAPABILITY_UNAVAILABLE`，不伪报（§6.1）。
- `speech.listen`：收音 → 规则解析 → 按规范的十个字段回传（§6.2）。
  绑定字段（pending_id / pending_version / question_id）**原样取自命令**，
  A 不自己推断窗口，也不改数字、真假或否定词。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterator, Mapping, Optional

from .command_agent import CommandContext, HandlerOutcome
from .intents import Intent, Operator, ParseResult, RejectReason
from .ports import PlaybackStatus, SpeechInput, SpeechOutput, Utterance
from .speech_parser import parse
from .team_protocol import (
    ERR_ASR_FAILED,
    ERR_BAD_REQUEST,
    ERR_CAPABILITY_UNAVAILABLE,
    ERR_NO_SPEECH,
    ERR_TIMEOUT,
    ERR_TTS_FAILED,
    INTENT_ANSWER,
    INTENT_CANCEL,
    INTENT_CONFIRM,
    INTENT_EXIT,
    INTENT_FINAL_SUBMIT,
    INTENT_HELP,
    INTENT_PAUSE,
    INTENT_QUESTION,
    INTENT_REPEAT_LAST,
    INTENT_RESUME,
    INTENT_UNSUPPORTED,
    PARSER_RULE,
    listen_result,
)

#: 需要「问清楚」而不是「换个说法」的拒绝原因
_AMBIGUOUS_REASONS = frozenset(
    {
        RejectReason.COMPOUND,
        RejectReason.MULTIPLE_NUMBERS,
        RejectReason.NEGATION_AMBIGUOUS,
        RejectReason.UNEXPECTED_QUESTION,
        RejectReason.OUT_OF_RANGE,
    }
)

_INTENT_MAP = {
    Intent.FINAL: INTENT_FINAL_SUBMIT,
    Intent.CONFIRM: INTENT_CONFIRM,
    Intent.CANCEL: INTENT_CANCEL,
    Intent.PAUSE: INTENT_PAUSE,
    Intent.RESUME: INTENT_RESUME,
    Intent.EXIT: INTENT_EXIT,
    Intent.REPEAT_LAST: INTENT_REPEAT_LAST,
    Intent.HELP: INTENT_HELP,
}

_OPERATOR_MAP = {Operator.GT: "gt", Operator.LT: "lt", Operator.EQ: "eq"}


def next_utterance(
    source: SpeechInput,
    deadline: float,
    *,
    clock: Callable[[], float] = time.monotonic,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Optional[Utterance]:
    """在截止时间前取一条语音。

    优先用输入源的 `poll(timeout)`：`RosInput` 的 `stream()` 在没消息时不会返回，
    直接 `next()` 会永久卡住，既等不到超时也查不了取消。
    没有 `poll` 的实现（老式脚本输入）退回迭代器，并说明该路径不能超时。
    """
    poll = getattr(source, "poll", None)
    if callable(poll):
        while clock() < deadline:
            if should_stop is not None and should_stop():
                return None
            wait = min(0.3, max(0.05, deadline - clock()))
            utterance = poll(wait)
            if utterance is not None:
                return utterance
        return None

    stream: Iterator[Utterance] = source.stream()
    try:
        while True:
            if clock() >= deadline:
                return None
            if should_stop is not None and should_stop():
                return None
            utterance = next(stream)
            if utterance is not None:
                return utterance
    except StopIteration:
        return None


class SpeechSayHandler:
    """`speech.say`：朗读并如实回报结局。"""

    def __init__(self, speaker: SpeechOutput, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._speaker = speaker
        self._clock = clock

    def __call__(self, ctx: CommandContext) -> HandlerOutcome:
        text = ctx.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return HandlerOutcome.failure(ERR_BAD_REQUEST, "speech.say 缺少 text")

        if ctx.should_stop(force=True):
            return HandlerOutcome.cancelled("执行前已取消")

        playback = self._speaker.speak(text)

        if playback.completed:
            # 只有确实播完才回 success
            return HandlerOutcome.success({"spoken": True})

        if playback.uncertain:
            # 规范 §6.1：判不出来就报能力不可用，不能伪报成功
            return HandlerOutcome.failure(
                ERR_CAPABILITY_UNAVAILABLE, "无法判断播报是否结束，未伪报成功"
            )

        if playback.status is PlaybackStatus.TIMEOUT:
            return HandlerOutcome.failure(ERR_TIMEOUT, "播报超时")
        return HandlerOutcome.failure(ERR_TTS_FAILED, playback.detail or "播报失败")


class SpeechListenHandler:
    """`speech.listen`：收音 → 规则解析 → 规范结果。"""

    def __init__(
        self,
        source: SpeechInput,
        *,
        parser: Callable[[str], ParseResult] = parse,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._parser = parser
        self._clock = clock

    def __call__(self, ctx: CommandContext) -> HandlerOutcome:
        payload = ctx.payload
        max_listen_ms = payload.get("max_listen_ms")
        if (
            isinstance(max_listen_ms, bool)
            or not isinstance(max_listen_ms, int)
            or max_listen_ms <= 0
        ):
            return HandlerOutcome.failure(ERR_BAD_REQUEST, "speech.listen 缺少 max_listen_ms")

        problem = _check_bindings(payload)
        if problem is not None:
            return HandlerOutcome.failure(ERR_BAD_REQUEST, problem)

        deadline = min(ctx.deadline, self._clock() + max_listen_ms / 1000.0)

        if ctx.should_stop(force=True):
            return HandlerOutcome.cancelled("收音前已取消")

        if getattr(self._source, "drain_before_listen", False):
            drain = getattr(self._source, "drain", None)
            if callable(drain):
                drain()

        utterance = next_utterance(
            self._source,
            deadline,
            clock=self._clock,
            should_stop=lambda: ctx.should_stop(),
        )
        if utterance is None or not utterance.text:
            if ctx.cancelled or ctx.cancel_state() == "cancel_requested":
                return HandlerOutcome.cancelled("收音已取消")
            # 无语音是任务失败，不是「随便生成一个意图」
            return HandlerOutcome.failure(ERR_NO_SPEECH, "没有听到语音")

        try:
            parsed = self._parser(utterance.text)
        except Exception as exc:  # 解析器本身出问题时也要如实回报
            return HandlerOutcome.failure(ERR_ASR_FAILED, f"解析异常: {type(exc).__name__}")

        return HandlerOutcome.success(build_listen_result(parsed, payload, utterance.text))


def build_listen_result(
    parsed: ParseResult,
    payload: Mapping[str, Any],
    utterance: str,
) -> Dict[str, Any]:
    """把解析结果变成规范的十个字段。

    绑定字段原样取自命令；不属于当前 `allowed_intents` 的意图一律回 `unsupported`，
    不替 C 猜。
    """
    allowed = _allowed_intents(payload)

    if not parsed.accepted:
        reason = _ambiguous_or_unsupported(parsed.reason)
        return listen_result(
            intent=INTENT_UNSUPPORTED, utterance=utterance, reason=reason
        )

    intent = _to_team_intent(parsed, allowed)
    if intent is None or intent not in allowed:
        return listen_result(
            intent=INTENT_UNSUPPORTED, utterance=utterance, reason="unsupported"
        )

    if intent == INTENT_QUESTION:
        return listen_result(
            intent=intent,
            comparison=_OPERATOR_MAP.get(parsed.operator),
            number=parsed.value,
            utterance=utterance,
        )

    if intent == INTENT_FINAL_SUBMIT:
        return listen_result(intent=intent, number=parsed.value, utterance=utterance)

    if intent == INTENT_ANSWER:
        return listen_result(
            intent=intent,
            answer=parsed.intent is Intent.AFFIRM,
            question_id=_optional_str(payload.get("question_id")),
            utterance=utterance,
        )

    if intent in (INTENT_CONFIRM, INTENT_CANCEL):
        return listen_result(
            intent=intent,
            pending_id=_optional_str(payload.get("pending_id")),
            pending_version=_optional_int(payload.get("pending_version")),
            question_id=_optional_str(payload.get("question_id")),
            utterance=utterance,
        )

    return listen_result(intent=intent, utterance=utterance)


def _to_team_intent(parsed: ParseResult, allowed: tuple) -> Optional[str]:
    if parsed.intent is Intent.ASK:
        return INTENT_QUESTION

    if parsed.intent in (Intent.AFFIRM, Intent.DENY):
        # 「是/不是」的含义由窗口决定：回答窗口是 answer，确认窗口是 confirm/cancel。
        # 不能无条件映射成 answer，否则确认窗口里玩家说「是的」会被判 unsupported。
        if INTENT_ANSWER in allowed:
            return INTENT_ANSWER
        if INTENT_CONFIRM in allowed or INTENT_CANCEL in allowed:
            return INTENT_CONFIRM if parsed.intent is Intent.AFFIRM else INTENT_CANCEL
        return INTENT_ANSWER

    return _INTENT_MAP.get(parsed.intent)


def _allowed_intents(payload: Mapping[str, Any]) -> tuple:
    allowed = payload.get("allowed_intents")
    if isinstance(allowed, (list, tuple)):
        return tuple(str(item) for item in allowed)
    return ()


def _check_bindings(payload: Mapping[str, Any]) -> Optional[str]:
    """窗口要求的绑定字段缺失时提前报错，不要回传一个不合 schema 的结果。"""
    allowed = _allowed_intents(payload)
    if INTENT_CONFIRM in allowed or INTENT_CANCEL in allowed:
        if _optional_str(payload.get("pending_id")) is None:
            return "确认窗口缺少 pending_id"
        if _optional_int(payload.get("pending_version")) is None:
            return "确认窗口缺少 pending_version"
    if INTENT_ANSWER in allowed and _optional_str(payload.get("question_id")) is None:
        return "回答窗口缺少 question_id"
    return None


def _ambiguous_or_unsupported(reason: Optional[RejectReason]) -> str:
    return "ambiguous" if reason in _AMBIGUOUS_REASONS else "unsupported"


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def default_handlers(speaker: SpeechOutput, source: SpeechInput) -> Dict[str, Callable]:
    """A 的两条命令 → 处理器。"""
    from .team_protocol import COMMAND_SPEECH_LISTEN, COMMAND_SPEECH_SAY

    return {
        COMMAND_SPEECH_SAY: SpeechSayHandler(speaker),
        COMMAND_SPEECH_LISTEN: SpeechListenHandler(source),
    }


__all__ = [
    "SpeechListenHandler",
    "SpeechSayHandler",
    "build_listen_result",
    "default_handlers",
    "next_utterance",
]
