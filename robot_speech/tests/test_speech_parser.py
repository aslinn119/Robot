"""speech_parser 的自动化测试。

覆盖交接文档「任务 3」列的 10 类场景：
1 正常的大小比较问题 / 2 等于问题 / 3 最终答案确认 / 4 暂停与继续控制 /
5 1~10 数字边界 / 6 非法数字 / 7 复合问题 / 8 否定表达 / 9 多数字表达 /
10 模糊、空白及异常输入

另外覆盖控制类意图、归一化行为与对外接口结构。
所有断言基于真实运行结果，未使用模拟数据（本解析器本来就是纯文本输入）。
"""

from __future__ import annotations

import pytest

from robot_speech import (
    MAX_NUMBER,
    MIN_NUMBER,
    Intent,
    Operator,
    RejectReason,
    extract_numbers,
    has_question_particle,
    has_unsafe_number_format,
    normalize_text,
    parse,
)

# ---------------------------------------------------------------------------
# 1. 正常的大小比较问题
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, operator, value",
    [
        ("大于五吗", Operator.GT, 5),
        ("小于八吗", Operator.LT, 8),
        ("大于5吗", Operator.GT, 5),
        ("小于8吗", Operator.LT, 8),
        ("大于五", Operator.GT, 5),          # 不带语气词
        (" 大于 五 吗 ", Operator.GT, 5),    # 带空格
        ("大于５吗", Operator.GT, 5),        # 全角数字
        ("大于五?", Operator.GT, 5),         # 带英文问号
        ("请问大于五吗", Operator.GT, 5),    # 带口语填充词
        ("比五大吗", Operator.GT, 5),
        ("比五小吗", Operator.LT, 5),
        ("超过七吗", Operator.GT, 7),
        ("低于三吗", Operator.LT, 3),
        ("高于二吗", Operator.GT, 2),
        ("少于四吗", Operator.LT, 4),
    ],
)
def test_ask_comparison(text, operator, value):
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert result.intent is Intent.ASK
    assert result.operator is operator
    assert result.value == value
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# 2. 等于问题
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value",
    [
        ("是七吗", 7),
        ("是七", 7),
        ("等于九吗", 9),
        ("就是三吗", 3),
        ("那是七吗", 7),        # 句首「那」作为填充词
    ],
)
def test_ask_equal(text, value):
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert result.intent is Intent.ASK
    assert result.operator is Operator.EQ
    assert result.value == value


# ---------------------------------------------------------------------------
# 3. 最终答案确认
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value",
    [
        ("我确定是七", 7),
        ("确定是七", 7),
        ("我确定七", 7),
        ("最终答案是十", 10),
        ("最终提交五", 5),
        ("答案是三", 3),
        ("我的答案是八", 8),
        ("我猜是九", 9),
    ],
)
def test_final_submit(text, value):
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert result.intent is Intent.FINAL
    assert result.operator is None
    assert result.value == value


# ---------------------------------------------------------------------------
# 4. 暂停与继续控制
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, intent",
    [
        ("暂停游戏", Intent.PAUSE),
        ("暂停", Intent.PAUSE),
        ("等一下", Intent.PAUSE),
        ("继续游戏", Intent.RESUME),
        ("继续", Intent.RESUME),
        ("接着说", Intent.RESUME),
        ("取消", Intent.CANCEL),
        ("算了", Intent.CANCEL),
        ("退出", Intent.EXIT),
        ("结束游戏", Intent.EXIT),
        ("确认", Intent.CONFIRM),
        ("确定", Intent.CONFIRM),
        ("是", Intent.AFFIRM),
        ("对", Intent.AFFIRM),
        ("好的", Intent.AFFIRM),
        ("不是", Intent.DENY),
        ("不对", Intent.DENY),
    ],
)
def test_control_intents(text, intent):
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert result.intent is intent
    assert result.operator is None
    assert result.value is None


# ---------------------------------------------------------------------------
# 5. 1~10 数字边界
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", range(MIN_NUMBER, MAX_NUMBER + 1))
def test_number_boundaries_arabic(value):
    result = parse(f"大于{value}吗")
    assert result.accepted
    assert result.value == value


@pytest.mark.parametrize(
    "chinese, value",
    [("一", 1), ("二", 2), ("两", 2), ("三", 3), ("四", 4), ("五", 5),
     ("六", 6), ("七", 7), ("八", 8), ("九", 9), ("十", 10)],
)
def test_number_boundaries_chinese(chinese, value):
    result = parse(f"是{chinese}吗")
    assert result.accepted, f"是{chinese}吗 应被接受"
    assert result.value == value


