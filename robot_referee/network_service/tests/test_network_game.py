import json
import sys
import unittest
from pathlib import Path
from uuid import uuid4
from threading import Thread
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from network_v1.coordinator import Coordinator
from network_v1.transport import ProtocolError, create_server


class NetworkGameTests(unittest.TestCase):
    def setUp(self):
        self.c = Coordinator({r: 'test-' + r for r in 'ABCD'})
        self.instances = {r: uuid4().hex for r in 'AD'}
        for role in 'AD':
            self.send(role, 'module.heartbeat', {'instance_id': self.instances[role], 'module_status': 'ready', 'active_command_ids': [], 'capabilities': [], 'runtime_mode': 'mock'})
        self.body = dict(protocol_version='1.0', mode='robot_hides', runtime_mode='mock')
        self.key = uuid4().hex
        self.c.create_game('C', self.body, self.key)
        self.c.secret = 7

    def send(self, role, kind, payload, cmd=None):
        e = dict(protocol_version='1.0', request_id=uuid4().hex, game_id=cmd['game_id'] if cmd else None, input_epoch=cmd['input_epoch'] if cmd else None, source=role, command_id=cmd['command_id'] if cmd else None, event_type=kind, payload=payload)
        return self.c.event(role, e, self.instances.get(role, '')), e

    def take(self, role='A', lane='main'):
        cmd = self.c.next(role, role, lane)['command']
        self.assertIsNotNone(cmd)
        self.send(role, 'task.accepted', {}, cmd)
        self.send(role, 'task.started', {}, cmd)
        return cmd

    def done(self, cmd, result):
        return self.send(cmd['target'], 'task.result', dict(status='success', result=result, error=None), cmd)

    def prompt(self):
        cmd = self.take()
        self.assertEqual(cmd['command_type'], 'speech.say')
        self.done(cmd, {'spoken': True})

    def utter(self, intent, number=None, comparison=None):
        cmd = self.take()
        self.assertEqual(cmd['command_type'], 'speech.listen')
        p = cmd['payload']
        return self.done(cmd, dict(intent=intent, comparison=comparison, number=number, answer=None, pending_id=p['pending_id'], pending_version=p['pending_version'], question_id=p['question_id'], utterance='测试', parser='manual_mock', reason=None))

    def question(self, answer=True, lie=False):
        self.prompt()
        self.utter('question', 5, 'gt')
        self.prompt()
        self.utter('confirm')
        cmd = self.take('D', 'strategy')
        return self.done(cmd, dict(decision='answer', comparison=None, number=None, answer=answer, lie_applied=lie, candidates=[], certainty='not_final'))

    def test_complete_game_and_privacy(self):
        self.question()
        public = self.c.public()
        self.assertEqual(public['remaining_questions'], 6)
        self.assertIsNone(public['result'])
        self.assertNotIn('secret', json.dumps(public))
        self.prompt()
        motion = self.take('D', 'motion')
        self.done(motion, {'action': 'nod', 'executed': True})
        self.utter('final_submit', 7)
        self.prompt()
        self.utter('confirm')
        self.assertEqual(self.c.public()['result']['outcome'], 'guesser_win')
        self.assertEqual(self.c.public()['result']['revealed_number'], 7)

    def test_replayed_result_does_not_count_twice(self):
        (_, _), event = self.question()
        before = self.c.public()
        self.assertTrue(self.c.event('D', event, self.instances['D'])[1])
        event['request_id'] = uuid4().hex
        self.c.event('D', event, self.instances['D'])
        self.assertEqual(self.c.public(), before)

    def test_second_lie_rolls_back_result_and_count(self):
        self.question(False, True)
        self.prompt()
        self.utter('question', 5, 'gt')
        self.prompt()
        self.utter('confirm')
        cmd = self.take('D', 'strategy')
        with self.assertRaises(ProtocolError):
            self.done(cmd, dict(decision='answer', comparison=None, number=None, answer=False, lie_applied=True, candidates=[], certainty='not_final'))
        self.assertEqual(self.c.public()['remaining_questions'], 6)
        self.assertEqual(self.c.lookup('D', cmd['command_id'])['status'], 'running')
        self.done(cmd, dict(decision='answer', comparison=None, number=None, answer=True, lie_applied=False, candidates=[], certainty='not_final'))
        self.assertEqual(self.c.public()['remaining_questions'], 5)

    def test_cancel_no_count(self):
        self.prompt()
        self.utter('question', 5, 'gt')
        self.prompt()
        self.utter('cancel')
        self.assertEqual(self.c.public()['remaining_questions'], 7)
        self.assertIsNone(self.c.public()['pending'])

    def control(self, kind):
        s = self.c.public()
        e = dict(protocol_version='1.0', request_id=uuid4().hex, game_id=s['game_id'], input_epoch=s['input_epoch'], source='C', command_id=None, event_type='control.' + kind, payload={})
        return self.c.event('C', e, '')

    def test_pause_old_result_only_cleans_ledger(self):
        self.prompt()
        old = self.take()
        self.control('pause')
        p = old['payload']
        (result, _), _ = self.done(old, dict(intent='question', comparison='gt', number=5, answer=None, pending_id=p['pending_id'], pending_version=p['pending_version'], question_id=None, utterance='大于5', parser='rule', reason=None))
        self.assertEqual(result['disposition'], 'ignored_for_game')
        self.assertEqual(self.c.public()['phase'], 'paused')
        self.control('resume')
        self.assertEqual(self.c.public()['phase'], 'waiting_question')
        self.prompt()
        self.assertEqual(self.c.public()['remaining_questions'], 7)

    def test_bad_pending_is_rejected(self):
        self.prompt()
        self.utter('question', 5, 'gt')
        self.prompt()
        cmd = self.take()
        with self.assertRaises(ProtocolError):
            self.done(cmd, dict(intent='confirm', comparison=None, number=None, answer=None, pending_id=uuid4().hex, pending_version=1, question_id=None, utterance='确认', parser='rule', reason=None))
        self.assertEqual(self.c.public()['remaining_questions'], 7)

    def test_seven_questions_then_final_only(self):
        self.question()
        for _ in range(6):
            self.prompt()
            self.utter('question', 5, 'gt')
            self.prompt()
            self.utter('confirm')
            cmd = self.take('D', 'strategy')
            self.done(cmd, dict(decision='answer', comparison=None, number=None, answer=True, lie_applied=False, candidates=[], certainty='not_final'))
        self.prompt()
        cmd = self.take()
        self.assertNotIn('question', cmd['payload']['allowed_intents'])
        self.assertIn('final_submit', cmd['payload']['allowed_intents'])
        self.assertEqual(len(self.c.public()['history']), 7)

    def test_create_idempotence_and_auth(self):
        response, replay = self.c.create_game('C', self.body, self.key)
        self.assertTrue(replay)
        self.assertEqual(response['state']['game_id'], self.c.public()['game_id'])
        with self.assertRaises(ProtocolError):
            self.c.create_game('A', self.body, uuid4().hex)

    def test_true_speech_required(self):
        cmd = self.take()
        with self.assertRaises(ProtocolError):
            self.done(cmd, {'spoken': False})
        self.assertEqual(self.c.lookup('A', cmd['command_id'])['status'], 'running')

    def test_duplicate_confirm_does_not_requeue_strategy(self):
        self.prompt()
        self.utter('question', 5, 'gt')
        self.prompt()
        (_, _), event = self.utter('confirm')
        self.c.event('A', event, self.instances['A'])
        self.assertEqual(sum(t['command']['command_type'] == 'strategy.decide' for t in self.c.tasks.values()), 1)

    def test_resume_rotates_pending(self):
        self.prompt()
        self.utter('question', 5, 'gt')
        old = self.c.public()['pending']
        self.control('pause')
        self.control('resume')
        pending = self.c.public()['pending']
        self.assertNotEqual(old['pending_id'], pending['pending_id'])
        self.assertEqual(pending['pending_version'], old['pending_version'] + 1)

    def test_http_whole_game(self):
        server = create_server(self.c, 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        original_send = self.send
        original_take = self.take
        def send_http(role, kind, payload, cmd=None):
            event = dict(protocol_version='1.0', request_id=uuid4().hex, game_id=cmd['game_id'] if cmd else None, input_epoch=cmd['input_epoch'] if cmd else None, source=role, command_id=cmd['command_id'] if cmd else None, event_type=kind, payload=payload)
            request = Request(base + '/api/v1/events', data=json.dumps(event).encode(), headers={'Authorization':'Bearer test-' + role, 'X-Roban-Instance':self.instances[role], 'Content-Type':'application/json'})
            with urlopen(request, timeout=2) as response:
                result = json.load(response)
            return (result['data'], result['replayed']), event
        def take_http(role='A', lane='main'):
            request = Request(base + '/api/v1/modules/' + role + '/commands/next?lane=' + lane, headers={'Authorization':'Bearer test-' + role})
            with urlopen(request, timeout=2) as response:
                cmd = json.load(response)['data']['command']
            self.assertIsNotNone(cmd)
            send_http(role, 'task.accepted', {}, cmd)
            send_http(role, 'task.started', {}, cmd)
            return cmd
        self.send, self.take = send_http, take_http
        try:
            self.test_complete_game_and_privacy()
            with urlopen(base + '/api/v1/state/public', timeout=2) as response:
                self.assertEqual(json.load(response)['data']['state']['result']['outcome'], 'guesser_win')
        finally:
            self.send, self.take = original_send, original_take
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_create_and_public_state(self):
        other = Coordinator({r: 'test-' + r for r in 'ABCD'})
        server = create_server(other, 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            request = Request(base + '/api/v1/games', data=json.dumps(self.body).encode(), headers={'Authorization': 'Bearer test-C', 'Idempotency-Key': uuid4().hex, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 201)
            with urlopen(base + '/api/v1/state/public', timeout=2) as response:
                self.assertEqual(json.load(response)['data']['state']['remaining_questions'], 7)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
