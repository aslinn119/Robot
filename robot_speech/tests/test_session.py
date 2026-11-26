"""交互流程（阶段三骨架）的时序测试。

对应上机前必须跑通的三条：

1. 播报结束后才开窗；播报失败或超时则不开窗、提示重试；
2. 迟到结果不能串到下一轮（取消 A → 提议 B → A 的旧确认）；
3. 有效确认只生效一次，重复确认与重播都不会再次提交问答。

C 用 `tests/support/fake_referee.py` 的替身，播报用 `SimulatedSpeaker`。
**这不能证明机器人真的播完了**，只证明流程在拿到「播完」信号后的行为正确。
"""

from __future__ import annotations

import json

import pytest

from robot_speech import (
    EventLog,
    GameSession,
    ScriptedInput,
    SimulatedSpeaker,
    SpeechRefereeClient,
    Utterance,
    parse,
)
from support.fake_referee import FakeReferee


def make_session(script=None, *, default="completed", secret=6, max_questions=7, allow_unverified=False):
    fake = FakeReferee(game_id="g1", secret=secret, max_questions=max_questions)
    client = SpeechRefereeClient(fake, fake.game_id)
    speaker = SimulatedSpeaker(script, default=default)
    session = GameSession(
        client,
        ScriptedInput([]),
        speaker,
        allow_unverified_playback=allow_unverified,
    )
    return fake, client, speaker, session


# ---------------------------------------------------------------------------
# 场景 1：播报结束后才开窗
# ---------------------------------------------------------------------------


def test_window_opens_only_after_playback_completed():
    _, client, speaker, session = make_session(secret=6)

    record = session.process(Utterance("大于五吗"))
    assert record.status == "proposed"
    assert session.window is not None
    # 复述确实读了
    assert speaker.spoken and "比5大" in speaker.spoken[0]
    # 窗口身份在创建时就固定
    window = session.window
    assert window.key == f"{window.pending_key}#{window.window_id}"
    assert window.pending_key == f"{window.game_id}|{window.pending_id}|{window.version}"

    confirmed = session.process(Utterance("确认", window_key=window.key))
    assert confirmed.status == "confirmed"
    assert client.state["remaining"] == 6
    assert len(client.state["history"]) == 1


@pytest.mark.parametrize("outcome", ["failed", "timeout"])
def test_failed_playback_does_not_open_window(outcome):
    _, client, _, session = make_session(script=[outcome])

    record = session.process(Utterance("大于五吗"))
    assert record.status == "recite_failed"
    assert record.detail == outcome
    assert session.window is None
    assert session.awaiting_recitation is True

    # 没有窗口，此时说「确认」不能生效
    confirm = session.process(Utterance("确认"))
    assert confirm.status == "no_pending"
    assert client.state["remaining"] == 7
    assert client.state["history"] == []


def test_retry_recitation_does_not_resubmit_to_referee():
    _, client, speaker, session = make_session(script=["failed", "completed"])
    session.process(Utterance("大于五吗"))

    before = client.request_count
    retry = session.retry_recitation()
    assert retry.status == "proposed"
    assert client.request_count == before        # 没有再发 propose
    assert session.window is not None

    confirmed = session.process(Utterance("确认", window_key=session.window.key))
    assert confirmed.status == "confirmed"


def test_retry_recitation_without_pending_shows_nothing():
    _, _, _, session = make_session()
    record = session.retry_recitation()
    assert record.status == "no_pending_recitation"


def test_unverified_playback_blocks_window_by_default():
    """默认验收路径：没有观察到播完就不开窗。"""
    _, client, _, session = make_session(script=["unverified"])
    record = session.process(Utterance("大于五吗"))
    assert record.status == "recite_unverified_blocked"
    assert session.window is None

    confirm = session.process(Utterance("确认"))
    assert confirm.status == "no_pending"
    assert client.state["remaining"] == 7


def test_unverified_playback_can_be_enabled_diagnostically():
    """显式开启的诊断模式：继续，但日志里要能看出来。"""
    _, _, _, session = make_session(script=["unverified"], allow_unverified=True)
    record = session.process(Utterance("大于五吗"))
    assert record.status == "proposed_unverified"
    assert session.window is not None

    unverified = [r for r in session.log.records if r["event"] == "window.open.unverified"]
    assert len(unverified) == 1


# ---------------------------------------------------------------------------
# 场景 2：迟到结果不能串到下一轮
# ---------------------------------------------------------------------------


def test_late_confirm_from_cancelled_window_is_rejected():
    _, client, _, session = make_session(secret=6)

    session.process(Utterance("大于五吗"))
    key_a = session.window_key

    cancelled = session.process(Utterance("取消", window_key=key_a))
    assert cancelled.status == "cancelled"
    assert session.window is None

    session.process(Utterance("是七吗"))
    key_b = session.window_key
    assert key_b != key_a

    before = client.state
    before_requests = client.request_count

    late = session.process(Utterance("确认", window_key=key_a))

    assert late.status == "stale_confirm"
    assert client.request_count == before_requests   # 根本没有发给 C
    after = client.state
    assert after["remaining"] == before["remaining"] == 7
    assert after["history"] == before["history"] == []
    assert after["pending"]["pending_id"] == before["pending"]["pending_id"]


