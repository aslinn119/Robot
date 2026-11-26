"""A 的两条命令与命令循环的测试（对真 HTTP 假服务）。"""

from __future__ import annotations

import time

import pytest

from robot_speech.command_agent import CommandAgent, CommandContext
from robot_speech.http_client import HttpRefereeClient
from robot_speech.simulated_devices import ScriptedInput, SimulatedSpeaker
from robot_speech.speech_commands import (
    SpeechListenHandler,
    SpeechSayHandler,
    build_listen_result,
    next_utterance,
)
from robot_speech.speech_parser import parse
from robot_speech.team_protocol import (
    COMMAND_SPEECH_LISTEN,
    COMMAND_SPEECH_SAY,
    LISTEN_RESULT_FIELDS,
    PROTOCOL_VERSION,
    new_id,
)
from support.fake_c_server import FakeCReferee

TOKEN = "test-token"


class _StubClient:
    instance_id = "0" * 32

    def command_status(self, command_id):  # noqa: ARG002
        return {"status": "running", "cancel_requested": False}

    def post_event(self, event):  # noqa: ARG002
        return {"ok": True}


def make_ctx(payload, *, command_type=COMMAND_SPEECH_LISTEN, timeout_ms=15000, client=None):
    command = {
        "protocol_version": PROTOCOL_VERSION,
        "command_id": new_id(),
        "game_id": new_id(),
        "input_epoch": 0,
        "target": "A",
        "command_type": command_type,
        "timeout_ms": timeout_ms,
        "payload": payload,
    }
    return CommandContext(command, client or _StubClient(), clock=time.monotonic)


SAY_PAYLOAD = {"text": "请提出你的问题。", "purpose": "prompt", "answer_id": None, "sync_group_id": None}
LISTEN_PAYLOAD = {
    "allowed_intents": ["question", "final_submit", "pause", "exit", "repeat_last", "help"],
    "pending_id": None,
    "pending_version": None,
    "question_id": None,
    "max_listen_ms": 15000,
}


# ---------------------------------------------------------------------------
# speech.say：必须真的播完才回 success
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, expected_status, expected_code",
    [
        (["completed"], "success", None),
        (["unverified"], "failed", "CAPABILITY_UNAVAILABLE"),
        (["failed"], "failed", "TTS_FAILED"),
        (["timeout"], "failed", "TIMEOUT"),
    ],
)
def test_say_reports_real_outcome(script, expected_status, expected_code):
    handler = SpeechSayHandler(SimulatedSpeaker(script))
    outcome = handler(make_ctx(SAY_PAYLOAD, command_type=COMMAND_SPEECH_SAY))

    assert outcome.status == expected_status
    if expected_code is None:
        assert outcome.result == {"spoken": True}
    else:
        assert outcome.error["code"] == expected_code


def test_say_requires_text():
    outcome = SpeechSayHandler(SimulatedSpeaker())(make_ctx({"text": ""}, command_type=COMMAND_SPEECH_SAY))
    assert outcome.status == "failed"
    assert outcome.error["code"] == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# speech.listen：十个字段 + allowed_intents 约束
# ---------------------------------------------------------------------------


def _listen(text, payload=None, scripts=None):
    payload = dict(payload or LISTEN_PAYLOAD)
    handler = SpeechListenHandler(ScriptedInput([text]))
    return handler(make_ctx(payload))


def test_question_maps_comparison_and_number():
    outcome = _listen("大于五吗")
    assert outcome.status == "success"
    result = outcome.result
    assert tuple(result) == LISTEN_RESULT_FIELDS
    assert result["intent"] == "question"
    assert result["comparison"] == "gt"
    assert result["number"] == 5
    assert result["pending_id"] is None
    assert result["parser"] == "rule"


def test_final_submit_maps_number():
    result = _listen("我确定是七").result
    assert result["intent"] == "final_submit"
    assert result["number"] == 7
    assert result["comparison"] is None


def test_answer_returns_question_id():
    payload = dict(LISTEN_PAYLOAD, allowed_intents=["answer"], question_id=new_id())
    result = _listen("是的", payload).result
    assert result["intent"] == "answer"
    assert result["answer"] is True
    assert result["question_id"] == payload["question_id"]

    denied = _listen("不是", payload).result
    assert denied["answer"] is False


