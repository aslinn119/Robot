import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from network_v1.d_strategy_adapter import decide, StrategyUnavailable
from vendor_d.strategy import suggest
import test_network_player as fixtures


class DIntegrationTests(unittest.TestCase):
    def test_all_real_strategy_paths_through_c(self):
        paths=[]
        def walk(history):
            result=suggest(history,7-len(history))
            if result['status']=='certain':
                secret=result['proposal']['number']
                paths.append((secret,history))
                return
            self.assertEqual(result['status'],'question')
            q=result['proposal']
            for answer in (False,True):
                next_history=history+[dict(q,answer=answer)]
                possible=[]
                for n in range(1,11):
                    errors=sum({'gt':n>x['number'],'lt':n<x['number'],'eq':n==x['number']}[x['kind']]!=x['answer'] for x in next_history)
                    if errors<=1:possible.append(n)
                if possible:walk(next_history)
        walk([])
        self.assertEqual(len(paths),56)
        maximum=0
        for secret,history in paths:
            with self.subTest(secret=secret,history=history):
                f=fixtures.PlayerNetworkTests('runTest')
                f.setUp()
                try:
                    f.capture(secret)
                    cmd=f.take('B')
                    f.done(cmd,dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=True))
                    f.prompt()
                    for expected in history:
                        cmd=f.take('D','strategy')
                        result=decide(cmd['payload'])
                        self.assertEqual(result['decision'],'question')
                        self.assertEqual(result['comparison'],expected['kind'])
                        self.assertEqual(result['number'],expected['number'])
                        f.done(cmd,result)
                        f.prompt();f.utter('answer',expected['answer']);f.prompt();f.utter('confirm')
                    cmd=f.take('D','strategy')
                    result=decide(cmd['payload'])
                    self.assertEqual(result['decision'],'final_submit')
                    self.assertEqual(result['number'],secret)
                    f.done(cmd,result)
                    f.prompt();f.utter('confirm');f.reveal(secret)
                    self.assertEqual(f.c.public()['result']['outcome'],'guesser_win')
                    self.assertLessEqual(f.c.public()['result']['lie_count'],1)
                    maximum=max(maximum,len(f.c.public()['history']))
                finally:f.doCleanups()
        self.assertEqual(maximum,7)

    def test_answer_bridge_deterministic_and_budget(self):
        for secret in range(1,11):
            for seed in range(16):
                used=False
                for ordinal in range(1,8):
                    payload=dict(purpose='answer_question',secret=secret,question=dict(comparison='gt',number=5),lie_used=used,decision_seed=seed,question_ordinal=ordinal)
                    result=decide(payload)
                    self.assertEqual(result,decide(payload))
                    if result['lie_applied']:
                        self.assertFalse(used)
                        used=True
                    self.assertEqual(result['answer']!=(secret>5),result['lie_applied'])

    def test_insufficient_strategy_does_not_invent_guess(self):
        history=[dict(question_id='test',comparison='gt',number=10,answer=False)]*7
        with self.assertRaises(StrategyUnavailable):
            decide(dict(purpose='guess_next',history=history,remaining_questions=0))


if __name__=='__main__':unittest.main()