def test_new_question_supersedes_previous_window():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))
    key_a = session.window_key
    session.process(Utterance("小于八吗"))
    key_b = session.window_key
    assert key_b != key_a

    late = session.process(Utterance("确认", window_key=key_a))
    assert late.status == "stale_confirm"
    assert session.window is not None
    assert session.window_key == key_b


def test_confirm_with_unrelated_window_key_is_rejected():
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    record = session.process(Utterance("确认", window_key="g1|p99|99"))
    assert record.status == "unknown_window"
    assert client.state["remaining"] == 7


def test_confirm_without_any_pending_window():
    _, client, _, session = make_session()
    record = session.process(Utterance("确认"))
    assert record.status == "no_pending"
    assert client.state["remaining"] == 7


def test_affirm_without_window_requires_context():
    """没有确认窗口时，「是」的含义不确定，不能当确认发出去。"""
    _, client, _, session = make_session()
    record = session.process(Utterance("是"))
    assert record.status == "context_required"
    assert client.request_count == 0


# ---------------------------------------------------------------------------
# 场景 3：有效确认只生效一次
# ---------------------------------------------------------------------------


def test_valid_confirm_applies_once_and_repeat_is_rejected():
    _, client, _, session = make_session(secret=6)

    session.process(Utterance("大于五吗"))
    session.process(Utterance("取消", window_key=session.window_key))
    session.process(Utterance("是七吗"))
    key_b = session.window_key

    first = session.process(Utterance("确认", window_key=key_b))
    assert first.status == "confirmed"
    assert len(client.state["history"]) == 1
    assert client.state["remaining"] == 6

    sent_after_first = client.request_count
    second = session.process(Utterance("确认", window_key=key_b))
    assert second.status == "stale_confirm"
    assert client.request_count == sent_after_first
    assert len(client.state["history"]) == 1
    assert client.state["remaining"] == 6


def test_playback_retry_never_resubmits_question():
    """重播只影响喇叭，不影响问答。"""
    _, client, speaker, session = make_session(script=["failed", "completed"])
    session.process(Utterance("大于五吗"))
    requests_before = client.request_count
    remaining_before = client.state["remaining"]
    spoken_before = speaker.call_count

    session.retry_recitation()

    assert client.request_count == requests_before
    assert client.state["remaining"] == remaining_before
    assert speaker.call_count == spoken_before + 1


# ---------------------------------------------------------------------------
# 其它：拒绝输入、C 拒绝、整场运行
# ---------------------------------------------------------------------------


def test_rejected_input_does_not_touch_referee():
    _, client, _, session = make_session()
    record = session.process(Utterance("大于十五吗"))
    assert record.status == "input_rejected"
    assert record.detail == "OUT_OF_RANGE"
    assert client.request_count == 0


def test_referee_rejection_is_surfaced():
    fake = FakeReferee(game_id="g1", max_questions=0)
    client = SpeechRefereeClient(fake, fake.game_id)
    session = GameSession(client, ScriptedInput([]), SimulatedSpeaker())

    record = session.process(Utterance("大于五吗"))
    assert record.status == "referee_rejected"
    assert record.detail == "no_questions_left"
    assert session.window is None


def test_local_control_does_not_touch_referee():
    _, client, _, session = make_session()
    assert session.process(Utterance("暂停")).status == "local_control"
    assert session.process(Utterance("继续")).status == "local_control"
    assert client.request_count == 0


def test_run_end_to_end_with_scripted_input():
    fake = FakeReferee(game_id="g1", secret=6)
    client = SpeechRefereeClient(fake, fake.game_id)
    speaker = SimulatedSpeaker()
    script = ScriptedInput(["大于五吗", "确认", "小于八吗", "确认"])
    session = GameSession(client, script, speaker)

    report = session.run()

    assert [turn.status for turn in report.turns] == [
        "proposed",
        "confirmed",
        "proposed",
        "confirmed",
    ]
    assert client.state["remaining"] == 5
    assert len(client.state["history"]) == 2


def test_turn_record_keeps_event_timeline():
    _, _, _, session = make_session()
    record = session.process(Utterance("大于五吗"))
    names = [name for name, _ in record.events]
    assert names[0] == "input"
    assert "parsed" in names
    assert "proposed" in names
    assert "recited" in names
    assert record.duration >= 0.0


def test_pause_sentence_is_parsed_but_not_proposed():
    """「等一下」在解析层是 PAUSE，不能变成一次提议。"""
    assert parse("等一下").accepted
    _, client, _, session = make_session()
    session.process(Utterance("等一下"))
    assert client.request_count == 0


