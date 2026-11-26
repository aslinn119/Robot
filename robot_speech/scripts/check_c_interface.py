#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对 C 的 RefereeService 是否符合 `docs/interface_v02.md` 的约定。

只读探测：每次都新建一个 service 实例，不碰 C 的任何文件，不写游戏状态。
输出分两类——

- **必须一致**：v0.2 已经写明的行为，不一致就是 bug，当场能定；
- **需要确认**：v0.2 没定义、但 A 的适配层已经做了假设的地方，把实际行为记下来，
  回来照着改 `referee_client`，或者让 C 补进文档。

用法（在有 C 代码的机器上）：

    # C 的包目录（含 event_service.py）
    python3 scripts/check_c_interface.py --path ~/team_project_ws/src/Robot_checkout/robot_referee/src/robot_referee

    # 只给了模块名，靠 PYTHONPATH 找
    python3 scripts/check_c_interface.py --module event_service

    # 没有 C 的代码，用我们的测试替身先自检脚本本身
    python3 scripts/check_c_interface.py --self-test

不加参数时默认 `--module event_service`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# 判定
PASS = "PASS"      # 与 v0.2 一致
FAIL = "FAIL"      # 与 v0.2 不一致（必错）
NOTE = "NOTE"      # v0.2 未定义，记录实际行为
SKIP = "SKIP"      # 跑不了（异常等）

Record = Tuple[str, str, str, str]  # (类别, 检查项, 期望, 实际)


def _propose(kind: str, number: Optional[int], request_id: str, game_id: str) -> Dict[str, Any]:
    return {
        "game_id": game_id,
        "request_id": request_id,
        "event_type": "propose",
        "payload": {"kind": kind, "number": number},
    }


def _resolve(kind: str, pending_id: Any, version: Any, request_id: str, game_id: str) -> Dict[str, Any]:
    return {
        "game_id": game_id,
        "request_id": request_id,
        "event_type": kind,
        "payload": {"pending_id": pending_id, "version": version},
    }


def _pending_of(state: Dict[str, Any]) -> Any:
    pending = state.get("pending")
    if not isinstance(pending, dict):
        return None
    return pending


def _pid(pending: Dict[str, Any]) -> Any:
    """待确认项的 pending_id：兼容平铺与嵌在 payload 里两种写法。"""
    if "pending_id" in pending:
        return pending["pending_id"]
    nested = pending.get("payload")
    if isinstance(nested, dict):
        return nested.get("pending_id")
    return None


def _ver(pending: Dict[str, Any]) -> Any:
    if "version" in pending:
        return pending["version"]
    nested = pending.get("payload")
    if isinstance(nested, dict):
        return nested.get("version")
    return None


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------


def check_state_fields(make_service: Callable[[], Any]) -> Record:
    try:
        state = make_service().public_state()
    except Exception as exc:  # noqa: BLE001
        return (SKIP, "public_state 字段", "7 个字段", f"调用失败: {exc!r}")

    required = ("game_id", "phase", "remaining", "history", "pending", "finished", "result")
    missing = [name for name in required if name not in state]
    if missing:
        return (FAIL, "public_state 字段", "7 个字段", f"缺 {missing}")
    return (PASS, "public_state 字段", "7 个字段", "齐全")


def check_propose(make_service: Callable[[], Any]) -> List[Record]:
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    try:
        response = service.handle(_propose("gt", 5, "ci-1", game_id))
    except Exception as exc:  # noqa: BLE001
        return [(SKIP, "propose 正常路径", "ok=True 且产生 pending", f"异常: {exc!r}")]

    records: List[Record] = []
    ok = bool(response.get("ok"))
    pending = _pending_of(response.get("state", {}))
    records.append(
        (PASS if ok else FAIL, "propose 正常路径", "ok=True", f"ok={ok}, code={response.get('code')}")
    )
    records.append(
        (PASS if pending else FAIL, "propose 产生 pending", "state.pending 非空", f"pending={pending}")
    )
    if pending:
        records.append(
            (NOTE, "pending 的字段结构", "v0.2 未定义",
             f"keys={sorted(pending.keys())}, pending_id={_pid(pending)}, version={_ver(pending)}")
        )
    return records