# ---------------------------------------------------------------------------
# 6. 非法数字（越界 / 规则外写法）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "大于零吗",
        "大于0吗",
        "大于十一吗",
        "大于十五吗",
        "大于二十吗",
        "大于100吗",
        "大于一百吗",
        "是十二吗",
        "最终答案是十五",
    ],
)
def test_out_of_range(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.OUT_OF_RANGE


@pytest.mark.parametrize(
    "text",
    ["大于等于五吗", "小于等于五吗", "不等于五吗", "不小于五吗", "不大于五吗"],
)
def test_unsupported_operator(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.UNSUPPORTED_OPERATOR


# ---------------------------------------------------------------------------
# 7. 复合问题
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "大于五而且小于八吗",
        "大于五并且小于八吗",
        "大于五还有小于八吗",
        "大于五，小于八吗",
        "大于五、小于八吗",
    ],
)
def test_compound_question(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.COMPOUND


# ---------------------------------------------------------------------------
# 8. 否定表达
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["是不是七", "是不是七吗", "不是七吗", "不是五吗"])
def test_negation_ambiguous(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.NEGATION_AMBIGUOUS


# ---------------------------------------------------------------------------
# 9. 多数字表达
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["大于五小于八", "五和八", "是七还是八", "大于5小于8吗"],
)
def test_multiple_numbers(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.MULTIPLE_NUMBERS


# ---------------------------------------------------------------------------
# 10. 模糊、空白及异常输入
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\t\n", "。。。！", "?？。"],
)
def test_empty_input(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.EMPTY


@pytest.mark.parametrize("text", [None, 123, 3.14, [], {}, b"\xe5\xa4\xa7"])
def test_non_string_input(text):
    result = parse(text)
    assert not result.accepted
    assert result.reason is RejectReason.FORMAT_ERROR


@pytest.mark.parametrize(
    "text",
    ["今天天气不错", "五", "大于", "是", "帮我拿杯水", "鲁班鲁班"],
)
def test_no_intent(text):
    result = parse(text)
    # 「是」在控制词表里，属于 AFFIRM，不在此列
    if text == "是":
        assert result.intent is Intent.AFFIRM
        return
    assert not result.accepted
    assert result.reason is RejectReason.NO_INTENT


def test_too_long_input():
    result = parse("大" * 80)
    assert not result.accepted
    assert result.reason is RejectReason.TOO_LONG


# ---------------------------------------------------------------------------
# 归一化与数字抽取（内部行为，供后续适配层复用）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("大于五吗", "大于五"),
        (" 是 七 吗 ", "是七"),
        ("请问小于八吗", "小于八"),
        ("最终答案是十！", "最终答案是十"),
    ],
)
def test_normalize_text(text, expected):
    assert normalize_text(text) == expected


@pytest.mark.parametrize(
    "text, values",
    [
        ("大于五吗", [5]),
        ("大于5吗", [5]),
        ("大于十五吗", [15]),
        ("大于一百吗", [100]),
        ("大于零吗", [0]),
        ("大于五小于八", [5, 8]),
        ("没有数字", []),
    ],
)
def test_extract_numbers(text, values):
    assert [token.value for token in extract_numbers(text)] == values


# ---------------------------------------------------------------------------
# 对外接口结构与不变量
# ---------------------------------------------------------------------------


def test_to_dict_schema():
    result = parse("大于五吗")
    assert result.to_dict() == {
        "intent": "ASK",
        "operator": "GT",
        "value": 5,
        "confidence": 1.0,
        "raw_text": "大于五吗",
    }


def test_to_dict_schema_on_reject():
    result = parse("大于十五吗")
    assert result.to_dict() == {
        "intent": "UNKNOWN",
        "operator": None,
        "value": None,
        "confidence": 0.0,
        "raw_text": "大于十五吗",
    }
    assert result.to_debug_dict()["reason"] == "OUT_OF_RANGE"


@pytest.mark.parametrize(
    "text",
    ["大于五吗", "是七吗", "我确定是七", "暂停", "是", "不是", "确认", "大于十五吗", "随便说点什么"],
)
def test_invariants(text):
    result = parse(text)
    if result.accepted:
        assert result.confidence == 1.0
        assert result.reason is None
        if result.intent is Intent.ASK:
            assert result.operator in (Operator.GT, Operator.LT, Operator.EQ)
            assert MIN_NUMBER <= result.value <= MAX_NUMBER
        if result.intent is Intent.FINAL:
            assert result.operator is None
            assert MIN_NUMBER <= result.value <= MAX_NUMBER
    else:
        assert result.intent is Intent.UNKNOWN
        assert result.confidence == 0.0
        assert result.reason is not None
        assert result.operator is None
        assert result.value is None


