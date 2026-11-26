"""有限句式的中文意图解析器（A 模块阶段一）。

设计原则
--------
1. 只接受确定的句式，其余一律拒绝并给出原因码——**不猜**。
   项目方案要求「对于无法确定意图的输入，应拒绝或请求用户重新表达」。
2. 纯标准库，无 ROS 依赖，可在 Windows 独立运行与测试。
3. 不做任何计次、状态或胜负判断（A 模块红线）。

支持的表达见 README「支持表达清单」。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .intents import (
    Intent,
    Operator,
    ParseResult,
    RejectReason,
    accepted,
    rejected,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MIN_NUMBER = 1
MAX_NUMBER = 10
MAX_TEXT_LENGTH = 60  # 超过即视为非本游戏语句（防止超长噪声）

# 语气词：出现在句尾时剥离，不参与句式匹配
_TRAILING_PARTICLES = "吗呢啊呀吧么嘛"

# 口语填充词：出现在句首时剥离
_LEADING_FILLERS = ("那么", "请问", "那个", "麻烦", "嗯", "呃", "啊", "哦", "那")

# 复合句连接词：出现即判为复合问题
_COMPOUND_WORDS = ("而且", "并且", "还有", "同时", "然后", "以及", "另外", "再问", "接着问")

# 规则外比较：规则只允许严格大于/小于/等于
_UNSUPPORTED_WORDS = ("大于等于", "小于等于", "不等于", "大于或等于", "小于或等于", "不小于", "不大于")

# 疑问语气词：出现在句末时，会把陈述句变成疑问句，不能一律当作噪声剥掉
# （「确认吗」不是「确认」，「我确定是七吗」也不是最终提交）
_QUESTION_PARTICLES = ("吗", "么")

# 疑问标点：与语气词同等对待。「确认？」同样不是确认。
# NFKC 会把全角「？」转成半角「?」，所以只需判断半角。
_QUESTION_MARKS = "?"

# 数字相关的危险写法：负数、小数、被空格分开的数字。
# 这些符号如果被清洗掉，会把「大于-5」「是1.0」「是1 0」静默变成合法输入，
# 因此在归一化之前先判定并拒绝。
_NUMERIC_CHARS = r"0-9零〇一二两三四五六七八九十百"
_SIGN_CHARS = r"\-+−‐﹣"
_UNSAFE_NUMBER_PATTERNS = (
    # 符号紧邻数字：-5、+3、五-
    re.compile(rf"[{_SIGN_CHARS}]\s*[{_NUMERIC_CHARS}]"),
    re.compile(rf"[{_NUMERIC_CHARS}]\s*[{_SIGN_CHARS}]"),
    # 小数点：1.0、五.五，以及缺整数部分的 .5
    re.compile(rf"[{_NUMERIC_CHARS}]\s*[.．]\s*[{_NUMERIC_CHARS}]"),
    re.compile(rf"[.．]\s*[{_NUMERIC_CHARS}]"),
    # 数字之间夹分隔符：1,0 / 1。0 / 1、0
    re.compile(rf"[{_NUMERIC_CHARS}]\s*[，,、;；。]\s*[{_NUMERIC_CHARS}]"),
    # 阿拉伯数字之间夹空白：1 0
    re.compile(r"\d\s+\d"),
)

# 中文数字
_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100}
_CN_NUMBER_RE = re.compile(r"[零〇一二两三四五六七八九十百]+")
_ARABIC_NUMBER_RE = re.compile(r"\d+")

# 句式模板：数字统一替换成 #，其余必须逐字匹配
_GT_TEMPLATES = frozenset({"大于#", "比#大", "超过#", "高于#", "大过#"})
_LT_TEMPLATES = frozenset({"小于#", "比#小", "低于#", "少于#", "小过#"})
_EQ_TEMPLATES = frozenset({"是#", "等于#", "就是#", "是数字#"})
_FINAL_TEMPLATES = frozenset(
    {
        "我确定是#",
        "确定是#",
        "我确定#",
        "最终答案是#",
        "最终答案#",
        "最终提交#",
        "提交答案是#",
        "答案是#",
        "我的答案是#",
        "我提交#",
        "我猜是#",
        "我选#",
    }
)

# 控制类词表：必须整句完全一致
_CONFIRM_WORDS = frozenset({"确认", "确定", "我确认", "我确定", "确认无误", "可以确认", "确认一下", "就这样"})
_CANCEL_WORDS = frozenset({"取消", "取消问题", "取消这次", "算了", "不要了", "撤销", "不提了"})
_EXIT_WORDS = frozenset({"退出", "退出游戏", "结束游戏", "不玩了", "我要退出", "结束"})
_PAUSE_WORDS = frozenset({"暂停", "暂停游戏", "暂停一下", "先停一下", "等一下", "等一等", "停一下"})
_RESUME_WORDS = frozenset({"继续", "继续游戏", "接着来", "接着说", "恢复", "继续提问"})
_AFFIRM_WORDS = frozenset(
    {"是", "是的", "对", "对的", "嗯", "好", "好的", "可以", "行", "没错", "正确", "没有问题"}
)
_DENY_WORDS = frozenset({"不是", "不对", "不", "否", "没有", "不好", "不确认", "否认"})

# 整句匹配顺序即优先级；同一句话只会命中一张表（词表本身互不重叠）
_CONTROL_TABLE = (
    (Intent.CONFIRM, _CONFIRM_WORDS),
    (Intent.CANCEL, _CANCEL_WORDS),
    (Intent.EXIT, _EXIT_WORDS),
    (Intent.PAUSE, _PAUSE_WORDS),
    (Intent.RESUME, _RESUME_WORDS),
    (Intent.AFFIRM, _AFFIRM_WORDS),
    (Intent.DENY, _DENY_WORDS),
)


# ---------------------------------------------------------------------------
# 归一化与数字抽取
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberToken:
    """文本中的一个数字及其位置。"""

    start: int
    end: int
    value: int
    raw: str


def _nfkc(text: str) -> str:
    """全角转半角（NFKC），不删任何字符。"""
    return unicodedata.normalize("NFKC", text)


def has_unsafe_number_format(text: str) -> bool:
    """检测会被清洗「洗掉」的数字写法：负数、小数、被空格分开的数字。

    必须在 normalize_text 之前调用——清洗会删除负号、小数点和空格，
    否则「大于-5吗」「是1.0吗」「是1 0吗」会被静默改写成合法输入。
    """
    if not isinstance(text, str):
        return False
    prepared = _nfkc(text)
    return any(pattern.search(prepared) for pattern in _UNSAFE_NUMBER_PATTERNS)


def has_question_particle(text: str) -> bool:
    """判断句末（忽略空白）是否带疑问标记：语气词「吗/么」或问号「？/?」。

    「确认吗」「确认？」和「确认」、「我确定是七？」和「我确定是七」
    是两类话。归一化会剥掉语气词和标点，之后就无法区分，所以要在解析前单独记录。
    """
    if not isinstance(text, str):
        return False
    prepared = _nfkc(text).strip()
    tail = re.sub(r"[\s\W_]+$", "", prepared, flags=re.UNICODE)
    suffix = prepared[len(tail):]
    if any(mark in suffix for mark in _QUESTION_MARKS):
        return True
    return tail.endswith(_QUESTION_PARTICLES)


def normalize_text(text: str) -> str:
    """归一化：全角转半角、去空白与标点、剥离开头填充词和句尾语气词。

    只做与语义无关的清洗，不改动任何实词。
    注意：本函数会剥掉句末的「吗」，因此**不能**用它判断是否为疑问句，
    需要该信息时先调用 has_question_particle()。
    """
    if not isinstance(text, str):
        raise TypeError("normalize_text 只接受 str")
    result = _nfkc(text)
    result = re.sub(r"\s+", "", result)
    result = re.sub(r"[^\w\u4e00-\u9fff]", "", result)  # 去标点符号
    # 首尾各剥离最多 3 轮（例如「请问大于五吗」需要先剥「吗」再剥「请问」）
    for _ in range(3):
        before = result
        for filler in _LEADING_FILLERS:
            if result.startswith(filler) and len(result) > len(filler):
                result = result[len(filler):]
                break
        while result and result[-1] in _TRAILING_PARTICLES and len(result) > 1:
            result = result[:-1]
        if result == before:
            break
    return result


def _cn_number_to_int(text: str) -> Optional[int]:
    """把中文数字串转成整数，无法识别返回 None。

    支持：一~九、十、十一~十九、二十~九十九、一百。不追求通用中文数字文法。
    """
    if not text:
        return None
    total = 0
    rest = text

    if "百" in rest:
        head, _, rest = rest.partition("百")
        hundreds = _single_digit_sum(head) if head else 1
        if hundreds is None:
            return None
        total += hundreds * 100

    if "十" in rest:
        head, _, rest = rest.partition("十")
        tens = _single_digit_sum(head) if head else 1
        if tens is None:
            return None
        total += tens * 10

    if rest:
        ones = _single_digit_sum(rest)
        if ones is None:
            return None
        total += ones

    return total


def _single_digit_sum(text: str) -> Optional[int]:
    """连续单字数字求和（「二三」这类非规范写法不视为合法，返回 None）。"""
    if len(text) != 1:
        return None
    return _CN_DIGITS.get(text)


def extract_numbers(text: str) -> List[NumberToken]:
    """按出现顺序抽取阿拉伯数字与中文数字。"""
    tokens: List[NumberToken] = []

    for match in _ARABIC_NUMBER_RE.finditer(text):
        tokens.append(NumberToken(match.start(), match.end(), int(match.group()), match.group()))

    for match in _CN_NUMBER_RE.finditer(text):
        value = _cn_number_to_int(match.group())
        if value is None:
            continue
        tokens.append(NumberToken(match.start(), match.end(), value, match.group()))

    tokens.sort(key=lambda token: token.start)
    # 防御：理论上两类正则不会重叠，仍做一次去重保证位置唯一
    unique: List[NumberToken] = []
    for token in tokens:
        if unique and token.start < unique[-1].end:
            continue
        unique.append(token)
    return unique


def build_skeleton(text: str, tokens: List[NumberToken]) -> Tuple[str, List[int]]:
    """把数字替换成 #，返回句式骨架与数字值列表。"""
    pieces: List[str] = []
    values: List[int] = []
    cursor = 0
    for token in tokens:
        pieces.append(text[cursor:token.start])
        pieces.append("#")
        values.append(token.value)
        cursor = token.end
    pieces.append(text[cursor:])
    return "".join(pieces), values


