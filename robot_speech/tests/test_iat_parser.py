"""iat_parser 的自动化测试。

⚠️ 全部测试数据都是**模拟数据**，带 `_simulated: true` 标记。
这些测试只能证明「按当前假设实现的拼接逻辑自洽」，
**不能**证明 IAT 已经在实机上打通。真实样本到手后需要重新核对组装规则。
"""

from __future__ import annotations

import json
import os

import pytest

from robot_speech import IatAssembler, IatError, SIMULATED_DATA_NOTICE, build_simulated_payload, parse_segment

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "simulated_iat_events.jsonl")


def _payload(words, is_final=False):
    return build_simulated_payload(words, is_final)


# ---------------------------------------------------------------------------
# parse_segment：单条事件的解析与容错
# ---------------------------------------------------------------------------


def test_parse_segment_from_dict():
    segment = parse_segment({"text": {"ls": False, "ws": [{"cw": [{"w": "你"}]}, {"cw": [{"w": "好"}]}]}})
    assert segment.text == "你好"
    assert segment.is_final is False


def test_parse_segment_from_json_string():
    payload = json.dumps({"text": {"ls": True, "ws": [{"cw": [{"w": "是"}]}, {"cw": [{"w": "七"}]}]}})
    segment = parse_segment(payload)
    assert segment.text == "是七"
    assert segment.is_final is True


def test_parse_segment_from_bytes():
    payload = json.dumps({"text": {"ls": False, "ws": [{"cw": [{"w": "五"}]}]}}).encode("utf-8")
    segment = parse_segment(payload)
    assert segment.text == "五"


def test_parse_segment_uses_first_candidate_only():
    """`cw` 是同一位置的 n-best 候选，不是续写；参考实现只取 cw[0]。"""
    segment = parse_segment({"text": {"ls": False, "ws": [{"cw": [{"w": "五"}, {"w": "呜"}]}]}})
    assert segment.text == "五"


def test_parse_segment_ls_accepts_string_flags():
    segment = parse_segment({"text": {"ls": "true", "ws": [{"cw": [{"w": "七"}]}]}})
    assert segment.is_final is True


def test_parse_segment_missing_ls_defaults_to_partial():
    segment = parse_segment({"text": {"ws": [{"cw": [{"w": "七"}]}]}})
    assert segment.is_final is False


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"text": "不是对象"}, "MISSING_TEXT"),
        ({}, "MISSING_TEXT"),
        ({"text": {}}, "MISSING_WS"),
        ({"text": {"ws": "不是列表"}}, "MISSING_WS"),
        ({"text": {"ws": ["不是对象"]}}, "BAD_WORD_ITEM"),
        ({"text": {"ws": [{}]}}, "BAD_WORD_ITEM"),
        ({"text": {"ws": [{"cw": []}]}}, "BAD_WORD_ITEM"),
        ({"text": {"ws": [{"cw": ["不是对象"]}]}}, "BAD_WORD_ITEM"),
        ({"text": {"ws": [{"cw": [{"w": 7}]}]}}, "BAD_WORD"),
        ({"text": {"ls": "或许", "ws": [{"cw": [{"w": "七"}]}]}}, "BAD_FLAG"),
        ("", "EMPTY_PAYLOAD"),
        ("   ", "EMPTY_PAYLOAD"),
        ("{不是合法json", "JSON_ERROR"),
        (123, "FORMAT_ERROR"),
        (b"\xff\xfe", "DECODE_ERROR"),
    ],
)
def test_parse_segment_rejects_bad_payload(payload, reason):
    with pytest.raises(IatError) as excinfo:
        parse_segment(payload)
    assert excinfo.value.reason == reason


# ---------------------------------------------------------------------------
# IatAssembler：拼接、去重、修订、结束
# ---------------------------------------------------------------------------


