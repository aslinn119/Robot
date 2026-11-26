# ============================================================================
# 【已废弃 · v0.2】本模块依据的 A↔C 接口是 v0.2 的**进程内直接调用**，
# TEAM_INTERFACE v1.0（2026-11-26）发布后已被取代。
# 现行入口 scripts/speech_agent.py 使用 command_agent + http_client + team_protocol，
# **不再导入本模块**。保留它是为了对照历史设计，新代码不要使用。
# 现行协议见仓库根目录 TEAM_INTERFACE.md。
# ============================================================================
"""A → C 的事件构造，对齐 `docs/interface_v02.md`。

本模块只做「解析结果 → 事件字典」的纯函数转换，**不保存任何会话状态**。
request_id 生成、待确认绑定、重试缓存都在 `referee_client.py`。

v0.2 的几条铁律（本模块据此设计）：

- `propose` 只产生提议，**确认后才生效**；
- `confirm` / `cancel` 的 payload **恰好**是 `pending_id` + `version`，
  且必须取自对应待确认内容；
- 同一 `game_id + request_id + 完全相同内容` 重发返回缓存响应（`duplicate=true`），
  改变内容则 `request_conflict`；
- 旧局消息 `stale_game`。

**未冻结**：`timestamp` 在 `interfaces.md` 的公共字段里，但 v0.2 的请求示例没有它。
本模块默认带、可关，且**重试必须复用同一个事件 dict**，否则时间戳变化会被 C 判为
「相同编号改变内容」。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from .intents import Intent, Operator, ParseResult

# ---------------------------------------------------------------------------
# 事件类型与 payload kind（v0.2 已定义）
# ---------------------------------------------------------------------------

EVENT_PROPOSE = "propose"
EVENT_CONFIRM = "confirm"
EVENT_CANCEL = "cancel"
EVENT_NEW_GAME = "new_game"

KIND_GT = "gt"
KIND_LT = "lt"
KIND_EQ = "eq"
KIND_SUBMIT = "submit"
KIND_EXIT = "exit"

#: v0.3 玩家藏牌才用得到；机器人藏牌阶段 A 不发送
KIND_REGISTER = "register"
KIND_YES = "yes"
KIND_NO = "no"
KIND_REVEAL = "reveal"

PROPOSABLE_KINDS = (KIND_GT, KIND_LT, KIND_EQ, KIND_SUBMIT, KIND_EXIT)

_OPERATOR_TO_KIND = {
    Operator.GT: KIND_GT,
    Operator.LT: KIND_LT,
    Operator.EQ: KIND_EQ,
}


class Action(str, Enum):
    """上层拿到一条解析结果后应该做什么。"""

    PROPOSE = "propose"    # 发给 C 的 propose
    CONFIRM = "confirm"    # 复用已绑定的确认窗口发 confirm
    CANCEL = "cancel"      # 复用已绑定的确认窗口发 cancel
    LOCAL = "local"        # 本地处理，C 没有对应状态转换（暂停/继续）
    REJECT = "reject"      # 拒绝，要求用户重新表达


class UnmappableIntent(ValueError):
    """该解析结果不能用于本次操作（例如把「暂停」当成 propose 发出去）。"""


def propose_payload(result: ParseResult) -> Dict[str, Any]:
    """把 ASK / FINAL / EXIT 解析结果转成 C 的 propose payload。

    其余意图（确认、取消、暂停……）不是 propose，抛 UnmappableIntent。
    """
    if result.intent is Intent.ASK:
        if result.operator is None or result.value is None:
            raise UnmappableIntent(f"ASK 缺少 operator/value: {result}")
        return {"kind": _OPERATOR_TO_KIND[result.operator], "number": result.value}

    if result.intent is Intent.FINAL:
        if result.value is None:
            raise UnmappableIntent(f"FINAL 缺少 value: {result}")
        return {"kind": KIND_SUBMIT, "number": result.value}

    if result.intent is Intent.EXIT:
        return {"kind": KIND_EXIT, "number": None}

    raise UnmappableIntent(f"{result.intent.value} 不是 propose 事件")


def confirm_payload(pending_id: str, version: int) -> Dict[str, Any]:
    """confirm / cancel 共用：payload 恰为 pending_id + version。"""
    if not pending_id:
        raise ValueError("pending_id 不能为空")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError(f"version 必须是 int，收到 {version!r}")
    return {"pending_id": pending_id, "version": version}


def action_for(result: ParseResult, *, confirm_window_open: bool = False) -> Action:
    """判断一条解析结果该走哪条路径。

    `AFFIRM` / `DENY` 的含义取决于当前环节（见 docs/player_hides_v03.md）：
    只有在确认窗口打开时才能解释成 confirm / cancel；否则拒绝，
    不能替游戏阶段猜。
    """
    if not result.accepted:
        return Action.REJECT

    if result.intent in (Intent.ASK, Intent.FINAL, Intent.EXIT):
        return Action.PROPOSE
    if result.intent is Intent.CONFIRM:
        return Action.CONFIRM
    if result.intent is Intent.CANCEL:
        return Action.CANCEL
    if result.intent in (Intent.PAUSE, Intent.RESUME):
        return Action.LOCAL
    if result.intent is Intent.AFFIRM:
        return Action.CONFIRM if confirm_window_open else Action.REJECT
    if result.intent is Intent.DENY:
        return Action.CANCEL if confirm_window_open else Action.REJECT
    return Action.REJECT


def build_event(
    *,
    game_id: str,
    request_id: str,
    event_type: str,
    payload: Dict[str, Any],
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """构造一条 A → C 事件。

    `timestamp` 为 None 时不写入该字段（v0.2 未要求，等接口冻结再定）。
    """
    if not game_id:
        raise ValueError("game_id 不能为空")
    if not request_id:
        raise ValueError("request_id 不能为空")
    event: Dict[str, Any] = {
        "game_id": game_id,
        "request_id": request_id,
        "event_type": event_type,
        "payload": payload,
    }
    if timestamp is not None:
        event["timestamp"] = timestamp
    return event


__all__ = [
    "Action",
    "EVENT_CANCEL",
    "EVENT_CONFIRM",
    "EVENT_NEW_GAME",
    "EVENT_PROPOSE",
    "KIND_EQ",
    "KIND_EXIT",
    "KIND_GT",
    "KIND_LT",
    "KIND_NO",
    "KIND_REGISTER",
    "KIND_REVEAL",
    "KIND_SUBMIT",
    "KIND_YES",
    "PROPOSABLE_KINDS",
    "UnmappableIntent",
    "action_for",
    "build_event",
    "confirm_payload",
    "propose_payload",
]