# ---------------------------------------------------------------------------
# 主解析入口
# ---------------------------------------------------------------------------


def parse(text: object) -> ParseResult:
    """把一句中文解析成统一意图结构。

    参数可以是任意对象；非字符串一律返回 FORMAT_ERROR，不抛异常，
    这样 ROS 回调里可以直接调用而不需要额外 try/except。
    """
    if not isinstance(text, str):
        return rejected(repr(text), RejectReason.FORMAT_ERROR)

    raw = text
    if len(raw) > MAX_TEXT_LENGTH:
        return rejected(raw, RejectReason.TOO_LONG)

    # 1) 会被清洗洗掉的数字写法（负号、小数点、数字间空格）先拒绝
    if has_unsafe_number_format(raw):
        return rejected(raw, RejectReason.INVALID_NUMBER_FORMAT)

    is_question = has_question_particle(raw)

    normalized = normalize_text(raw)
    if not normalized:
        return rejected(raw, RejectReason.EMPTY, normalized)

    # 2) 复合问题优先判定：「大于五而且小于八吗」
    for word in _COMPOUND_WORDS:
        if word in normalized:
            return rejected(raw, RejectReason.COMPOUND, normalized)

    # 3) 规则外的比较方式：「大于等于五」「不小于五」「不等于五」
    for word in _UNSUPPORTED_WORDS:
        if word in normalized:
            return rejected(raw, RejectReason.UNSUPPORTED_OPERATOR, normalized)

    # 4) 控制类整句匹配（必须先于数字抽取：「等一下」「先停一下」里含中文数字）
    control_intent = _lookup_control_word(normalized)
    if control_intent is not None:
        if is_question:
            # 「确认吗」「是吗」是提问，不是执行确认；交给上层要求重新表达
            return rejected(raw, RejectReason.UNEXPECTED_QUESTION, normalized)
        return accepted(control_intent, raw, normalized)

    tokens = extract_numbers(normalized)

    if len(tokens) >= 2:
        # 用逗号/顿号分隔的两个分句也属于复合提问
        if re.search(r"[，,、;；]", raw):
            return rejected(raw, RejectReason.COMPOUND, normalized)
        return rejected(raw, RejectReason.MULTIPLE_NUMBERS, normalized)

    # 5) 否定歧义：「是不是七」「不是七吗」——不猜，要求重新表达
    if "是不是" in normalized or ("不是" in normalized and tokens):
        return rejected(raw, RejectReason.NEGATION_AMBIGUOUS, normalized)

    if len(tokens) == 1:
        skeleton, values = build_skeleton(normalized, tokens)
        value = values[0]
        intent, operator = _match_question_template(skeleton)
        if intent is None:
            return rejected(raw, RejectReason.NO_INTENT, normalized)
        if intent is Intent.FINAL and is_question:
            # 「我确定是七吗」是在问要不要提交，不是提交本身
            return rejected(raw, RejectReason.UNEXPECTED_QUESTION, normalized)
        if not MIN_NUMBER <= value <= MAX_NUMBER:
            return rejected(raw, RejectReason.OUT_OF_RANGE, normalized)
        return accepted(intent, raw, normalized, operator=operator, value=value)

    # 6) 既无数字也无控制词
    return rejected(raw, RejectReason.NO_INTENT, normalized)


def _match_question_template(skeleton: str) -> Tuple[Optional[Intent], Optional[Operator]]:
    if skeleton in _GT_TEMPLATES:
        return Intent.ASK, Operator.GT
    if skeleton in _LT_TEMPLATES:
        return Intent.ASK, Operator.LT
    if skeleton in _EQ_TEMPLATES:
        return Intent.ASK, Operator.EQ
    if skeleton in _FINAL_TEMPLATES:
        return Intent.FINAL, None
    return None, None


def _lookup_control_word(normalized: str) -> Optional[Intent]:
    """整句匹配控制类词表，命中返回意图，否则返回 None。"""
    for intent, words in _CONTROL_TABLE:
        if normalized in words:
            return intent
    return None