def test_assembler_cumulative_updates():
    assembler = IatAssembler()
    first = assembler.push(_payload(["大于"]))
    assert (first.text, first.delta, first.is_final) == ("大于", "大于", False)

    second = assembler.push(_payload(["大于", "五"]))
    assert (second.text, second.delta) == ("大于五", "五")
    assert second.is_final is False


def test_assembler_duplicate_payload():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五"]))
    update = assembler.push(_payload(["大于", "五"]))
    assert update.is_duplicate is True
    assert update.delta == ""
    assert update.text == "大于五"


def test_assembler_stale_shorter_payload_is_ignored():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五", "吗"]))
    update = assembler.push(_payload(["大于"]))
    assert update.is_duplicate is True
    assert update.text == "大于五吗"


def test_assembler_revision_replaces_text():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五"]))
    update = assembler.push(_payload(["小于", "五"]))
    assert update.revision is True
    assert update.text == "小于五"
    assert update.delta == "小于五"


def test_assembler_final_flag():
    assembler = IatAssembler()
    assembler.push(_payload(["是"]))
    update = assembler.push(_payload(["是", "七"], is_final=True))
    assert update.is_final is True
    assert update.text == "是七"
    assert assembler.text == "是七"
    assert assembler.is_final is True


def test_assembler_empty_words_do_not_clear_text():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五"]))
    update = assembler.push(_payload([], is_final=False))
    assert update.text == "大于五"
    assert update.is_duplicate is True


def test_assembler_auto_reset_after_final():
    assembler = IatAssembler()
    assembler.push(_payload(["是", "七"], is_final=True))
    update = assembler.push(_payload(["继续"]))
    assert update.text == "继续"
    assert update.is_final is False
    assert assembler.auto_reset_last is True


def test_assembler_explicit_reset():
    assembler = IatAssembler()
    assembler.push(_payload(["是", "七"], is_final=True))
    assembler.reset()
    assert assembler.text == ""
    assert assembler.is_final is False
    update = assembler.push(_payload(["小于"]))
    assert update.text == "小于"


def test_assembler_event_index_increments():
    assembler = IatAssembler()
    assert assembler.push(_payload(["一"])).event_index == 1
    assert assembler.push(_payload(["一", "二"])).event_index == 2
    assembler.reset()
    assert assembler.push(_payload(["三"])).event_index == 3


# ---------------------------------------------------------------------------
# 模拟数据标记：防止把模拟结果当成实机验证
# ---------------------------------------------------------------------------

def test_build_simulated_payload_is_marked():
    payload = build_simulated_payload(["大于", "五"], is_final=False)
    assert payload["_simulated"] is True
    assert payload["_note"]
    assert SIMULATED_DATA_NOTICE


def test_fixture_events_are_marked_simulated():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    assert lines, "fixture 不能为空"
    for line in lines:
        data = json.loads(line)
        assert data["_simulated"] is True


def test_fixture_replay_end_to_end():
    """回放 fixture，验证两句话都被正确拼出并结束。"""
    assembler = IatAssembler()
    finals = []
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            update = assembler.push(line.strip())
            if update.is_final:
                finals.append(update.text)
                assembler.reset()
    assert finals == ["大于五吗", "是七"]


# ---------------------------------------------------------------------------
# 回归 1：句子边界取决于「累积式 / 增量式」，必须显式选择
#    曾出现：事件只带新增片段时，「大于」+「五吗」拼成「五吗」。
# ---------------------------------------------------------------------------


def test_delta_mode_appends_fragments():
    assembler = IatAssembler(mode="delta")
    first = assembler.push(_payload(["大于"]))
    assert (first.text, first.delta) == ("大于", "大于")

    second = assembler.push(_payload(["五吗"]))
    assert second.text == "大于五吗"
    assert second.delta == "五吗"
    assert second.revision is False


def test_delta_mode_duplicate_fragment_is_ignored():
    assembler = IatAssembler(mode="delta")
    assembler.push(_payload(["大于"]))
    update = assembler.push(_payload(["大于"]))
    assert update.is_duplicate is True
    assert update.text == "大于"