def test_parse_never_raises_on_weird_input():
    """ROS 回调里会直接调用 parse，因此不能抛异常。"""
    for payload in (None, object(), b"bytes", ["list"], {"a": 1}, 1e999):
        parse(payload)  # 不抛即通过


# ---------------------------------------------------------------------------
# 11. 回归：归一化不能改变数字的写法
#    「大于-5吗」曾被解析成 大于5，「是1.0吗」「是1 0吗」曾被解析成 是10，
#    原因是清洗顺手删掉了负号、小数点和数字间空格。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "大于-5吗",
        "大于－５吗",       # 全角负号 + 全角数字
        "大于-五吗",        # 负号 + 中文数字
        "大于+5吗",
        "大于五-吗",        # 符号在数字之后
        "是1.0吗",
        "是1.5吗",
        "是五.五吗",
        "是1 0吗",          # 数字之间夹空格
        "大于 1 0 吗",
        "是.5吗",           # 缺整数部分的小数
        "是.五吗",
        "是1,0吗",          # 逗号夹在数字之间
        "是1。0吗",         # 中文句号夹在数字之间
        "是1、0吗",
    ],
)
def test_invalid_number_format(text):
    result = parse(text)
    assert not result.accepted, f"{text!r} 不应被接受，实际 {result}"
    assert result.reason is RejectReason.INVALID_NUMBER_FORMAT


def test_number_with_surrounding_space_is_still_ok():
    """数字整体两侧有空格是正常输入，不能被误杀。"""
    result = parse("大于 5 吗")
    assert result.accepted
    assert (result.operator, result.value) == (Operator.GT, 5)


@pytest.mark.parametrize(
    "text, operator, value",
    [
        ("大于五.", Operator.GT, 5),
        ("大于五。", Operator.GT, 5),
        ("大于五,", Operator.GT, 5),
        ("大于五！", Operator.GT, 5),
        ("是七。", Operator.EQ, 7),
    ],
)
def test_sentence_final_punctuation_is_tolerated(text, operator, value):
    """句末标点不是数字的一部分，正常放行（评审复核确认的行为）。"""
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert (result.operator, result.value) == (operator, value)


# ---------------------------------------------------------------------------
# 12. 回归：句末「吗」表达疑问，不能一律当噪声剥掉
#    「确认吗」曾被当成 CONFIRM，「我确定是七吗」曾被当成 FINAL。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "确认吗",
        "确认？",
        "确认?",
        "确定吗",
        "我确定是七吗",
        "我确定是七？",
        "确定是七吗",
        "是吗",
        "对的吗",
        "取消吗",
        "退出吗",
        "暂停吗",
        "继续吗",
    ],
)
def test_question_particle_on_non_ask(text):
    result = parse(text)
    assert not result.accepted, f"{text!r} 不应被接受，实际 {result}"
    assert result.reason is RejectReason.UNEXPECTED_QUESTION


@pytest.mark.parametrize(
    "text, intent",
    [
        ("确认", Intent.CONFIRM),
        ("我确定是七", Intent.FINAL),
        ("确定是七", Intent.FINAL),
        ("大于五吗", Intent.ASK),   # 提问句本来就应该带「吗」
        ("是七吗", Intent.ASK),
    ],
)
def test_question_particle_does_not_break_valid_inputs(text, intent):
    result = parse(text)
    assert result.accepted, f"{text!r} 应被接受，实际 {result}"
    assert result.intent is intent


def test_has_question_particle_helper():
    assert has_question_particle("确认吗") is True
    assert has_question_particle("确认吗？") is True
    assert has_question_particle("确认？") is True
    assert has_question_particle("确认?") is True
    assert has_question_particle("确认") is False
    assert has_question_particle("确认。") is False
    # 提问句本来就带问号；这里只记录事实，是否放行由 parse() 按意图决定
    assert has_question_particle("大于五？") is True
    assert has_question_particle("大于五") is False


def test_has_unsafe_number_format_helper():
    assert has_unsafe_number_format("大于-5吗") is True
    assert has_unsafe_number_format("是1.0吗") is True
    assert has_unsafe_number_format("是.5吗") is True
    assert has_unsafe_number_format("是1,0吗") is True
    assert has_unsafe_number_format("是1。0吗") is True
    assert has_unsafe_number_format("大于五吗") is False
    assert has_unsafe_number_format("大于 5 吗") is False
    # 句末句点不是数字的一部分
    assert has_unsafe_number_format("大于五.") is False
    assert has_unsafe_number_format("大于五。") is False