def check_dedupe(make_service: Callable[[], Any]) -> List[Record]:
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    event = _propose("gt", 5, "ci-dup", game_id)
    try:
        first = service.handle(dict(event))
        second = service.handle(dict(event))
    except Exception as exc:  # noqa: BLE001
        return [(SKIP, "同 request_id 重发", "duplicate=True", f"异常: {exc!r}")]

    return [
        (
            PASS if first.get("duplicate") is False else NOTE,
            "首次请求 duplicate 标志",
            "False（或缺失）",
            f"{first.get('duplicate')!r}",
        ),
        (
            PASS if second.get("duplicate") is True else FAIL,
            "同 request_id 同内容重发",
            "duplicate=True",
            f"duplicate={second.get('duplicate')!r}, code={second.get('code')!r}",
        ),
    ]


def check_conflict(make_service: Callable[[], Any]) -> Record:
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    try:
        service.handle(_propose("gt", 5, "ci-conflict", game_id))
        response = service.handle(_propose("lt", 5, "ci-conflict", game_id))
    except Exception as exc:  # noqa: BLE001
        return (SKIP, "同 request_id 改内容", "request_conflict", f"异常: {exc!r}")

    ok = response.get("ok")
    code = response.get("code")
    if ok is False and code == "request_conflict":
        return (PASS, "同 request_id 改内容", "ok=False 且 code=request_conflict", "符合")
    return (FAIL, "同 request_id 改内容", "ok=False 且 code=request_conflict", f"ok={ok}, code={code}")


def check_confirm(make_service: Callable[[], Any]) -> List[Record]:
    service = make_service()
    try:
        state0 = service.public_state()
        game_id = state0.get("game_id", "g1")
        remaining0 = state0.get("remaining")
        service.handle(_propose("gt", 5, "ci-c1", game_id))
        pending = _pending_of(service.public_state())
        if not pending:
            return [(FAIL, "confirm 正常路径", "应能拿到 pending", "pending 为空")]
        response = service.handle(_resolve("confirm", _pid(pending), _ver(pending), "ci-c2", game_id))
        state1 = service.public_state()
    except Exception as exc:  # noqa: BLE001
        return [(SKIP, "confirm 正常路径", "ok=True 且计次", f"异常: {exc!r}")]

    records = [
        (
            PASS if response.get("ok") else FAIL,
            "confirm 正常路径",
            "ok=True",
            f"ok={response.get('ok')}, code={response.get('code')}",
        )
    ]
    remaining1 = state1.get("remaining")
    records.append(
        (
            PASS if isinstance(remaining0, int) and remaining1 == remaining0 - 1 else FAIL,
            "confirm 后计次",
            f"remaining {remaining0} → {remaining0 - 1}",
            f"{remaining0} → {remaining1}",
        )
    )
    records.append(
        (PASS if state1.get("pending") in (None, {}) else NOTE, "confirm 后清空 pending", "pending=None",
         f"{state1.get('pending')}")
    )
    return records


def check_stale_pending(make_service: Callable[[], Any]) -> List[Record]:
    """同一局里，旧待确认项的确认会不会被误当成新的。v0.2 未定义错误码。"""
    service = make_service()
    try:
        game_id = service.public_state().get("game_id", "g1")
        service.handle(_propose("gt", 5, "ci-a1", game_id))
        pending_a = _pending_of(service.public_state())
        service.handle(_resolve("cancel", _pid(pending_a), _ver(pending_a), "ci-a2", game_id))
        service.handle(_propose("eq", 7, "ci-b1", game_id))
        before = service.public_state()
        late = service.handle(_resolve("confirm", _pid(pending_a), _ver(pending_a), "ci-a3", game_id))
        after = service.public_state()
    except Exception as exc:  # noqa: BLE001
        return [(SKIP, "同局旧 pending 确认", "应被拒且状态不变", f"异常: {exc!r}")]

    records: List[Record] = [
        (
            PASS if late.get("ok") is False else FAIL,
            "同局旧 pending 确认被拒",
            "ok=False",
            f"ok={late.get('ok')}, code={late.get('code')}",
        ),
        (
            NOTE,
            "同局旧 pending 的错误码",
            "v0.2 未定义，A 暂用 pending_mismatch",
            f"实际 code={late.get('code')!r}  ← **记下来，让 C 补进文档**",
        ),
    ]
    same_remaining = before.get("remaining") == after.get("remaining")
    same_history = before.get("history") == after.get("history")
    same_pending = _pid(_pending_of(before) or {}) == _pid(_pending_of(after) or {})
    records.append(
        (
            PASS if (same_remaining and same_history and same_pending) else FAIL,
            "旧 pending 确认后状态不变",
            "remaining/history/pending 都不变",
            f"remaining={same_remaining}, history={same_history}, pending={same_pending}",
        )
    )
    return records


