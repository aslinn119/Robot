#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 的 TEAM_INTERFACE v1.0 客户端入口：拉命令、执行、回传。

与旧的 `speech_node.py` 的区别：
- 旧节点自己编排「提议 → 复述 → 确认」（v0.2 进程内接口，已由规范取代）；
- 本脚本只做 C 派的 `speech.say` / `speech.listen` 两条命令，**顺序由 C 决定**。

启动（机器人上，先 source 环境）：

    export ROBAN_BASE_URL=http://<C的局域网IP>:8780
    export ROBAN_TOKEN_A=<A 的令牌>
    python3 scripts/speech_agent.py

可选环境变量：
    ROBAN_RUNTIME_MODE   mock / robot（默认 robot，会写进心跳）
    ROBAN_LOG_PATH       事件日志路径；默认 ~/.ros/robot_speech/agent-<run_id>.jsonl
    ROBAN_LOG_RAW_TEXT   1 时记录原始语音文本
"""

from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
for _path in (_HERE, _SRC):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from robot_speech import CommandAgent, EventLog, HttpRefereeClient, default_handlers  # noqa: E402
from robot_speech.http_client import RefereeHttpError  # noqa: E402
from robot_speech.team_protocol import SOURCE_A  # noqa: E402


def _fatal(message: str) -> int:
    print(f"[错误] {message}", file=sys.stderr)
    return 2


def main() -> int:
    base_url = os.environ.get("ROBAN_BASE_URL", "").strip()
    token = os.environ.get("ROBAN_TOKEN_A", "").strip()

    if not base_url:
        return _fatal("未设置 ROBAN_BASE_URL，例如 http://192.168.1.20:8780")
    if not token:
        return _fatal("未设置 ROBAN_TOKEN_A（令牌不要写进代码或日志）")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    log_path = os.environ.get("ROBAN_LOG_PATH") or os.path.expanduser(
        f"~/.ros/robot_speech/agent-{run_id}.jsonl"
    )
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    log = EventLog(
        open(log_path, "a", encoding="utf-8"),
        session=f"a-{run_id}",
        include_text=os.environ.get("ROBAN_LOG_RAW_TEXT") == "1",
    )
    log.anchor()

    client = HttpRefereeClient(base_url, token, source=SOURCE_A)
    print(f"C = {base_url}  实例 {client.instance_id}  日志 {log_path}")

    try:
        health = client.health()
    except RefereeHttpError as exc:
        log.close()
        return _fatal(f"连不上 C：{exc}")

    print(f"health: {health.get('data', {}).get('service_status')}")

    # 设备适配复用旧节点里的实现（同样的 TTS 服务与话题），只是不再由它编排流程
    try:
        from speech_node import RosInput, RosSpeaker
    except Exception as exc:  # 缺 rospy 或厂商 srv
        log.close()
        return _fatal(f"加载 ROS 适配层失败：{exc}")

    speaker = RosSpeaker(log=log)
    input_source = RosInput(lambda: None, log=log)

    agent = CommandAgent(
        client,
        default_handlers(speaker, input_source),
        source=SOURCE_A,
        log=log,
        runtime_mode=os.environ.get("ROBAN_RUNTIME_MODE", "robot"),
    )

    print("开始拉取命令（Ctrl-C 退出）")
    try:
        agent.run_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        log.emit("session.end", data={"reason": "exit"})
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