def test_confirm_echoes_pending_binding():
    pending_id = new_id()
    payload = dict(
        LISTEN_PAYLOAD,
        allowed_intents=["confirm", "cancel", "pause", "exit", "help"],
        pending_id=pending_id,
        pending_version=3,
    )
    result = _listen("确认", payload).result
    assert result["intent"] == "confirm"
    assert result["pending_id"] == pending_id
    assert result["pending_version"] == 3

    cancelled = _listen("取消", payload).result
    assert cancelled["intent"] == "cancel"
    assert cancelled["pending_id"] == pending_id


def test_confirm_window_maps_yes_no_to_confirm_cancel():
    """确认窗口里玩家说「是/不是」，必须变成 confirm/cancel，而不是 answer。"""
    pending_id = new_id()
    payload = dict(
        LISTEN_PAYLOAD,
        allowed_intents=["confirm", "cancel", "pause", "exit", "help"],
        pending_id=pending_id,
        pending_version=2,
    )

    yes = _listen("是的", payload).result
    assert yes["intent"] == "confirm"
    assert yes["pending_id"] == pending_id
    assert yes["pending_version"] == 2

    no = _listen("不对", payload).result
    assert no["intent"] == "cancel"
    assert no["pending_id"] == pending_id


def test_confirm_window_without_pending_binding_is_rejected():
    payload = dict(
        LISTEN_PAYLOAD,
        allowed_intents=["confirm", "cancel"],
        pending_id=None,
        pending_version=None,
    )
    outcome = _listen("确认", payload)
    assert outcome.status == "failed"
    assert outcome.error["code"] == "BAD_REQUEST"


def test_answer_window_without_question_id_is_rejected():
    payload = dict(LISTEN_PAYLOAD, allowed_intents=["answer"], question_id=None)
    outcome = _listen("是的", payload)
    assert outcome.status == "failed"
    assert outcome.error["code"] == "BAD_REQUEST"


def test_intent_outside_allowed_becomes_unsupported():
    # 当前窗口只允许答案，玩家却说了一个问题
    payload = dict(LISTEN_PAYLOAD, allowed_intents=["answer"], question_id=new_id())
    result = _listen("大于五吗", payload).result
    assert result["intent"] == "unsupported"
    assert result["reason"] == "unsupported"


@pytest.mark.parametrize(
    "text, expected_reason",
    [
        ("大于五而且小于八吗", "ambiguous"),
        ("是不是七", "ambiguous"),
        ("大于十五吗", "ambiguous"),
        ("今天天气不错", "unsupported"),
    ],
)
def test_reject_reasons_are_classified(text, expected_reason):
    result = _listen(text).result
    assert result["intent"] == "unsupported"
    assert result["reason"] == expected_reason


def test_no_speech_is_task_failure_not_intent():
    handler = SpeechListenHandler(ScriptedInput([]))
    outcome = handler(make_ctx(dict(LISTEN_PAYLOAD, max_listen_ms=50)))
    assert outcome.status == "failed"
    assert outcome.error["code"] == "NO_SPEECH"


def test_listen_drains_stale_backlog_before_polling():
    class DrainableInput:
        drain_before_listen = True

        def __init__(self) -> None:
            self.drained = False

        def drain(self) -> int:
            self.drained = True
            return 1

        def poll(self, timeout: float = 0.0):  # noqa: ARG002
            from robot_speech.ports import Utterance

            return Utterance(text="大于五吗") if self.drained else Utterance(text="旧回声")

    outcome = SpeechListenHandler(DrainableInput())(make_ctx(LISTEN_PAYLOAD))
    assert outcome.status == "success"
    assert outcome.result["number"] == 5


def test_listen_cancelled_mid_wait_returns_cancelled():
    class CancellingClient(_StubClient):
        def __init__(self) -> None:
            self.calls = 0

        def command_status(self, command_id):  # noqa: ARG002
            self.calls += 1
            return {"status": "cancel_requested" if self.calls >= 2 else "running", "cancel_requested": self.calls >= 2}

    class SilentPollInput:
        def poll(self, timeout: float = 0.0):  # noqa: ARG002
            time.sleep(0.02)
            return None

    ctx = CommandContext(
        {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": new_id(),
            "game_id": new_id(),
            "input_epoch": 0,
            "target": "A",
            "command_type": COMMAND_SPEECH_LISTEN,
            "timeout_ms": 15000,
            "payload": LISTEN_PAYLOAD,
        },
        CancellingClient(),
        cancel_poll_interval=0.0,
    )
    outcome = SpeechListenHandler(SilentPollInput())(ctx)
    assert outcome.status == "cancelled"
    assert outcome.error["code"] == "CANCELLED"


