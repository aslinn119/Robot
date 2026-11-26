"""用队友 A 的真实文本解析和 D 的业务适配离线联调；本脚本模拟 C 的确认和计次。"""
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from robot_speech.speech_parser import parse
from robot_speech.speech_commands import build_listen_result
from robot_strategy.team_strategy import decide, replay_profile


def hear(text, intent, **bindings):
    result = build_listen_result(parse(text), dict(allowed_intents=[intent], **bindings), text)
    assert result['intent'] == intent, result
    return result


def confirm(pending_id):
    event = hear('确认', 'confirm', pending_id=pending_id, pending_version=1)
    assert (event['pending_id'], event['pending_version']) == (pending_id, 1)


def run():
    question = hear('大于五吗', 'question')
    assert (question['comparison'], question['number']) == ('gt', 5)
    qid = UUID(int=1).hex
    confirm(qid)
    payload = dict(mode='robot_hides', purpose='answer_question', secret=7,
                   question=dict(question_id=qid, comparison=question['comparison'],
                                 number=question['number']), history=[], question_ordinal=1,
                   lie_used=False, max_lies=1, decision_seed=123456)
    answer = decide(UUID(int=2).hex, payload)
    assert answer == decide(UUID(int=2).hex, payload)
    assert answer['answer'] == (not answer['lie_applied'])
    games = []
    for game in range(10):
        history = []
        openings, style = replay_profile(games)
        while True:
            payload = dict(mode='player_hides', purpose='guess_next', history=history,
                           remaining_questions=7-len(history), max_lies=1)
            result = decide(UUID(int=game+3).hex, payload, previous_openings=openings, style=style)
            if result['decision'] == 'final_submit':
                assert (result['number'], result['certainty']) == (3, 'unique')
                break
            assert len(history) < 7
            n = result['number']
            actual = {'gt': 3 > n, 'lt': 3 < n, 'eq': 3 == n}[result['comparison']]
            spoken = actual != (len(history) == game % 8)
            qid = UUID(int=100+game*10+len(history)).hex
            heard = hear('是' if spoken else '不是', 'answer', question_id=qid)
            assert (heard['question_id'], heard['answer']) == (qid, spoken)
            confirm(UUID(int=300+game*10+len(history)).hex)
            history.append(dict(question_id=qid, comparison=result['comparison'],
                                number=n, answer=heard['answer']))
        games.append(dict(phase='finished', mode='player_hides', history=history))
    print('通过：机器人藏牌问答及重试；连续十局同牌猜牌、语音文本回答和确认。')


if __name__ == '__main__':
    run()
