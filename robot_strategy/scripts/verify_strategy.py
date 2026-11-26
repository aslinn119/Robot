#!/usr/bin/env python3
"""枚举策略树的全部可达合法回答分支，并独立核对候选。"""
import json
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from robot_strategy.strategy import opening_questions, suggest


def verify(all_openings=False):
    started = time.monotonic()
    counts = {'nodes': 0, 'leaves': 0, 'secret_paths': 0, 'max_questions': 0}
    def walk(history):
        # 独立的直接真值表，不调用被测候选更新函数。
        possible = []
        for secret in range(1, 11):
            errors = 0
            for row in history:
                actual = {'gt': secret > row['number'], 'lt': secret < row['number'],
                          'eq': secret == row['number']}[row['kind']]
                errors += actual != row['answer']
            if errors <= 1:
                possible.append((secret, errors))
        if not possible:
            return
        result = suggest(history, 7 - len(history))
        assert result['s0'] == [x for x, e in possible if e == 0]
        assert result['s1'] == [x for x, e in possible if e == 1]
        counts['nodes'] += 1
        counts['max_questions'] = max(counts['max_questions'], len(history))
        proposal = result['proposal']
        if result['status'] == 'certain':
            assert len(possible) == 1 and proposal['number'] == possible[0][0]
            counts['leaves'] += 1
            counts['secret_paths'] += len(possible)
            return
        assert result['status'] == 'question' and len(history) < 7, (history, result)
        for answer in (False, True):
            walk(history + [dict(proposal, answer=answer)])
    if all_openings:
        observed = set()
        index = 0
        while len(observed) < len(opening_questions()):
            assert index < 10000, '有候选开局未通过实际入口选中'
            game_id = format(index, '032x')
            index += 1
            proposal = suggest([], 7, game_id=game_id)['proposal']
            key = (proposal['kind'], proposal['number'])
            if key in observed:
                continue
            observed.add(key)
            assert suggest([], 7, game_id=game_id)['proposal'] == proposal
            for answer in (False, True):
                walk([dict(proposal, answer=answer)])
        counts['openings'] = sorted(observed)
    else:
        walk([])
    return dict(counts, passed=True, seconds=round(time.monotonic() - started, 3))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--all-openings', action='store_true')
    print(json.dumps(verify(parser.parse_args().all_openings), ensure_ascii=False, indent=2))
