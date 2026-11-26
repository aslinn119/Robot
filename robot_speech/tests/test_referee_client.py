"""A → C 适配层的时序测试。

核心场景（评审指定）：
    提议 A → 打开 A 的确认窗口 → 取消 A → 提议 B → A 的旧确认迟到

断言：旧确认仍携带开窗时绑定的 A 的 pending_id / version，不会确认 B，
也不会改变次数和历史；随后对 B 的有效确认只生效一次，重试同一 request_id 不会重复计次。

C 用 `tests/support/fake_referee.py` 的最小替身，**不是**真实裁判实现。
同一局内「旧待确认项」的错误码 v0.2 未定义，测试只锁定「拒绝且状态不变」。
"""

from __future__ import annotations

import pytest

from robot_speech import SpeechRefereeClient, parse
from robot_speech.referee_client import ConfirmWindow, NoPendingToConfirm
from robot_speech.referee_protocol import (
    Action,
    UnmappableIntent,
    action_for,
    build_event,
    confirm_payload,
    propose_payload,
)
from support.fake_referee import FakeReferee


def make_client(**kwargs):
    fake = FakeReferee(**{k: v for k, v in kwargs.items() if k in ("game_id", "secret", "max_questions")})
    client_kwargs = {k: v for k, v in kwargs.items() if k not in ("game_id", "secret", "max_questions")}
    return fake, SpeechRefereeClient(fake, fake.game_id, **client_kwargs)


# ---------------------------------------------------------------------------
# 1. 解析结果 → propose payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("大于五吗", {"kind": "gt", "number": 5}),
        ("小于八吗", {"kind": "lt", "number": 8}),
        ("是七吗", {"kind": "eq", "number": 7}),
        ("我确定是七", {"kind": "submit", "number": 7}),
        ("退出", {"kind": "exit", "number": None}),
    ],
)
def test_propose_payload_mapping(text, expected):
    assert propose_payload(parse(text)) == expected


@pytest.mark.parametrize("text", ["确认", "取消", "暂停", "继续", "是", "不是", "今天天气不错"])
def test_non_propose_intents_cannot_be_sent_as_propose(text):
    with pytest.raises(UnmappableIntent):
        propose_payload(parse(text))


def test_confirm_payload_is_exactly_two_fields():
    assert confirm_payload("p3", 3) == {"pending_id": "p3", "version": 3}


def test_confirm_payload_rejects_bad_arguments():
    with pytest.raises(ValueError):
        confirm_payload("", 1)
    with pytest.raises(ValueError):
        confirm_payload("p1", "1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. action_for：谁走 propose、谁走 confirm，以及「是」为什么不能自己猜
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, window_open, expected",
    [
        ("大于五吗", False, Action.PROPOSE),
        ("我确定是七", False, Action.PROPOSE),
        ("退出", False, Action.PROPOSE),
        ("确认", False, Action.CONFIRM),
        ("取消", False, Action.CANCEL),
        ("暂停", False, Action.LOCAL),
        ("继续", False, Action.LOCAL),
        ("是", False, Action.REJECT),      # 没有确认窗口时，「是」含义不明
        ("是", True, Action.CONFIRM),      # 确认窗口里才是确认
        ("不是", True, Action.CANCEL),
        ("今天天气不错", True, Action.REJECT),
    ],
)
def test_action_for(text, window_open, expected):
    assert action_for(parse(text), confirm_window_open=window_open) is expected


def test_client_refuses_to_send_confirm_as_propose():
    _, client = make_client()
    with pytest.raises(UnmappableIntent):
        client.propose(parse("确认"))


# ---------------------------------------------------------------------------
# 3. 核心场景：取消 A → 提议 B → A 的旧确认迟到
# ---------------------------------------------------------------------------


def test_late_confirm_after_cancel_does_not_touch_new_pending():
    fake, client = make_client(secret=6)

    # ① 提议 A，并在开窗时绑定
    sent_a = client.propose(parse("大于五吗"))
    assert sent_a.ok and sent_a.duplicate is False
    window_a = client.open_confirm_window()
    assert isinstance(window_a, ConfirmWindow)
    assert window_a.kind == "gt" and window_a.number == 5

    # ② 取消 A
    cancelled = client.cancel(window_a)
    assert cancelled.ok
    after_cancel = client.state
    assert after_cancel["pending"] is None
    assert after_cancel["remaining"] == 7
    assert after_cancel["history"] == []

    # ③ 提议 B
    sent_b = client.propose(parse("是七吗"))
    assert sent_b.ok
    window_b = client.open_confirm_window()
    assert window_b.pending_id != window_a.pending_id
    assert window_b.version != window_a.version
    after_b = client.state

    # ④ A 的旧确认迟到：仍然携带 A 的 pending_id 与 version
    late = client.confirm(window_a)
    assert late.event["payload"] == {
        "pending_id": window_a.pending_id,
        "version": window_a.version,
    }
    assert late.ok is False
    # v0.2 未定义同一局内旧待确认项的错误码，先只断言「被拒绝」，具体码待与 C 对齐
    assert late.code

    # ⑤ 状态完全没变：没有确认 B、没有计次、没有写历史
    after_late = client.state
    assert after_late["history"] == after_b["history"] == []
    assert after_late["remaining"] == after_b["remaining"] == 7
    assert after_late["pending"]["pending_id"] == window_b.pending_id
    assert after_late["pending"]["version"] == window_b.version


