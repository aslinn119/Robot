#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 模块阶段一的独立运行入口（纯 Python，不需要 ROS）。

用法::

    # 单句解析
    python speech_cli.py "大于五吗"

    # 输出 JSON（字段与交给游戏逻辑模块的一致）
    python speech_cli.py --json "大于五吗"

    # 交互模式，一行一句，输入 q 退出
    python speech_cli.py

    # 用模拟 IAT 事件文件演示组装器（每行一个 JSON 对象）
    python speech_cli.py --iat tests/fixtures/simulated_iat_events.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from robot_speech import IatAssembler, IatError, parse  # noqa: E402


def _print_result(raw: str, as_json: bool) -> None:
    result = parse(raw)
    if as_json:
        print(json.dumps(result.to_debug_dict(), ensure_ascii=False))
    else:
        detail = (
            "" if result.accepted or not result.normalized_text
            else f"  归一化={result.normalized_text!r}"
        )
        print(f"{raw!r} -> {result}{detail}")


def _run_once(text: str, as_json: bool) -> int:
    _print_result(text, as_json)
    return 0


def _run_interactive(as_json: bool) -> int:
    print("输入一句话回车解析；输入 q 或空行退出。")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line.strip() or line.strip().lower() in ("q", "quit", "exit"):
            return 0
        _print_result(line, as_json)


def _run_iat(path: str) -> int:
    if not os.path.exists(path):
        print(f"找不到文件: {path}", file=sys.stderr)
        return 2
    assembler = IatAssembler()
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                update = assembler.push(line)
            except IatError as exc:
                print(f"[{line_no}] IatError {exc}")
                continue
            flags = []
            if update.is_final:
                flags.append("FINAL")
            if update.is_duplicate:
                flags.append("dup")
            if update.revision:
                flags.append("rev")
            flag_text = ",".join(flags) if flags else "partial"
            print(f"[{line_no}] {flag_text:<14} text={update.text!r} delta={update.delta!r}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A 模块中文意图解析器演示")
    parser.add_argument("text", nargs="*", help="要解析的句子；省略则进入交互模式")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON（含拒绝原因）")
    parser.add_argument("--iat", metavar="FILE", help="回放模拟 IAT 事件文件（JSON 每行一条）")
    args = parser.parse_args(argv)

    if args.iat:
        return _run_iat(args.iat)
    if args.text:
        return _run_once(" ".join(args.text), args.json)
    return _run_interactive(args.json)


if __name__ == "__main__":
    sys.exit(main())
