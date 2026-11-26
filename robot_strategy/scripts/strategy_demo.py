#!/usr/bin/env python3
"""连续十局拿同一张牌，全程如实回答，展示跨局选问。"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from robot_strategy.strategy import suggest, truth

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--style', choices=('mixed', 'balanced', 'edge'), default='mixed')
args = parser.parse_args()
openings = []
for game in range(1, 11):
    history = []
    while True:
        result = suggest(history, 7 - len(history), game_id=str(game),
                         previous_openings=openings, style=args.style)
        q = result['proposal']
        if result['status'] == 'certain':
            break
        history.append(dict(q, answer=truth(3, q['kind'], q['number'])))
    openings.append(history[0])
    print(game, history[0]['kind'], history[0]['number'], len(history), q['number'])