def test_window_version_does_not_drift_after_new_propose():
    _, client = make_client()
    client.propose(parse("大于五吗"))
    window_a = client.open_confirm_window()
    client.cancel(window_a)
    client.propose(parse("小于八吗"))

    assert window_a.version == 1
    assert client.is_stale(window_a) is True
    sent = client.confirm(window_a)
    assert sent.event["payload"] == {"pending_id": window_a.pending_id, "version": 1}


def test_late_confirm_without_cancel_is_also_rejected():
    """不取消直接提新问题，旧确认同样必须被拒（pending 被替换）。"""
    _, client = make_client()
    client.propose(parse("大于五吗"))
    window_a = client.open_confirm_window()
    client.propose(parse("小于八吗"))

    late = client.confirm(window_a)
    assert late.ok is False
    state = client.state
    assert state["remaining"] == 7
    assert state["history"] == []


# ---------------------------------------------------------------------------
# 4. 有效确认只生效一次；重试同一 request_id 不重复计次
# ---------------------------------------------------------------------------


def test_valid_confirm_applies_once_and_retry_is_idempotent():
    fake, client = make_client(secret=6)
    client.propose(parse("大于五吗"))
    window = client.open_confirm_window()

    first = client.confirm(window)
    assert first.ok and first.duplicate is False
    state = client.state
    assert state["remaining"] == 6
    assert len(state["history"]) == 1
    assert state["history"][0]["answer"] is True   # 6 > 5

    retry = client.resend(first)
    assert retry.request_id == first.request_id
    assert retry.duplicate is True
    after = client.state
    assert after["remaining"] == 6
    assert len(after["history"]) == 1


def test_cancel_does_not_change_counts():
    _, client = make_client()
    client.propose(parse("大于五吗"))
    window = client.open_confirm_window()
    cancelled = client.cancel(window)
    assert cancelled.ok

    state = client.state
    assert state["remaining"] == 7
    assert state["history"] == []
    assert state["pending"] is None


def test_business_reject_is_cached_and_retriable():
    _, client = make_client()
    sent = client.send_propose({"kind": "gt", "number": 15})
    assert sent.ok is False
    assert sent.code == "bad_payload"

    again = client.resend(sent)
    assert again.duplicate is True
    assert again.ok is False


# ---------------------------------------------------------------------------
# 5. 去重、旧局、重复响应里的快照
# ---------------------------------------------------------------------------


def test_reused_request_id_with_different_content_conflicts():
    fake, client = make_client()
    sent = client.propose(parse("大于五吗"))

    tampered = dict(sent.event)
    tampered["payload"] = {"kind": "lt", "number": 5}
    response = fake.handle(tampered)

    assert response["ok"] is False
    assert response["code"] == "request_conflict"


def test_other_game_is_rejected_as_stale():
    fake = FakeReferee(game_id="g1")
    client = SpeechRefereeClient(fake, "g2")
    sent = client.propose(parse("大于五吗"))
    assert sent.ok is False
    assert sent.code == "stale_game"


def test_duplicate_response_does_not_restore_stale_state():
    """重复响应里的 state 是处理时快照，不能拿来刷新当前状态。"""
    _, client = make_client()
    sent = client.propose(parse("大于五吗"))
    window = client.open_confirm_window()
    client.cancel(window)
    assert client.state["pending"] is None

    duplicate = client.resend(sent)
    assert duplicate.duplicate is True
    assert client.state["pending"] is None  # 必须来自 public_state，而不是缓存快照


# ---------------------------------------------------------------------------
# 6. 开窗前提、事件构造、request_id
# ---------------------------------------------------------------------------


def test_open_confirm_window_without_pending_raises():
    _, client = make_client()
    with pytest.raises(NoPendingToConfirm):
        client.open_confirm_window()


def test_request_ids_are_unique_and_sequential():
    _, client = make_client()
    first = client.propose(parse("大于五吗"))
    second = client.propose(parse("小于八吗"))
    assert first.request_id == "A-0001"
    assert second.request_id == "A-0002"


def test_timestamp_present_by_default_and_stable_on_retry():
    _, client = make_client(clock=lambda: 1234.5)
    sent = client.propose(parse("大于五吗"))
    assert sent.event["timestamp"] == 1234.5

    retry = client.resend(sent)
    assert retry.event["timestamp"] == 1234.5


def test_timestamp_can_be_disabled():
    _, client = make_client(include_timestamp=False)
    sent = client.propose(parse("大于五吗"))
    assert "timestamp" not in sent.event


def test_build_event_requires_ids():
    with pytest.raises(ValueError):
        build_event(game_id="", request_id="r1", event_type="propose", payload={})
    with pytest.raises(ValueError):
        build_event(game_id="g1", request_id="", event_type="propose", payload={})


# ---------------------------------------------------------------------------
# 7. 结束类事件
# ---------------------------------------------------------------------------


def test_submit_reveals_number_only_after_confirm():
    _, client = make_client(secret=6)
    client.propose(parse("我确定是七"))
    window = client.open_confirm_window()
    assert "revealed_number" not in client.state  # 确认前不公开

    sent = client.confirm(window)
    assert sent.ok
    state = client.state
    assert state["finished"] is True
    assert state["revealed_number"] == 6
    assert state["result"] == "lose"             # 猜 7，实际 6


def test_exit_finishes_without_revealing():
    _, client = make_client(secret=6)
    client.propose(parse("退出"))
    window = client.open_confirm_window()
    assert client.confirm(window).ok

    state = client.state
    assert state["finished"] is True
    assert state["result"] == "exit"
    assert "revealed_number" not in state