def check_cancel(make_service: Callable[[], Any]) -> Record:
    service = make_service()
    try:
        game_id = service.public_state().get("game_id", "g1")
        service.handle(_propose("gt", 5, "ci-x1", game_id))
        pending = _pending_of(service.public_state())
        response = service.handle(_resolve("cancel", _pid(pending), _ver(pending), "ci-x2", game_id))
        state = service.public_state()
    except Exception as exc:  # noqa: BLE001
        return (SKIP, "cancel 正常路径", "ok=True 且 pending 清空", f"异常: {exc!r}")

    ok = bool(response.get("ok"))
    cleared = state.get("pending") in (None, {})
    if ok and cleared:
        return (PASS, "cancel 正常路径", "ok=True 且 pending 清空", "符合")
    return (FAIL, "cancel 正常路径", "ok=True 且 pending 清空", f"ok={ok}, pending={state.get('pending')}")


def check_stale_game(make_service: Callable[[], Any]) -> Record:
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    try:
        response = service.handle(_propose("gt", 5, "ci-g1", f"{game_id}-other"))
    except Exception as exc:  # noqa: BLE001
        return (SKIP, "旧局消息", "stale_game", f"异常: {exc!r}")

    code = response.get("code")
    if response.get("ok") is False and code == "stale_game":
        return (PASS, "旧局消息", "ok=False 且 code=stale_game", "符合")
    return (FAIL, "旧局消息", "ok=False 且 code=stale_game", f"ok={response.get('ok')}, code={code}")


def check_extra_payload(make_service: Callable[[], Any]) -> Record:
    """payload 多带一个字段会怎样？v0.2 说「恰为 kind、number」。"""
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    event = _propose("gt", 5, "ci-e1", game_id)
    event["payload"]["note"] = "extra"
    try:
        response = service.handle(event)
    except Exception as exc:  # noqa: BLE001
        return (NOTE, "payload 多余字段", "v0.2 要求恰为 kind/number", f"异常: {exc!r}")

    return (
        NOTE,
        "payload 多余字段",
        "v0.2 要求恰为 kind/number（拒绝）",
        f"实际 ok={response.get('ok')}, code={response.get('code')!r}  ← **确认 C 的校验强度**",
    )


def check_timestamp(make_service: Callable[[], Any]) -> Record:
    """公共字段里的 timestamp 是否被接受？A 默认会带。"""
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    event = _propose("gt", 5, "ci-t1", game_id)
    event["timestamp"] = 1234.5
    try:
        response = service.handle(event)
    except Exception as exc:  # noqa: BLE001
        return (NOTE, "带 timestamp 字段", "interfaces.md 列为公共字段", f"异常: {exc!r}")

    return (
        NOTE,
        "带 timestamp 字段",
        "应被接受（interfaces.md 公共字段）",
        f"实际 ok={response.get('ok')}, code={response.get('code')!r}",
    )


def check_new_game_early(make_service: Callable[[], Any]) -> Record:
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    try:
        response = service.handle(
            {"game_id": game_id, "request_id": "ci-n1", "event_type": "new_game", "payload": {}}
        )
    except Exception as exc:  # noqa: BLE001
        return (NOTE, "未结束时 new_game", "v0.2：仅当前局结束后接受", f"异常: {exc!r}")

    return (
        NOTE,
        "未结束时 new_game",
        "v0.2：仅当前局结束后接受（应当拒绝）",
        f"实际 ok={response.get('ok')}, code={response.get('code')!r}",
    )


