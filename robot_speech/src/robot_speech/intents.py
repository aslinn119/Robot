"""A 模块对外统一意图结构。

设计约束（来自项目方案与接口草案）：
- 纯 Python，不依赖 ROS，可在 Windows 上独立运行与测试。
- 字段名对齐小组接口草案：intent / operator / value / confidence / raw_text。
- 解析器只描述「用户说了什么」，不修改计次、历史与胜负（A 模块红线）。

注意：AFFIRM / DENY（是 / 不是）只表达词面含义，最终被解释成「确认」「游戏回答」
还是「取消」，取决于当前游戏阶段，由适配层结合裁判返回的 phase 决定。
参见 docs/player_hides_v03.md「「是」要根据当前环节解释」。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    """解析器输出的意图类别。UNKNOWN 表示拒绝，不代表猜测结果。"""

    ASK = "ASK"          # 普通提问：大于 / 小于 / 是
    FINAL = "FINAL"      # 最终提交
    CONFIRM = "CONFIRM"  # 明确的确认词（确认 / 确定）
    CANCEL = "CANCEL"    # 撤销尚未提交的内容
    AFFIRM = "AFFIRM"    # 肯定（是 / 对 / 嗯 / 好），含义随阶段变化
    DENY = "DENY"        # 否定（不是 / 不对），含义随阶段变化
    PAUSE = "PAUSE"      # 暂停
    RESUME = "RESUME"    # 继续
    EXIT = "EXIT"        # 主动退出本局（需二次确认，由裁判侧执行）
    UNKNOWN = "UNKNOWN"  # 拒绝解析


class Operator(str, Enum):
    """普通提问的比较方式，严格比较。"""

    GT = "GT"
    LT = "LT"
    EQ = "EQ"


class RejectReason(str, Enum):
    """拒绝原因码，便于上层统计和日志定位。"""

    EMPTY = "EMPTY"                          # 空输入或只有标点
    FORMAT_ERROR = "FORMAT_ERROR"            # 非字符串等非法类型
    TOO_LONG = "TOO_LONG"                    # 超出合理长度
    NO_INTENT = "NO_INTENT"                  # 无匹配句式
    OUT_OF_RANGE = "OUT_OF_RANGE"            # 数字不在 1~10
    COMPOUND = "COMPOUND"                    # 复合问题（两问合一）
    MULTIPLE_NUMBERS = "MULTIPLE_NUMBERS"    # 一句话里出现多个数字
    NEGATION_AMBIGUOUS = "NEGATION_AMBIGUOUS"  # 否定歧义，如「是不是七」
    UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"  # 大于等于 / 不等于等规则外比较
    INVALID_NUMBER_FORMAT = "INVALID_NUMBER_FORMAT"  # 负数、小数、被空格分开的数字
    UNEXPECTED_QUESTION = "UNEXPECTED_QUESTION"      # 该句式不应带疑问语气，如「确认吗」


@dataclass(frozen=True)
class ParseResult:
    """一次解析的完整结果。

    对外只暴露 to_dict() 的五个字段（已与小组协商）；其余字段供调试与统计使用。
    """

    intent: Intent
    operator: Optional[Operator] = None
    value: Optional[int] = None
    confidence: float = 0.0
    raw_text: str = ""
    normalized_text: str = ""
    reason: Optional[RejectReason] = None

    @property
    def accepted(self) -> bool:
        return self.intent is not Intent.UNKNOWN

    def to_dict(self) -> dict:
        """A → 游戏逻辑模块的统一结构。字段已冻结，勿随意增删。"""
        return {
            "intent": self.intent.value,
            "operator": self.operator.value if self.operator is not None else None,
            "value": self.value,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
        }

    def to_debug_dict(self) -> dict:
        """带归一化文本与拒绝原因的调试视图，只用于日志和 CLI 展示。"""
        data = self.to_dict()
        data["normalized_text"] = self.normalized_text
        data["accepted"] = self.accepted
        data["reason"] = self.reason.value if self.reason is not None else None
        return data

    def __str__(self) -> str:  # CLI 友好
        if not self.accepted:
            return f"REJECT({self.reason.value if self.reason else 'UNKNOWN'})"
        if self.intent is Intent.ASK:
            return f"ASK/{self.operator.value}({self.value})"
        if self.intent is Intent.FINAL:
            return f"FINAL({self.value})"
        return self.intent.value


def rejected(raw_text: str, reason: RejectReason, normalized_text: str = "") -> ParseResult:
    """构造一个拒绝结果，confidence 固定为 0.0。"""
    return ParseResult(
        intent=Intent.UNKNOWN,
        operator=None,
        value=None,
        confidence=0.0,
        raw_text=raw_text,
        normalized_text=normalized_text,
        reason=reason,
    )


def accepted(
    intent: Intent,
    raw_text: str,
    normalized_text: str,
    operator: Optional[Operator] = None,
    value: Optional[int] = None,
) -> ParseResult:
    """构造一个接受结果，confidence 固定为 1.0（仅精确句式匹配才接受）。"""
    return ParseResult(
        intent=intent,
        operator=operator,
        value=value,
        confidence=1.0,
        raw_text=raw_text,
        normalized_text=normalized_text,
        reason=None,
    )
