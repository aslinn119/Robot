"""TEAM_INTERFACE v1.0 的格式层测试（不涉及网络）。"""

from __future__ import annotations

import pytest

from robot_speech.team_protocol import (
    COMMAND_FIELDS,
    ENVELOPE_FIELDS,
    LISTEN_RESULT_FIELDS,
    PROTOCOL_VERSION,
    ProtocolError,
    build_event,
    build_heartbeat,
    is_valid_id,
    listen_result,
    new_id,
    task_result_cancelled,
    task_result_failure,
    task_result_success,
    validate_command,
)


def _command(**overrides):
    command = {
        "protocol_version": PROTOCOL_VERSION,
        "command_id": new_id(),
        "game_id": new_id(),
        "input_epoch": 0,
        "target": "A",
        "command_type": "speech.say",
        "timeout_ms": 15000,
        "payload": {"text": "你好"},
    }
    command.update(overrides)
    return command


# ---------------------------------------------------------------------------
# ID 与信封
# ---------------------------------------------------------------------------


def test_new_id_is_32_lowercase_hex():
    value = new_id()
    assert len(value) == 32
    assert is_valid_id(value)
    assert value == value.lower()


@pytest.mark.parametrize("bad", ["A-0001", "ABC", "a" * 31, "a" * 33, "G" * 32, "", None])
def test_invalid_ids_rejected(bad):
    assert not is_valid_id(bad)
    with pytest.raises(ProtocolError):
        build_event(
            request_id=bad,
            game_id=new_id(),
            input_epoch=0,
            source="A",
            command_id=None,
            event_type="task.started",
        )


def test_event_envelope_has_exactly_eight_fields():
    event = build_event(
        request_id=new_id(),
        game_id=new_id(),
        input_epoch=0,
        source="A",
        command_id=new_id(),
        event_type="task.started",
    )
    assert tuple(event) == ENVELOPE_FIELDS
    assert len(event) == 8


def test_event_rejects_extra_fields():
    with pytest.raises(ProtocolError) as excinfo:
        build_event(
            request_id=new_id(),
            game_id=new_id(),
            input_epoch=0,
            source="A",
            command_id=new_id(),
            event_type="task.started",
            extra={"debug": 1},
        )
    assert excinfo.value.reason == "ENVELOPE_EXTRA_FIELD"


def test_non_heartbeat_event_requires_game_and_epoch():
    with pytest.raises(ProtocolError):
        build_event(
            request_id=new_id(),
            game_id=None,
            input_epoch=0,
            source="A",
            command_id=None,
            event_type="task.started",
        )


def test_heartbeat_allows_null_game_and_epoch():
    event = build_heartbeat(instance_id=new_id())
    assert tuple(event) == ENVELOPE_FIELDS
    assert event["game_id"] is None
    assert event["input_epoch"] is None
    assert event["command_id"] is None
    payload = event["payload"]
    assert payload["capabilities"] == ["speech.say", "speech.listen"]
    assert payload["runtime_mode"] == "mock"


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


def test_command_accepts_exact_fields():
    command = _command()
    assert validate_command(command) == command


def test_command_rejects_missing_and_extra_fields():
    missing = _command()
    missing.pop("timeout_ms")
    with pytest.raises(ProtocolError) as excinfo:
        validate_command(missing)
    assert excinfo.value.reason == "COMMAND_MISSING_FIELDS"

    extra = _command(debug=True)
    with pytest.raises(ProtocolError) as excinfo:
        validate_command(extra)
    assert excinfo.value.reason == "COMMAND_EXTRA_FIELDS"


def test_command_rejects_bad_version_and_ids():
    with pytest.raises(ProtocolError):
        validate_command(_command(protocol_version="0.9"))
    with pytest.raises(ProtocolError):
        validate_command(_command(game_id="g1"))
    with pytest.raises(ProtocolError):
        validate_command(_command(timeout_ms=0))


def test_command_fields_constant_matches():
    assert len(COMMAND_FIELDS) == 8


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------


def test_listen_result_has_exactly_ten_fields():
    result = listen_result(intent="question", comparison="gt", number=5, utterance="大于五吗")
    assert tuple(result) == LISTEN_RESULT_FIELDS
    assert len(result) == 10


def test_listen_result_truncates_utterance_to_160():
    result = listen_result(intent="help", utterance="啊" * 300)
    assert len(result["utterance"]) == 160


def test_task_result_shapes():
    assert task_result_success({"spoken": True}) == {
        "status": "success",
        "result": {"spoken": True},
        "error": None,
    }
    failed = task_result_failure("TTS_FAILED", "坏了")
    assert failed["status"] == "failed" and failed["result"] is None
    assert failed["error"]["code"] == "TTS_FAILED"
    cancelled = task_result_cancelled()
    assert cancelled["status"] == "cancelled"
    assert cancelled["error"]["code"] == "CANCELLED"
