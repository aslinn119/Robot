"""TEAM_INTERFACE v1.0 的公共格式：事件信封、命令、结果、错误码。

本模块**只做格式**，不做网络（网络在 `http_client.py`），也不做循环（在 `command_agent.py`）。
这样格式校验可以单独测，不依赖任何服务。

规范来源：`docs/TEAM_INTERFACE.md` §4（信封/响应）、§5（命令与结果）、§6（A 的两种命令）。
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, Mapping, Optional

PROTOCOL_VERSION = "1.0"
API_PREFIX = "/api/v1"

SOURCE_A = "A"
SOURCE_B = "B"
SOURCE_C = "C"
SOURCE_D = "D"

# ---------------------------------------------------------------------------
# 事件与命令
# ---------------------------------------------------------------------------

EVENT_HEARTBEAT = "module.heartbeat"
EVENT_TASK_ACCEPTED = "task.accepted"
EVENT_TASK_STARTED = "task.started"
EVENT_TASK_RESULT = "task.result"

COMMAND_SPEECH_SAY = "speech.say"
COMMAND_SPEECH_LISTEN = "speech.listen"

A_CAPABILITIES = (COMMAND_SPEECH_SAY, COMMAND_SPEECH_LISTEN)

#: 事件信封的**恰好八个**顶层字段（规范 §4.1，不接受额外字段）
ENVELOPE_FIELDS = (
    "protocol_version",
    "request_id",
    "game_id",
    "input_epoch",
    "source",
    "command_id",
    "event_type",
    "payload",
)

#: 命令的**恰好八个**顶层字段（规范 §5.1）
COMMAND_FIELDS = (
    "protocol_version",
    "command_id",
    "game_id",
    "input_epoch",
    "target",
    "command_type",
    "timeout_ms",
    "payload",
)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# ---------------------------------------------------------------------------
# A 的结果词表（规范 §6.2 表）
# ---------------------------------------------------------------------------

INTENT_QUESTION = "question"
INTENT_FINAL_SUBMIT = "final_submit"
INTENT_ANSWER = "answer"
INTENT_CONFIRM = "confirm"
INTENT_CANCEL = "cancel"
INTENT_PAUSE = "pause"
INTENT_RESUME = "resume"
INTENT_EXIT = "exit"
INTENT_REPEAT_LAST = "repeat_last"
INTENT_HELP = "help"
INTENT_UNSUPPORTED = "unsupported"

#: speech.listen 结果的**恰好十个**字段
LISTEN_RESULT_FIELDS = (
    "intent",
    "comparison",
    "number",
    "answer",
    "pending_id",
    "pending_version",
    "question_id",
    "utterance",
    "parser",
    "reason",
)

COMPARISONS = ("gt", "lt", "eq")

PARSER_RULE = "rule"
PARSER_QWEN = "qwen"
PARSER_MANUAL_MOCK = "manual_mock"

PURPOSES = ("prompt", "question", "answer", "confirmation", "result", "feedback")

# ---------------------------------------------------------------------------
# 错误码（规范 §13.2）
# ---------------------------------------------------------------------------

ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_UNAUTHORIZED = "UNAUTHORIZED"
ERR_COMMAND_EXPIRED = "COMMAND_EXPIRED"
ERR_COMMAND_CANCELLED = "COMMAND_CANCELLED"
ERR_COMMAND_NOT_RUNNABLE = "COMMAND_NOT_RUNNABLE"
ERR_NO_SPEECH = "NO_SPEECH"
ERR_ASR_FAILED = "ASR_FAILED"
ERR_MODEL_TIMEOUT = "MODEL_TIMEOUT"
ERR_TTS_FAILED = "TTS_FAILED"
ERR_CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
ERR_TIMEOUT = "TIMEOUT"
ERR_CANCELLED = "CANCELLED"
ERR_INTERNAL = "INTERNAL_ERROR"

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ProtocolError(ValueError):
    """本地格式错误。**不要在协议错误时自行编造结果回传**。"""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def new_id() -> str:
    """32 位小写十六进制 UUID（规范要求所有 ID 都用这个形式）。"""
    return uuid.uuid4().hex


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def _require(condition: bool, reason: str, detail: str = "") -> None:
    if not condition:
        raise ProtocolError(reason, detail)


# ---------------------------------------------------------------------------
# 事件信封
# ---------------------------------------------------------------------------


def build_event(
    *,
    request_id: str,
    game_id: Optional[str],
    input_epoch: Optional[int],
    source: str,
    command_id: Optional[str],
    event_type: str,
    payload: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """构造一条 `/events` 请求体。

    信封**恰好八个字段**，多一个都会被 C 拒绝（规范 §4.1）。
    `game_id` / `input_epoch` / `command_id` 只有在 `module.heartbeat` 里才允许全为 null。
    """
    event: Dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "game_id": game_id,
        "input_epoch": input_epoch,
        "source": source,
        "command_id": command_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
    }

    if extra:
        raise ProtocolError("ENVELOPE_EXTRA_FIELD", f"信封不接受额外字段: {sorted(extra)}")

    _require(tuple(event) == ENVELOPE_FIELDS, "ENVELOPE_FIELDS", f"{tuple(event)}")

    _require(is_valid_id(request_id), "BAD_REQUEST_ID", request_id)
    _require(source in (SOURCE_A, SOURCE_B, SOURCE_C, SOURCE_D), "BAD_SOURCE", str(source))
    _require(isinstance(command_id, str) or command_id is None, "BAD_COMMAND_ID", str(command_id))
    if command_id is not None:
        _require(is_valid_id(command_id), "BAD_COMMAND_ID", command_id)

    if event_type != EVENT_HEARTBEAT:
        _require(is_valid_id(game_id or ""), "BAD_GAME_ID", str(game_id))
        _require(
            isinstance(input_epoch, int) and not isinstance(input_epoch, bool),
            "BAD_INPUT_EPOCH",
            str(input_epoch),
        )

    return event


def build_heartbeat(
    *,
    instance_id: str,
    source: str = SOURCE_A,
    module_status: str = "ready",
    active_command_ids: Optional[Iterable[str]] = None,
    capabilities: Iterable[str] = A_CAPABILITIES,
    runtime_mode: str = "mock",
) -> Dict[str, Any]:
    """`module.heartbeat`：game_id / input_epoch / command_id 全为 null。"""
    payload = {
        "instance_id": instance_id,
        "module_status": module_status,
        "active_command_ids": list(active_command_ids or ()),
        "capabilities": list(capabilities),
        "runtime_mode": runtime_mode,
    }
    return build_event(
        request_id=new_id(),
        game_id=None,
        input_epoch=None,
        source=source,
        command_id=None,
        event_type=EVENT_HEARTBEAT,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


def validate_command(command: Mapping[str, Any]) -> Dict[str, Any]:
    """校验并归一化一条命令。字段多余、缺字段、类型不对都拒绝。"""
    _require(isinstance(command, Mapping), "BAD_COMMAND", str(type(command)))
    missing = [name for name in COMMAND_FIELDS if name not in command]
    _require(not missing, "COMMAND_MISSING_FIELDS", str(missing))
    extra = [name for name in command if name not in COMMAND_FIELDS]
    _require(not extra, "COMMAND_EXTRA_FIELDS", str(extra))

    _require(command["protocol_version"] == PROTOCOL_VERSION, "UNSUPPORTED_VERSION",
             str(command["protocol_version"]))
    _require(is_valid_id(command["command_id"]), "BAD_COMMAND_ID", str(command["command_id"]))
    _require(is_valid_id(command["game_id"]), "BAD_GAME_ID", str(command["game_id"]))
    _require(
        isinstance(command["input_epoch"], int) and not isinstance(command["input_epoch"], bool),
        "BAD_INPUT_EPOCH",
        str(command["input_epoch"]),
    )
    _require(
        isinstance(command["timeout_ms"], int)
        and not isinstance(command["timeout_ms"], bool)
        and command["timeout_ms"] > 0,
        "BAD_TIMEOUT",
        str(command["timeout_ms"]),
    )
    _require(isinstance(command["payload"], Mapping), "BAD_PAYLOAD", str(type(command["payload"])))
    return dict(command)


def task_result_success(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {"status": STATUS_SUCCESS, "result": dict(result), "error": None}


def task_result_failure(code: str, message: str) -> Dict[str, Any]:
    # schema 限制 error.message ≤160
    return {"status": STATUS_FAILED, "result": None, "error": {"code": code, "message": str(message)[:160]}}


def task_result_cancelled(message: str = "任务已取消") -> Dict[str, Any]:
    return {"status": STATUS_CANCELLED, "result": None, "error": {"code": ERR_CANCELLED, "message": message}}


# ---------------------------------------------------------------------------
# speech.listen 的结果
# ---------------------------------------------------------------------------


def listen_result(
    *,
    intent: str,
    comparison: Optional[str] = None,
    number: Optional[int] = None,
    answer: Optional[bool] = None,
    pending_id: Optional[str] = None,
    pending_version: Optional[int] = None,
    question_id: Optional[str] = None,
    utterance: str = "",
    parser: str = PARSER_RULE,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 `speech.listen` 的结果，**恰好十个字段**，未用字段填 null。"""
    result = {
        "intent": intent,
        "comparison": comparison,
        "number": number,
        "answer": answer,
        "pending_id": pending_id,
        "pending_version": pending_version,
        "question_id": question_id,
        "utterance": utterance[:160],
        "parser": parser,
        "reason": reason,
    }
    _require(tuple(result) == LISTEN_RESULT_FIELDS, "LISTEN_FIELDS", f"{tuple(result)}")
    return result


