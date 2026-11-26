"""A 模块：语音交互。

对外只暴露稳定入口，内部实现可替换：

    from robot_speech import parse, ParseResult, Intent, Operator

    result = parse("大于五吗")
    result.intent      -> Intent.ASK
    result.operator    -> Operator.GT
    result.value       -> 5

协议版本：TEAM_INTERFACE v1.0（HTTP + 任务拉取），协议正本见仓库根目录
`TEAM_INTERFACE.md`。A→C 链路是 `http_client` → `command_agent` → `speech_commands`。

本包不导入 rospy，也不依赖任何第三方库，可在 Windows 上独立运行。
ROS 接入放在 `scripts/speech_node.py`（纯适配层）+ `scripts/speech_agent.py`（入口）。
"""

from .command_agent import CommandAgent, CommandContext, HandlerOutcome
from .eventlog import EventLog
from .http_client import HttpRefereeClient, RefereeHttpError
from .iat_parser import (
    SIMULATED_DATA_NOTICE,
    IatAssembler,
    IatError,
    IatSegment,
    IatUpdate,
    build_simulated_payload,
    parse_segment,
)
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
from .simulated_devices import ScriptedInput, SimulatedSpeaker
from .speech_commands import (
    SpeechListenHandler,
    SpeechSayHandler,
    build_listen_result,
    default_handlers,
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

__version__ = "0.2.0"

__all__ = [
    "A_CAPABILITIES",
    "COMMAND_SPEECH_LISTEN",
    "COMMAND_SPEECH_SAY",
    "CommandAgent",
    "CommandContext",
    "ENVELOPE_FIELDS",
    "EventLog",
    "HandlerOutcome",
    "HttpRefereeClient",
    "IatAssembler",
    "IatError",
    "IatSegment",
    "IatUpdate",
    "Intent",
    "LISTEN_RESULT_FIELDS",
    "MAX_NUMBER",
    "MIN_NUMBER",
    "Operator",
    "PROTOCOL_VERSION",
    "ParseResult",
    "PlaybackResult",
    "PlaybackStatus",
    "ProbeRecorder",
    "ProtocolError",
    "RefereeHttpError",
    "RejectReason",
    "SIMULATED_DATA_NOTICE",
    "ScriptedInput",
    "SimulatedSpeaker",
    "SpeechInput",
    "SpeechListenHandler",
    "SpeechOutput",
    "SpeechSayHandler",
    "Utterance",
    "WindowAttribution",
    "accepted",
    "build_heartbeat",
    "build_listen_result",
    "build_simulated_payload",
    "build_skeleton",
    "default_handlers",
    "extract_numbers",
    "has_question_particle",
    "has_unsafe_number_format",
    "listen_result",
    "new_id",
    "normalize_text",
    "parse",
    "parse_segment",
    "rejected",
    "validate_command",
    "__version__",
]
