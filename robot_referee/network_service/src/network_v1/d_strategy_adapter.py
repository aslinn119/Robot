"""Protocol adapter for D's unchanged, pure-Python strategy delivery."""
import random
from vendor_d.strategy import suggest, answer_suggestion


class StrategyUnavailable(ValueError):
    pass


def decide(payload):
    if payload['purpose'] == 'guess_next':
        history = [dict(kind=q['comparison'], number=q['number'], answer=q['answer']) for q in payload['history']]
        suggestion = suggest(history, payload['remaining_questions'])
        proposal = suggestion['proposal']
        if suggestion['status'] not in ('question', 'certain') or proposal is None:
            raise StrategyUnavailable(suggestion['status'])
        candidates = sorted(suggestion['s0'] + suggestion['s1'])
        final = proposal['kind'] == 'submit'
        return dict(decision='final_submit' if final else 'question',
                    comparison=None if final else proposal['kind'], number=proposal['number'],
                    answer=None, lie_applied=None, candidates=candidates,
                    certainty='unique' if final else 'not_final')
    if payload['purpose'] == 'answer_question':
        # D exposes use_lie explicitly. The bridge adds the protocol's stable seed plan;
        # it never modifies D's function or records the lie budget itself.
        ordinal = random.Random(payload['decision_seed']).randrange(8)
        use_lie = not payload['lie_used'] and ordinal != 0 and ordinal == payload['question_ordinal']
        q = payload['question']
        result = answer_suggestion(payload['secret'], q['comparison'], q['number'],
                                   lies_used=int(payload['lie_used']), use_lie=use_lie)
        return dict(decision='answer', comparison=None, number=None,
                    answer=result['answer'], lie_applied=result['uses_lie'],
                    candidates=[], certainty='not_final')
    raise StrategyUnavailable('unsupported purpose')
