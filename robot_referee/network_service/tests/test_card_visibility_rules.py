import unittest
import test_network_player as fixtures


class CardVisibilityRulesTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PlayerNetworkTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_robot_guesses_without_opening_capture(self):
        f=self.f
        self.assertIsNone(f.c.secret)
        self.assertIsNone(f.c.next('B','B','main')['command'])
        f.register()
        cmd=f.take('D','strategy')
        self.assertNotIn('secret',cmd['payload'])
        self.assertFalse(any(t['command']['command_type']=='vision.capture' for t in f.c.tasks.values()))

    def test_secret_unknown_until_confirmed_final_reveal(self):
        f=self.f
        f.register();f.question(True)
        self.assertIsNone(f.c.secret)
        self.assertIsNone(f.c.next('B','B','main')['command'])
        f.final()
        self.assertEqual(f.c.public()['final_submission'],7)
        self.assertIsNone(f.c.secret)
        self.assertEqual(f.c.next('B','B','main')['command']['payload']['purpose'],'reveal')
        f.capture(7)
        self.assertIsNone(f.c.secret)
        self.assertIsNone(f.c.public()['result'])
        f.prompt();f.utter('confirm')
        self.assertEqual(f.c.secret,7)
        self.assertEqual(f.c.public()['result']['outcome'],'guesser_win')

    def test_player_guesses_robot_must_remember_card_first(self):
        f=self.f
        f.new_robot_game()
        self.assertIsNone(f.c.secret)
        self.assertEqual(f.c.public()['phase'],'registration_capture')
        self.assertIsNone(f.c.next('A','A','main')['command'])
        f.capture(4)
        self.assertIsNone(f.c.secret)
        cmd=f.take('B')
        f.done(cmd,dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=True))
        self.assertEqual(f.c.secret,4)
        self.assertEqual(f.c.public()['phase'],'waiting_question')
        self.assertNotIn('4',f.prompt()['payload']['text'])

    def test_exit_without_reveal_cannot_claim_winner(self):
        f=self.f
        f.register();f.question(True)
        # A's exit-confirmation path must also work while card truth is unknown.
        cmd=f.take('D','strategy')
        f.done(cmd,dict(decision='final_submit',comparison=None,number=7,answer=None,lie_applied=None,candidates=f.c.candidates(),certainty='guess'))
        f.prompt();f.utter('exit');f.prompt();f.utter('confirm')
        self.assertEqual(f.c.public()['result']['outcome'],'exited')
        self.assertIsNone(f.c.public()['result']['revealed_number'])


if __name__=='__main__':unittest.main()