def command_lane(command_type: str) -> Optional[str]:
    """A/B 都是 `main`；D 按命令类型分 strategy/motion。"""
    if command_type in (COMMAND_SPEECH_SAY, COMMAND_SPEECH_LISTEN):
        return "main"
    return None


__all__ = [
    "A_CAPABILITIES",
    "API_PREFIX",
    "COMMAND_FIELDS",
    "COMMAND_SPEECH_LISTEN",
    "COMMAND_SPEECH_SAY",
    "COMPARISONS",
    "ENVELOPE_FIELDS",
    "ERR_ASR_FAILED",
    "ERR_CANCELLED",
    "ERR_CAPABILITY_UNAVAILABLE",
    "ERR_COMMAND_CANCELLED",
    "ERR_COMMAND_EXPIRED",
    "ERR_MODEL_TIMEOUT",
    "ERR_NO_SPEECH",
    "ERR_TTS_FAILED",
    "ERR_TIMEOUT",
    "EVENT_HEARTBEAT",
    "EVENT_TASK_ACCEPTED",
    "EVENT_TASK_RESULT",
    "EVENT_TASK_STARTED",
    "INTENT_ANSWER",
    "INTENT_CANCEL",
    "INTENT_CONFIRM",
    "INTENT_EXIT",
    "INTENT_FINAL_SUBMIT",
    "INTENT_HELP",
    "INTENT_PAUSE",
    "INTENT_QUESTION",
    "INTENT_REPEAT_LAST",
    "INTENT_RESUME",
    "INTENT_UNSUPPORTED",
    "LISTEN_RESULT_FIELDS",
    "PARSER_MANUAL_MOCK",
    "PARSER_QWEN",
    "PARSER_RULE",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "SOURCE_A",
    "STATUS_CANCELLED",
    "STATUS_FAILED",
    "STATUS_SUCCESS",
    "build_event",
    "build_heartbeat",
    "command_lane",
    "is_valid_id",
    "listen_result",
    "new_id",
    "task_result_cancelled",
    "task_result_failure",
    "task_result_success",
    "validate_command",
]