def test_delta_mode_final():
    assembler = IatAssembler(mode="delta")
    assembler.push(_payload(["是"]))
    update = assembler.push(_payload(["七"], is_final=True))
    assert update.text == "是七"
    assert update.is_final is True


def test_cumulative_mode_keeps_prefix_semantics():
    """默认模式把「非前缀」当修订——这正是增量式事件会被吃掉的原因。"""
    assembler = IatAssembler()
    assembler.push(_payload(["大于"]))
    update = assembler.push(_payload(["五吗"]))
    assert update.revision is True
    assert update.text == "五吗"


def test_assembler_rejects_unknown_mode():
    with pytest.raises(ValueError):
        IatAssembler(mode="guess")


# ---------------------------------------------------------------------------
# 回归 2：同一个最终事件连推两次，只能产生一次最终结果
# ---------------------------------------------------------------------------


def test_duplicate_final_event_is_deduplicated():
    assembler = IatAssembler()
    assembler.push(_payload(["是"]))
    first = assembler.push(_payload(["是", "七"], is_final=True))
    assert first.is_final is True

    second = assembler.push(_payload(["是", "七"], is_final=True))
    assert second.is_final is False
    assert second.is_duplicate is True
    assert second.text == "是七"


def test_duplicate_final_in_delta_mode_is_deduplicated():
    assembler = IatAssembler(mode="delta")
    assembler.push(_payload(["大于五吗"], is_final=True))
    update = assembler.push(_payload(["大于五吗"], is_final=True))
    assert update.is_final is False
    assert update.is_duplicate is True


def test_identical_sentence_after_intervening_event_is_accepted():
    """玩家连着说两遍同一句话时，中间会有新事件，不能被当成重复丢掉。"""
    assembler = IatAssembler()
    assembler.push(_payload(["大于五吗"], is_final=True))
    assembler.push(_payload(["大"]))                     # 新一句开始
    update = assembler.push(_payload(["大于五吗"], is_final=True))
    assert update.is_final is True
    assert update.text == "大于五吗"


# ---------------------------------------------------------------------------
# 回归 3：末尾补发的 ls=True 可能不带新词，但它必须结束这句话
#    曾出现：最终事件 ws 为空（或与上一条相同）时返回 is_final=False，
#    上层永远等不到收尾，整句话被下一句的 auto_reset 吞掉。
# ---------------------------------------------------------------------------


def test_final_packet_without_new_words_closes_the_utterance():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五"]))
    assert assembler.text == "大于五"

    update = assembler.push(_payload([], is_final=True))   # 尾包不带词

    assert update.is_final is True          # 这句话结束了
    assert update.is_duplicate is False     # 不能标记成「可忽略」
    assert update.text == "大于五"           # 文本保留
    assert update.delta == ""


def test_final_packet_repeating_the_same_text_closes_the_utterance():
    assembler = IatAssembler()
    assembler.push(_payload(["是", "七"]))
    update = assembler.push(_payload(["是", "七"], is_final=True))
    assert update.is_final is True
    assert update.text == "是七"


def test_repeated_closing_final_does_not_fire_twice():
    assembler = IatAssembler()
    assembler.push(_payload(["大于", "五"]))
    first = assembler.push(_payload([], is_final=True))
    assert first.is_final is True

    second = assembler.push(_payload([], is_final=True))
    assert second.is_final is False
    assert second.is_duplicate is True


def test_empty_final_without_any_words_is_not_emitted():
    """没有任何识别内容时，空 final 不对外交付，避免上层当成一句话处理。"""
    assembler = IatAssembler()
    update = assembler.push(_payload([], is_final=True))
    assert update.is_final is False
    assert update.text == ""


def test_closing_final_works_in_delta_mode():
    assembler = IatAssembler(mode="delta")
    assembler.push(_payload(["大于"]))
    update = assembler.push(_payload([], is_final=True))
    assert update.is_final is True
    assert update.text == "大于"
