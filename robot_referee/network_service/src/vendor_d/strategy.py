"""仅从已确认公开历史推理；不读取秘密值，不修改裁判状态。"""
from functools import lru_cache

NUMBERS = tuple(range(1, 11))
QUESTIONS = tuple((kind, n) for kind in ('gt', 'lt', 'eq') for n in NUMBERS)


def truth(number, kind, threshold):
    if type(number) is not int or number not in NUMBERS:
        raise ValueError('牌值必须是 1～10 的整数')
    if kind not in ('gt', 'lt', 'eq') or type(threshold) is not int or threshold not in NUMBERS:
        raise ValueError('问题必须为 gt/lt/eq 和 1～10 的整数')
    return {'gt': number > threshold, 'lt': number < threshold, 'eq': number == threshold}[kind]


def advance(state, question, answer):
    if type(answer) is not bool:
        raise ValueError('回答必须为 bool，不能用字符串或整数代替')
    kind, n = question
    # 每个数字保留累计不一致数，超过一次即排除。
    return tuple((x, errors + int(truth(x, kind, n) != answer))
                 for x, errors in state if errors + int(truth(x, kind, n) != answer) <= 1)


def candidates(history):
    if not isinstance(history, list) or len(history) > 7:
        raise ValueError('history 必须为最多七条已确认问答的列表')
    state = tuple((n, 0) for n in NUMBERS)
    for item in history:
        if not isinstance(item, dict) or set(item) != {'kind', 'number', 'answer'}:
            raise ValueError('每条历史恰含 kind、number、answer；只传已确认问答')
        truth(1, item['kind'], item['number'])
        state = advance(state, (item['kind'], item['number']), item['answer'])
    return state


@lru_cache(maxsize=65536)
def solve(state, remaining):
    """有限深度全分支搜索；只在两个合法回答分支都可解时接受问题。"""
    if len(state) <= 1:
        return None
    if remaining <= 0 or sum(remaining + 1 if e == 0 else 1 for _, e in state) > 2 ** remaining:
        return False
    choices = []
    seen = set()
    for question in QUESTIONS:
        branches = tuple(advance(state, question, answer) for answer in (False, True))
        if branches in seen or state in branches:
            continue
        seen.add(branches)
        weight = max(sum(remaining if e == 0 else 1 for _, e in b) for b in branches)
        choices.append((weight, question, branches))
    for _, question, branches in sorted(choices):
        if all(solve(branch, remaining - 1) is not False for branch in branches):
            return question
    return False


def suggest(history, remaining):
    state = candidates(history)
    if type(remaining) is not int or not 0 <= remaining <= 7 or remaining != 7 - len(history):
        raise ValueError('remaining 必须等于 7 减已确认问答数')
    result = {'s0': [x for x, e in state if e == 0], 's1': [x for x, e in state if e == 1]}
    if not state:
        return dict(result, status='inconsistent', proposal=None)
    if len(state) == 1:
        return dict(result, status='certain', proposal={'kind': 'submit', 'number': state[0][0]})
    question = solve(state, remaining)
    if question is False:
        return dict(result, status='insufficient', proposal=None)
    return dict(result, status='question', proposal={'kind': question[0], 'number': question[1]})


def answer_suggestion(secret, kind, number, lies_used=0, use_lie=False):
    """藏牌侧的纯建议；额度由裁判在确认提交后记账，重试不在此扣减。"""
    if type(lies_used) is not int or lies_used not in (0, 1) or type(use_lie) is not bool:
        raise ValueError('说谎额度或开关无效')
    if use_lie and lies_used:
        raise ValueError('本局说谎额度已用尽')
    value = truth(secret, kind, number)
    return {'answer': not value if use_lie else value, 'uses_lie': use_lie}
