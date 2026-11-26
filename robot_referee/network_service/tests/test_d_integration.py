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
        gid='00000000000000000000000000000000'
        def walk(history):
            result=suggest(history,7-len(history),game_id=gid)
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
        self.assertEqual(len(paths),58)
        maximum=0
        for secret,history in paths:
            with self.subTest(secret=secret,history=history):
                f=fixtures.PlayerNetworkTests('runTest')
                f.setUp()
                try:
                    f.c.state['game_id']=gid
                    for task in f.c.tasks.values():
                        task['command']['game_id']=gid
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
                    payload=dict(purpose='answer_question',mode='robot_hides',max_lies=1,secret=secret,question=dict(comparison='gt',number=5),lie_used=used,decision_seed=seed,question_ordinal=ordinal)
                    result=decide(payload)
                    self.assertEqual(result,decide(payload))
                    if result['lie_applied']:
                        self.assertFalse(used)
                        used=True
                    self.assertEqual(result['answer']!=(secret>5),result['lie_applied'])

    def test_exhaustion_returns_explicit_guess(self):
        history=[dict(question_id='test',comparison='gt',number=10,answer=False)]*7
        result=decide(dict(purpose='guess_next',mode='player_hides',history=history,remaining_questions=0,max_lies=1))
        self.assertEqual(result['decision'],'final_submit')
        self.assertEqual(result['certainty'],'guess')
        self.assertIn(result['number'],result['candidates'])

    def test_same_game_profile_retries_are_stable(self):
        p=dict(purpose='guess_next',mode='player_hides',history=[],remaining_questions=7,max_lies=1)
        for style in ('mixed','balanced','edge'):
            self.assertEqual(decide(p,game_id='stable',profile=([],style)),decide(p,game_id='stable',profile=([],style)))

if __name__=='__main__':unittest.main()