def check_repropose_pending(make_service: Callable[[], Any]) -> Record:
    """上一提议还没确认又来一条新提议，会替换还是拒绝？v0.2 未定义。"""
    service = make_service()
    game_id = service.public_state().get("game_id", "g1")
    try:
        service.handle(_propose("gt", 5, "ci-r1", game_id))
        first = _pending_of(service.public_state())
        response = service.handle(_propose("lt", 8, "ci-r2", game_id))
        second = _pending_of(service.public_state())
    except Exception as exc:  # noqa: BLE001
        return (NOTE, "未确认时再提议", "v0.2 未定义", f"异常: {exc!r}")

    if response.get("ok") is False:
        verdict = f"拒绝（code={response.get('code')!r}）"
    elif _pid(first) != _pid(second):
        verdict = "替换为新的 pending（A 的测试替身也是这么做的）"
    else:
        verdict = "沿用同一个 pending"

    return (NOTE, "未确认时再提议", "v0.2 未定义", verdict)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _load_service(path: Optional[str], module: str) -> Callable[[], Any]:
    if path:
        sys.path.insert(0, os.path.abspath(os.path.expanduser(path)))
    imported = __import__(module, fromlist=["RefereeService"])
    factory = getattr(imported, "RefereeService", None)
    if factory is None:
        raise AttributeError(f"{module} 里没有 RefereeService")
    return factory


def _make_self_test() -> Callable[[], Any]:
    tests_dir = os.path.join(os.path.dirname(_HERE), "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from support.fake_referee import FakeReferee  # noqa: PLC0415

    return lambda: FakeReferee(game_id="self-test", secret=6)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="核对 C 的 RefereeService 是否符合 v0.2")
    parser.add_argument("--path", help="C 的包目录（含 event_service.py）")
    parser.add_argument("--module", default="event_service")
    parser.add_argument("--self-test", action="store_true", help="用测试替身自检脚本本身")
    parser.add_argument("--json", action="store_true", help="额外输出一份 JSON，便于存档")
    args = parser.parse_args(argv)

    try:
        make_service = _make_self_test() if args.self_test else _load_service(args.path, args.module)
    except Exception as exc:  # noqa: BLE001
        print(f"无法加载 {args.module}: {exc!r}")
        traceback.print_exc()
        return 2

    print("=" * 78)
    print("C 接口核对：" + ("测试替身自检" if args.self_test else f"{args.module}"))
    print("=" * 78)

    records: List[Record] = []
    records.append(check_state_fields(make_service))
    records.extend(check_propose(make_service))
    records.extend(check_dedupe(make_service))
    records.append(check_conflict(make_service))
    records.extend(check_confirm(make_service))
    records.extend(check_stale_pending(make_service))
    records.append(check_cancel(make_service))
    records.append(check_stale_game(make_service))
    records.append(check_extra_payload(make_service))
    records.append(check_timestamp(make_service))
    records.append(check_new_game_early(make_service))
    records.append(check_repropose_pending(make_service))

    for verdict, name, expected, actual in records:
        print(f"\n[{verdict}] {name}")
        print(f"   期望: {expected}")
        print(f"   实际: {actual}")

    fails = [r for r in records if r[0] == FAIL]
    notes = [r for r in records if r[0] == NOTE]
    skips = [r for r in records if r[0] == SKIP]
    print("\n" + "-" * 78)
    print(f"必错 {len(fails)} 项 / 待确认 {len(notes)} 项 / 跳过 {len(skips)} 项")

    if notes:
        print("\n需要 C 当场回答（v0.2 没定义，A 已经做了假设）：")
        for _, name, _, actual in notes:
            print(f"  · {name}：{actual}")

    if args.json:
        print("\nJSON:")
        print(json.dumps([dict(zip(("verdict", "check", "expected", "actual"), r)) for r in records],
                         ensure_ascii=False, indent=2))

    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