def test_next_utterance_respects_deadline():
    class NeverInput:
        def stream(self):
            while True:
                time.sleep(0.02)
                yield None  # 永远不会给出语音

    deadline = time.monotonic() + 0.1
    assert next_utterance(NeverInput(), deadline) is None


def test_build_listen_result_is_pure():
    result = build_listen_result(parse("是七吗"), LISTEN_PAYLOAD, "是七吗")
    assert result["comparison"] == "eq" and result["number"] == 7


# ---------------------------------------------------------------------------
# 命令循环（真 HTTP 假 C）
# ---------------------------------------------------------------------------


@pytest.fixture()
def referee():
    server = FakeCReferee(token=TOKEN)
    base_url = server.start()
    server.base_url = base_url  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        server.stop()


def _agent(referee, speaker_script=("completed",), utterances=("大于五吗",)):
    client = HttpRefereeClient(referee.base_url, TOKEN, source="A", sleep=lambda _s: None)
    speaker = SimulatedSpeaker(list(speaker_script))
    agent = CommandAgent(
        client,
        {
            COMMAND_SPEECH_SAY: SpeechSayHandler(speaker),
            COMMAND_SPEECH_LISTEN: SpeechListenHandler(ScriptedInput(list(utterances))),
        },
    )
    return agent, client


def test_agent_runs_command_lifecycle(referee):
    agent, _ = _agent(referee)
    referee.enqueue(COMMAND_SPEECH_SAY, SAY_PAYLOAD)

    command = referee.commands[0]
    assert agent.handle(command) is True

    assert [e["event_type"] for e in referee.events] == ["task.accepted", "task.started", "task.result"]
    result = referee.results()[0]["payload"]
    assert result["status"] == "success"
    assert result["result"] == {"spoken": True}
    assert result["error"] is None


def test_agent_reports_listen_result_over_http(referee):
    agent, _ = _agent(referee)
    referee.enqueue(COMMAND_SPEECH_LISTEN, LISTEN_PAYLOAD)

    agent.handle(referee.commands[0])

    result = referee.results()[0]["payload"]["result"]
    assert result["intent"] == "question"
    assert result["number"] == 5


def test_agent_does_not_repeat_same_command_id(referee):
    agent, _ = _agent(referee)
    referee.enqueue(COMMAND_SPEECH_SAY, SAY_PAYLOAD)
    command = referee.commands[0]

    assert agent.handle(command) is True
    assert agent.handle(command) is False
    assert len(referee.results()) == 1


def test_agent_skips_command_cancelled_before_start(referee):
    agent, _ = _agent(referee)
    referee.enqueue(COMMAND_SPEECH_SAY, SAY_PAYLOAD)
    command = referee.commands[0]
    referee.request_cancel(command["command_id"])

    assert agent.handle(command) is False
    events = [e["event_type"] for e in referee.events]
    assert events == ["task.accepted", "task.result"]
    assert referee.results()[0]["payload"]["status"] == "cancelled"


def test_agent_does_not_run_when_c_refuses_accept(referee):
    agent, _ = _agent(referee)
    referee.enqueue(COMMAND_SPEECH_SAY, SAY_PAYLOAD)
    command = referee.commands[0]
    referee.rejected_accepts.add(command["command_id"])

    assert agent.handle(command) is False
    started = [e for e in referee.events if e["event_type"] == "task.started"]
    assert started == []


def test_agent_reports_failure_for_unknown_command_type(referee):
    agent, _ = _agent(referee)
    referee.enqueue("speech.unknown", {})

    agent.handle(referee.commands[0])
    result = referee.results()[0]["payload"]
    assert result["status"] == "failed"
    assert result["error"]["code"] == "INTERNAL_ERROR"


def test_heartbeat_payload_matches_spec(referee):
    agent, _ = _agent(referee)
    agent.post_heartbeat()
    heartbeat = referee.events_of("module.heartbeat")[0]
    payload = heartbeat["payload"]
    assert set(payload) == {"instance_id", "module_status", "active_command_ids", "capabilities", "runtime_mode"}
    assert payload["capabilities"] == ["speech.say", "speech.listen"]


def test_client_requires_token(referee):
    from robot_speech.http_client import RefereeHttpError

    client = HttpRefereeClient(referee.base_url, "wrong-token", source="A", sleep=lambda _s: None)
    with pytest.raises(RefereeHttpError) as excinfo:
        client.pull_command(wait_ms=0)
    assert excinfo.value.status == 401


def test_client_pull_returns_none_when_empty(referee):
    client = HttpRefereeClient(referee.base_url, TOKEN, source="A", sleep=lambda _s: None)
    assert client.pull_command(wait_ms=0) is None
