#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A → C 适配层的时序演示（不需要机器人、不需要 ROS）。

跑的是评审指定的核心场景：

    提议 A → 打开 A 的确认窗口 → 取消 A → 提议 B → A 的旧确认迟到
    → 对 B 有效确认 → 用同一 request_id 重试

C 用 `tests/support/fake_referee.py` 的最小替身，**不是**真实裁判实现，
只用来验证 A 侧的时序与绑定。

用法::

    python scripts/referee_demo.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for path in (os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

from robot_speech import SpeechRefereeClient, parse  # noqa: E402
from support.fake_referee import FakeReferee  # noqa: E402


def _show(label: str, sent=None, state=None) -> None:
    print(f"\n{label}")
    if sent is not None:
        print(f"  request_id={sent.request_id}  ok={sent.ok}  code={sent.code}"
              f"  duplicate={sent.duplicate}")
        print(f"  payload={sent.event['payload']}")
    if state is not None:
        print(f"  state: remaining={state['remaining']} history={len(state['history'])} "
              f"pending={state['pending']['pending_id'] if state['pending'] else None}")


def main() -> int:
    fake = FakeReferee(game_id="demo-game", secret=6)
    client = SpeechRefereeClient(fake, fake.game_id)
    print("C 是测试替身；秘密数字固定为 6。")

    # ① 提议 A
    sent_a = client.propose(parse("大于五吗"))
    window_a = client.open_confirm_window()
    _show("① 提议 A，并在开窗时绑定 pending/version", sent_a)
    print(f"  窗口绑定: {window_a.describe()}")

    # ② 取消 A
    cancelled = client.cancel(window_a)
    _show("② 取消 A", cancelled, client.state)

    # ③ 提议 B
    sent_b = client.propose(parse("是七吗"))
    window_b = client.open_confirm_window()
    _show("③ 提议 B", sent_b)
    print(f"  窗口绑定: {window_b.describe()}")

    # ④ A 的旧确认迟到
    late = client.confirm(window_a)
    _show("④ A 的旧确认迟到：仍带 A 绑定的 pending_id/version", late, client.state)
    print("   ↑ 被拒绝，且 history/remaining 不变，pending 仍是 B")

    # ⑤ 对 B 有效确认
    ok = client.confirm(window_b)
    _show("⑤ 对 B 的有效确认", ok, client.state)

    # ⑥ 同一 request_id 重试
    retry = client.resend(ok)
    _show("⑥ 用同一 request_id 重试", retry, client.state)
    print("   ↑ duplicate=True，remaining 与 history 都没有再变")

    return 0


if __name__ == "__main__":
    sys.exit(main())
