#!/usr/bin/env python3
"""公开历史驱动的离线样例，不连接裁判、不发送机器人动作。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from robot_strategy.strategy import suggest

history = []
for answer in (None, True, False, True):
    if answer is not None:
        history.append(dict(result['proposal'], answer=answer))
    result = suggest(history, 7-len(history))
    print(json.dumps({'confirmed_history': history, 'suggestion': result}, ensure_ascii=False))
    if result['status'] != 'question':
        break
