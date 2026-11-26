"""A 模块：语音交互（阶段一，纯离线解析）。

对外只暴露少量稳定入口，内部实现可替换：

    from robot_speech import parse, ParseResult, Intent, Operator

    result = parse("大于五吗")
    result.intent      -> Intent.ASK
    result.operator    -> Operator.GT
    result.value       -> 5
    result.to_dict()   -> {"intent": "ASK", "operator": "GT", "value": 5,
                           "confidence": 1.0, "raw_text": "大于五吗"}

本包不导入 rospy，也不依赖任何第三方库，可在 Windows 上独立运行。
ROS 接入放在独立的适配层，见 robot_speech/scripts/ 与后续阶段二。
"""

from .iat_parser import (
    SIMULATED_DATA_NOTICE,
    IatAssembler,
    IatError,
    IatSegment,
    IatUpdate,
    build_simulated_payload,
    parse_segment,
)
from .command_agent import CommandAgent, CommandContext, HandlerOutcome
from .http_client import HttpRefereeClient, RefereeHttpError
from .speech_commands import (
    SpeechListenHandler,
    SpeechSayHandler,
    build_listen_result,
    default_handlers,
)
from .team_protocol import (
    A_CAPABILITIES,
    COMMAND_SPEECH_LISTEN,
    COMMAND_SPEECH_SAY,
    ENVELOPE_FIELDS,
    LISTEN_RESULT_FIELDS,
    PROTOCOL_VERSION,
    ProtocolError,
    build_heartbeat,
    listen_result,
    new_id,
    validate_command,
)
from .eventlog import EventLog
from .intents import (
    Intent,
    Operator,
    ParseResult,
    RejectReason,
    accepted,
    rejected,
)
from .ports import (
    PlaybackResult,
    PlaybackStatus,
    SpeechInput,
    SpeechOutput,
    Utterance,
    WindowAttribution,
)
from .probe import ProbeRecorder
from .referee_client import (
    ConfirmWindow,
    NoPendingToConfirm,
    RefereeClientError,
    SentRequest,
    SpeechRefereeClient,
)
from .referee_protocol import (
    Action,
    UnmappableIntent,
    action_for,
    build_event,
    confirm_payload,
    propose_payload,
)
from .speech_parser import (
    MAX_NUMBER,
    MIN_NUMBER,
    build_skeleton,
    extract_numbers,
    has_question_particle,
    has_unsafe_number_format,
    normalize_text,
    parse,
)
from .session import GameSession, SessionReport, TurnRecord
from .simulated_devices import ScriptedInput, SimulatedSpeaker

__version__ = "0.1.0"

__all__ = [
    "EventLog",
    "A_CAPABILITIES",
    "COMMAND_SPEECH_LISTEN",
    "COMMAND_SPEECH_SAY",
    "CommandAgent",
    "CommandContext",
    "ENVELOPE_FIELDS",
    "HandlerOutcome",
    "HttpRefereeClient",
    "LISTEN_RESULT_FIELDS",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "RefereeHttpError",
    "SpeechListenHandler",
    "SpeechSayHandler",
    "build_heartbeat",
    "build_listen_result",
    "default_handlers",
    "listen_result",
    "new_id",
    "validate_command",
    "Intent",
    "Operator",
    "ParseResult",
    "RejectReason",
    "accepted",
    "rejected",
    "Action",
    "ConfirmWindow",
    "NoPendingToConfirm",
    "RefereeClientError",
    "SentRequest",
    "SpeechRefereeClient",
    "UnmappableIntent",
    "action_for",
    "build_event",
    "confirm_payload",
    "propose_payload",
    "GameSession",
    "SessionReport",
    "TurnRecord",
    "PlaybackResult",
    "PlaybackStatus",
    "SpeechInput",
    "SpeechOutput",
    "Utterance",
    "WindowAttribution",
    "ProbeRecorder",
    "ScriptedInput",
    "SimulatedSpeaker",
    "parse",
    "normalize_text",
    "extract_numbers",
    "build_skeleton",
    "has_question_particle",
    "has_unsafe_number_format",
    "MIN_NUMBER",
    "MAX_NUMBER",
    "IatAssembler",
    "IatError",
    "IatSegment",
    "IatUpdate",
    "SIMULATED_DATA_NOTICE",
    "build_simulated_payload",
    "parse_segment",
    "__version__",
]