# ---------------------------------------------------------------------------
# 同一待确认项重开窗口：两扇窗不能共用身份
# ---------------------------------------------------------------------------


def test_reopened_window_for_same_pending_rejects_first_window_result():
    _, client, _, session = make_session(secret=6)

    session.process(Utterance("大于五吗"))
    first = session.window
    assert first is not None

    # 重播复述 = 为同一个待确认项重新开一扇窗
    retry = session.retry_recitation()
    assert retry.status == "proposed"
    second = session.window
    assert second is not None

    assert second.pending_key == first.pending_key   # C 那边还是同一条待确认项
    assert second.key != first.key                   # 但窗口身份必须不同
    assert second.window_id != first.window_id

    requests = client.request_count
    late = session.process(Utterance("确认", window_key=first.key))
    assert late.status == "stale_confirm"
    assert client.request_count == requests
    assert client.state["remaining"] == 7

    ok = session.process(Utterance("确认", window_key=second.key))
    assert ok.status == "confirmed"
    assert client.state["remaining"] == 6


def test_retry_opens_new_window_only_for_the_same_pending():
    """待确认项被换掉时，不能把重播算到新问题上。"""
    _, client, _, session = make_session(script=["failed"], default="completed")
    session.process(Utterance("大于五吗"))
    assert session.awaiting_recitation is True

    # 在重播之前，外部又提了新问题（模拟另一路输入）
    session._client.propose(parse("是七吗"))

    record = session.retry_recitation()
    assert record.status == "pending_changed"
    assert session.window is None
    assert client.state["pending"]["pending_id"] != "p1"


# ---------------------------------------------------------------------------
# 日志：只看记录就能解释「为什么开窗 / 为什么拒收 / 为什么只扣一次」
# ---------------------------------------------------------------------------


def test_log_has_full_timeline_for_one_turn():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))

    events = [record["event"] for record in session.log.records]
    # 锚点在前：换算墙钟时不必先跳到文件末尾找
    assert events[0] == "log.anchor"
    assert events[1] == "session.start"
    for required in (
        "input.received",
        "input.parsed",
        "propose.sent",
        "referee.response",
        "window.create",
        "window.activate",
        "speak.request",
        "speak.result",
        "turn.end",
    ):
        assert required in events, required


def test_log_lines_carry_context():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))

    for record in session.log.records:
        assert record["game_id"] == "g1"
        assert isinstance(record["ts"], float)
        assert "turn" in record
        assert "result" in record

    window_open = next(r for r in session.log.records if r["event"] == "window.activate")
    assert window_open["pending"] == "g1|p1|1"
    assert window_open["window"] == "g1|p1|1#w-0001"

    propose = next(r for r in session.log.records if r["event"] == "propose.sent")
    assert propose["request_id"].startswith("A-")


def test_log_omits_raw_text_by_default():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))
    assert all("text" not in record for record in session.log.records)


def test_log_can_include_raw_text_when_enabled():
    log = EventLog(include_text=True)
    fake = FakeReferee(game_id="g1")
    client = SpeechRefereeClient(fake, fake.game_id)
    session = GameSession(client, ScriptedInput([]), SimulatedSpeaker(), log=log)

    session.process(Utterance("大于五吗"))

    assert any(record.get("text") == "大于五吗" for record in log.records)
    assert any(record.get("text", "").startswith("你是要问") for record in log.records)


def test_log_marks_stale_rejection_as_not_sent():
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    key_a = session.window_key
    session.process(Utterance("取消", window_key=key_a))
    session.process(Utterance("是七吗"))
    session.process(Utterance("确认", window_key=key_a))

    stale = next(r for r in session.log.records if r["event"] == "input.stale")
    assert stale["result"] == "rejected"
    assert stale["data"]["sent_to_referee"] is False
    assert stale["data"]["reason"] == "window_closed"


def test_log_window_close_reason_is_recorded():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))
    session.process(Utterance("取消", window_key=session.window_key))

    closed = next(r for r in session.log.records if r["event"] == "window.close")
    assert closed["result"] == "cancelled"


def test_eventlog_writes_one_json_object_per_line(tmp_path):
    path = tmp_path / "run.jsonl"
    with open(path, "w", encoding="utf-8") as handle:
        log = EventLog(handle, session="unit")
        log.bind_game("g1")
        log.set_turn(1)
        log.emit("x.y", result="ok", data={"a": 1})
        log.emit("x.z", result="failed")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "x.y"
    assert first["game_id"] == "g1"
    assert first["turn"] == 1
    assert first["data"] == {"a": 1}


def test_eventlog_anchor_records_wall_clock():
    log = EventLog()
    anchor = log.anchor(wall_time=1700000000.0)
    assert anchor["event"] == "log.anchor"
    assert anchor["data"]["wall"] == 1700000000.0
