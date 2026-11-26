"""窗口归属与设备探测的测试。

重点：实机上不可能总是拿到「采集时绑定」的窗口标识。这里验证两种情况：

1. 结果在窗口生效**之前**到达 → 即使 key 对得上，也必须判为过期；
2. 归属完全未知 → **只观察，不提交**。
"""

from __future__ import annotations

import pytest

from robot_speech import (
    GameSession,
    ProbeRecorder,
    ScriptedInput,
    SimulatedSpeaker,
    SpeechRefereeClient,
    Utterance,
    WindowAttribution,
    parse,
)
from robot_speech.probe import resolve_probe_config
from support.fake_referee import FakeReferee


class FakeClock:
    """可控单调时钟。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_session(*, secret: int = 6, allow_inferred: bool = False):
    clock = FakeClock()
    fake = FakeReferee(game_id="g1", secret=secret)
    client = SpeechRefereeClient(fake, fake.game_id)
    speaker = SimulatedSpeaker()
    session = GameSession(
        client,
        ScriptedInput([]),
        speaker,
        clock=clock,
        allow_inferred_attribution=allow_inferred,
    )
    return clock, client, speaker, session


# ---------------------------------------------------------------------------
# 1. 到达早于窗口生效 → 即使 key 一致也判过期
# ---------------------------------------------------------------------------


def test_result_arriving_before_window_opens_is_stale_even_with_matching_key():
    """即使放开了「按到达时间提交」，时间判据仍然兜底。"""
    clock, client, _, session = make_session(allow_inferred=True)

    session.process(Utterance("大于五吗"))
    key = session.window_key
    assert key is not None
    opened_at = clock.now

    # 这条结果在窗口生效之前就到了，只是被晚处理
    early = Utterance(
        "确认",
        window_key=key,
        captured_at=opened_at - 0.5,
        window_source=WindowAttribution.ARRIVAL,
    )
    record = session.process(early)

    assert record.status == "stale_confirm"
    assert client.state["remaining"] == 7
    assert client.state["history"] == []

    stale = next(r for r in session.log.records if r["event"] == "input.stale")
    assert stale["data"]["reason"] == "arrived_before_window"
    assert stale["data"]["sent_to_referee"] is False


def test_result_arriving_after_window_opens_is_accepted():
    clock, client, _, session = make_session(allow_inferred=True)

    session.process(Utterance("大于五吗"))
    key = session.window_key
    clock.advance(1.0)

    record = session.process(
        Utterance(
            "确认",
            window_key=key,
            captured_at=clock.now,
            window_source=WindowAttribution.ARRIVAL,
        )
    )
    assert record.status == "confirmed"
    assert client.state["remaining"] == 6


def test_offline_utterance_without_timestamp_is_not_affected():
    """没有到达时刻就跳过时间判据，避免误杀离线脚本。"""
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    record = session.process(Utterance("确认", window_key=session.window_key))
    assert record.status == "confirmed"
    assert client.state["remaining"] == 6


# ---------------------------------------------------------------------------
# 2. 归属未知 → 只观察，不提交
# ---------------------------------------------------------------------------


def test_unknown_attribution_is_not_submitted():
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    requests = client.request_count

    record = session.process(
        Utterance(
            "确认",
            window_key=session.window_key,
            window_source=WindowAttribution.UNKNOWN,
        )
    )

    assert record.status == "attribution_untrusted"
    assert client.request_count == requests        # 一个请求都没发
    assert client.state["remaining"] == 7

    event = next(r for r in session.log.records if r["event"] == "input.attribution")
    assert event["result"] == "unknown"
    assert event["data"]["submitted"] is False
    assert event["data"]["note"] == "observation_only"


def test_unknown_attribution_blocks_cancel_too():
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    requests = client.request_count

    record = session.process(
        Utterance("取消", window_key=session.window_key, window_source=WindowAttribution.UNKNOWN)
    )

    assert record.status == "attribution_untrusted"
    assert client.request_count == requests
    assert session.window is not None


def test_arrival_attribution_is_rejected_by_default():
    """默认只接受采集时绑定的确认。"""
    _, client, _, session = make_session()
    session.process(Utterance("大于五吗"))
    requests = client.request_count

    record = session.process(
        Utterance(
            "确认",
            window_key=session.window_key,
            captured_at=None,
            window_source=WindowAttribution.ARRIVAL,
        )
    )

    assert record.status == "attribution_inferred"
    assert client.request_count == requests
    assert client.state["remaining"] == 7

    event = next(r for r in session.log.records if r["event"] == "input.attribution")
    assert event["result"] == "inferred"
    assert event["data"]["submitted"] is False
    assert event["data"]["note"] == "requires_capture_binding"


def test_result_from_window_a_arriving_after_b_opens_does_not_confirm_b():
    """评审要求的场景：A 的确认在 B 开窗后才到，不能算到 B 头上。

    这条结果到达时，窗口标识会指向 B（实机只能按到达时刻推断），
    所以默认策略必须直接拒收，而不是依赖 key。
    """
    clock, client, _, session = make_session()

    session.process(Utterance("大于五吗"))
    key_a = session.window_key
    session.process(Utterance("取消", window_key=key_a))
    session.process(Utterance("是七吗"))
    key_b = session.window_key
    assert key_b != key_a

    requests = client.request_count
    state_before = client.state

    # 玩家其实是在 A 说的「确认」，但结果现在才到，到达时窗口是 B
    record = session.process(
        Utterance(
            "确认",
            window_key=key_b,
            captured_at=clock.now,
            window_source=WindowAttribution.ARRIVAL,
        )
    )

    assert record.status == "attribution_inferred"
    # C 一个请求都没收到
    assert client.request_count == requests
    # B 仍然待确认
    assert session.window is not None
    assert session.window.key == key_b
    state_after = client.state
    assert state_after["pending"]["pending_id"] == state_before["pending"]["pending_id"]
    assert state_after["remaining"] == state_before["remaining"] == 7
    assert state_after["history"] == state_before["history"] == []


def test_arrival_attribution_submits_only_when_opted_in():
    """显式开启实验模式时才允许按到达时间提交，并且日志必须标 inferred。"""
    _, client, _, session = make_session(allow_inferred=True)
    session.process(Utterance("大于五吗"))

    record = session.process(
        Utterance(
            "确认",
            window_key=session.window_key,
            captured_at=None,
            window_source=WindowAttribution.ARRIVAL,
        )
    )

    assert record.status == "confirmed"
    assert client.state["remaining"] == 6
    event = next(r for r in session.log.records if r["event"] == "input.attribution")
    assert event["result"] == "inferred"
    assert event["data"]["submitted"] is True


def test_capture_attribution_is_logged_as_captured():
    _, _, _, session = make_session()
    session.process(Utterance("大于五吗"))
    session.process(
        Utterance(
            "确认",
            window_key=session.window_key,
            window_source=WindowAttribution.CAPTURE,
        )
    )

    event = next(r for r in session.log.records if r["event"] == "input.attribution")
    assert event["result"] == "captured"
    assert event["data"]["note"] == "bound_at_capture"


def test_input_log_records_attribution_metadata():
    _, _, _, session = make_session()
    session.process(
        Utterance(
            "大于五吗",
            window_source=WindowAttribution.ARRIVAL,
            captured_at=1234.5,
        )
    )
    received = next(r for r in session.log.records if r["event"] == "input.received")
    assert received["data"]["window_source"] == "arrival"
    assert received["data"]["captured_at"] == 1234.5


# ---------------------------------------------------------------------------
# 3. ProbeRecorder：设备观察
# ---------------------------------------------------------------------------


def test_probe_records_topic_arrivals_and_counts():
    from robot_speech import EventLog

    log = EventLog()
    probe = ProbeRecorder(log)

    probe.note_subscribed("/aiui/iat")
    probe.note_message("/aiui/iat", b"abc")
    probe.note_message("/aiui/iat", b"abcd")

    messages = [r for r in log.records if r["event"] == "probe.message"]
    assert len(messages) == 2
    assert messages[0]["data"]["topic"] == "/aiui/iat"
    assert messages[0]["data"]["size"] == 3
    assert messages[1]["data"]["count_on_topic"] == 2
    assert probe.topic_summary() == [{"topic": "/aiui/iat", "count": 2}]


def test_probe_watch_window_counts_only_inside():
    from robot_speech import EventLog

    log = EventLog()
    probe = ProbeRecorder(log)

    probe.note_message("/aiui/nlp", b"before")
    probe.begin_watch("after_tts", 3.0)
    probe.note_message("/aiui/nlp", b"inside")
    probe.note_message("/aiui/iat", b"inside2")
    summary = probe.end_watch()

    assert summary["messages"] == 2
    assert summary["by_topic"] == {"/aiui/nlp": 1, "/aiui/iat": 1}

    message = next(r for r in log.records if r["event"] == "probe.message")
    assert message["data"]["in_watch"] is False

    inside = [r for r in log.records if r["event"] == "probe.message" and r["data"]["in_watch"]]
    assert len(inside) == 2

    ended = next(r for r in log.records if r["event"] == "probe.watch.end")
    assert ended["result"] == "completed"
    assert ended["data"]["messages"] == 2


def test_probe_end_watch_without_begin():
    from robot_speech import EventLog

    probe = ProbeRecorder(EventLog())
    summary = probe.end_watch()
    assert summary["label"] is None
    assert summary["messages"] == 0


# ---------------------------------------------------------------------------
# 4. 诊断入口的启动参数：不带任何参数也必须能起来
# ---------------------------------------------------------------------------

_MISSING = object()


class FakeParams:
    """模仿 rospy.get_param：不给默认值且参数不存在时抛 KeyError。"""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def __call__(self, key, default=_MISSING):
        if key in self.values:
            return self.values[key]
        if default is _MISSING:
            raise KeyError(key)
        return default


def test_probe_config_works_with_no_parameters_at_all():
    """回归：`get_param("~run_id")` 不带默认值会抛 KeyError，脚本起不来。"""
    config = resolve_probe_config(FakeParams())

    assert config.run_id
    assert config.log_path.endswith(f"probe-{config.run_id}.jsonl")
    assert config.topics == ("/aiui/nlp", "/aiui/iat", "/aiui/wakeup")
    assert config.watch_seconds == 8.0
    assert config.tts_service == "/aiui/text_to_speak"
    assert config.include_text is False


def test_probe_config_honours_overrides():
    params = FakeParams(
        {
            "~run_id": "lab-1",
            "~topics": "/a, /b ,",
            "~watch_seconds": 3,
            "~tts_service": "/tts",
            "~log_raw_text": True,
        }
    )
    config = resolve_probe_config(params)

    assert config.run_id == "lab-1"
    assert config.log_path.endswith("probe-lab-1.jsonl")
    assert config.topics == ("/a", "/b")
    assert config.watch_seconds == 3.0
    assert config.tts_service == "/tts"
    assert config.include_text is True


def test_probe_config_uses_explicit_log_path():
    params = FakeParams({"~run_id": "x", "~log_path": "/tmp/custom.jsonl"})
    config = resolve_probe_config(params)
    assert config.log_path == "/tmp/custom.jsonl"
