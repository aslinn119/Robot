#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线交互流程演示：把上机前必须跑通的三条走一遍，并为每条落一份 JSONL 日志。

不需要机器人、不需要 ROS。C 用测试替身，播报用模拟喇叭。

    python scripts/dialogue_demo.py                    # 日志写到 evidence/logs/
    python scripts/dialogue_demo.py --log-raw          # 日志里带原始语音文本
    python scripts/dialogue_demo.py --log-dir my_logs

产物：

    evidence/logs/scenario1.jsonl   播报失败不开窗 / 播完才开窗 / 确认生效
    evidence/logs/scenario2.jsonl   取消 A → 提议 B → A 的确认迟到
    evidence/logs/scenario3.jsonl   有效确认只生效一次（含同 request_id 重试）
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for path in (os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

from robot_speech import (  # noqa: E402
    EventLog,
    GameSession,
    ScriptedInput,
    SimulatedSpeaker,
    SpeechRefereeClient,
    Utterance,
)
from support.fake_referee import FakeReferee  # noqa: E402

DEFAULT_LOG_DIR = os.path.join(_ROOT, "evidence", "logs")


class Runner:
    """管理「一次场景 = 一个会话 + 一个日志文件」。"""

    def __init__(self, log_dir: str, include_text: bool) -> None:
        self._dir = log_dir
        self._include_text = include_text
        self._handles: List[Tuple[str, object]] = []
        os.makedirs(log_dir, exist_ok=True)

    def new_session(self, name: str, script=None, *, allow_unverified: bool = False):
        path = os.path.join(self._dir, f"{name}.jsonl")
        handle = open(path, "w", encoding="utf-8")
        self._handles.append((path, handle))

        fake = FakeReferee(game_id=name, secret=6)
        client = SpeechRefereeClient(fake, fake.game_id)
        speaker = SimulatedSpeaker(script, default="completed")
        log = EventLog(handle, session=name, include_text=self._include_text)
        session = GameSession(
            client,
            ScriptedInput([]),
            speaker,
            log=log,
            allow_unverified_playback=allow_unverified,
        )
        return client, speaker, session, path

    def close(self) -> None:
        for path, handle in self._handles:
            handle.close()


def _line(record) -> str:
    detail = f" ({record.detail})" if record.detail else ""
    said = f"  朗读：{record.spoken}" if record.spoken else ""
    return f"  {record.text:<12} -> {record.status}{detail}{said}"


def scenario_1(runner: Runner) -> str:
    print("\n=== 场景 1：播报失败不开窗；观察到播完才开窗 ===")
    client, speaker, session, path = runner.new_session("scenario1", script=["failed"])

    print(_line(session.process(Utterance("大于五吗"))))
    print(f"       窗口：{session.window_key}（None = 没开）")
    print(_line(session.process(Utterance("确认"))))
    print(f"       剩余次数 {client.state['remaining']}（没变）")

    print("  ← 只重播复述（不重新提议）")
    retry = session.retry_recitation()
    print(f"  {'<retry>':<12} -> {retry.status}  窗口：{session.window_key}")
    print(_line(session.process(Utterance("确认", window_key=session.window_key))))
    print(f"       剩余次数 {client.state['remaining']}，历史 {len(client.state['history'])}")
    return path


def scenario_2(runner: Runner) -> str:
    print("\n=== 场景 2：迟到结果不能串到下一轮 ===")
    client, speaker, session, path = runner.new_session("scenario2")

    print(_line(session.process(Utterance("大于五吗"))))
    key_a = session.window_key
    print(f"       窗口 A：{key_a}")
    print(_line(session.process(Utterance("取消", window_key=key_a))))
    print(_line(session.process(Utterance("是七吗"))))
    key_b = session.window_key
    print(f"       窗口 B：{key_b}")

    before = client.state
    requests = client.request_count
    print("\n  ← A 的确认现在才到（仍带窗口 A 的 key）")
    print(_line(session.process(Utterance("确认", window_key=key_a))))
    after = client.state
    print(f"       请求数 {requests} → {client.request_count}（没有发给裁判）")
    print(f"       次数 {before['remaining']} → {after['remaining']}，"
          f"历史 {len(before['history'])} → {len(after['history'])}，"
          f"待确认仍是 {after['pending']['pending_id']}")
    return path


def scenario_3(runner: Runner) -> str:
    print("\n=== 场景 3：有效确认只生效一次 ===")
    client, speaker, session, path = runner.new_session("scenario3")

    session.process(Utterance("大于五吗"))
    session.process(Utterance("取消", window_key=session.window_key))
    session.process(Utterance("是七吗"))
    key_b = session.window_key

    print(_line(session.process(Utterance("确认", window_key=key_b))))
    print(f"       次数剩余={client.state['remaining']}，历史={len(client.state['history'])}")

    sent = client.request_count
    print("\n  ← 同一轮再确认一次（模拟识别重复推送）")
    print(_line(session.process(Utterance("确认", window_key=key_b))))
    print(f"       请求数 {sent} → {client.request_count}，"
          f"次数剩余={client.state['remaining']}，历史={len(client.state['history'])}")

    print("\n  ← 客户端层用同一 request_id 重试（网络重试）")
    retry = client.resend(session.last_sent)
    session.log.emit(
        "client.resend",
        request_id=retry.request_id,
        result="duplicate" if retry.duplicate else "accepted",
        data={"ok": retry.ok, "remaining": client.state["remaining"],
              "history": len(client.state["history"])},
    )
    print(f"       request_id={retry.request_id} duplicate={retry.duplicate} ok={retry.ok}")
    print(f"       次数剩余={client.state['remaining']}，历史={len(client.state['history'])}")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="离线交互流程演示 + JSONL 日志")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--log-raw", action="store_true", help="日志里记录原始语音/播报文本")
    args = parser.parse_args(argv)

    print("C = 测试替身（秘密数字 6）；播报 = 模拟喇叭。这不是实机验证。")
    runner = Runner(args.log_dir, args.log_raw)
    paths = []
    try:
        paths.append(scenario_1(runner))
        paths.append(scenario_2(runner))
        paths.append(scenario_3(runner))
    finally:
        runner.close()

    print("\n日志：")
    for path in paths:
        print(f"  {path}")
    print("\n提醒：这些日志只证明流程时序，不证明机器人真的播完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
