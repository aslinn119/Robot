import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from threading import Thread
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from network_v1.durable import DurableCoordinator
from network_v1.transport import ProtocolError, create_server
import test_network_game as game_tests
from robot_fixture import prepare_robot_card


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100.0
        self.tokens = {r:'private-token-' + r for r in 'ABCD'}
        self.c = DurableCoordinator(self.tokens, self.tmp.name, clock=lambda:self.now)
        self.instance = uuid4().hex
        self.body = dict(protocol_version='1.0', mode='robot_hides', runtime_mode='mock')
        self.key = uuid4().hex
        self.event('module.heartbeat', dict(instance_id=self.instance, module_status='ready', active_command_ids=[], capabilities=['speech.say','speech.listen'], runtime_mode='mock'))
        self.c.create_game('C', self.body, self.key)
        prepare_robot_card(self.c)

    def event(self, kind, payload, cmd=None):
        e = dict(protocol_version='1.0', request_id=uuid4().hex, game_id=cmd['game_id'] if cmd else None, input_epoch=cmd['input_epoch'] if cmd else None, source='A', command_id=cmd['command_id'] if cmd else None, event_type=kind, payload=payload)
        return self.c.event('A', e, self.instance), e

    def start(self):
        cmd = self.c.next('A','A','main')['command']
        self.event('task.accepted', {}, cmd)
        self.event('task.started', {}, cmd)
        return cmd

    def test_snapshot_written_and_tokens_excluded(self):
        data = json.loads(self.c.path.read_text(encoding='utf-8'))
        self.assertEqual(data['current']['state']['remaining_questions'],7)
        self.assertEqual(data['current']['secret'],self.c.secret)
        for token in self.tokens.values():
            self.assertNotIn(token, self.c.path.read_text(encoding='utf-8'))

    def test_restart_marks_interrupted_without_reveal(self):
        gid = self.c.public()['game_id']
        restarted = DurableCoordinator(self.tokens,self.tmp.name)
        self.assertIsNone(restarted.public())
        old = restarted.game_public(gid)
        self.assertEqual(old['result']['reason_code'],'SERVER_INTERRUPTED')
        self.assertIsNone(old['result']['revealed_number'])
        self.assertEqual(restarted.tasks,{})
        again = DurableCoordinator(self.tokens,self.tmp.name)
        self.assertEqual(again.game_public(gid),old)

    def test_write_failure_rolls_back_result_and_retry_commits_once(self):
        cmd = self.start()
        before = self.c.public()
        disk = self.c.path.read_bytes()
        with patch('network_v1.durable.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(ProtocolError) as caught:
                self.event('task.result',dict(status='success',result={'spoken':True},error=None),cmd)
        self.assertEqual(caught.exception.code,'JOURNAL_UNAVAILABLE')
        self.assertEqual(self.c.public(),before)
        self.assertEqual(self.c.path.read_bytes(),disk)
        self.assertEqual(self.c.lookup('A',cmd['command_id'])['status'],'running')
        self.event('task.result',dict(status='success',result={'spoken':True},error=None),cmd)
        self.assertEqual(sum(t['command']['command_type']=='speech.listen' for t in self.c.tasks.values()),1)
        self.assertEqual(list(Path(self.tmp.name).glob('*.tmp')),[])

    def test_create_failure_rolls_back_secret_and_cache(self):
        fresh = DurableCoordinator(self.tokens,Path(self.tmp.name)/'other')
        with patch.object(fresh,'_save',side_effect=OSError('blocked')):
            with self.assertRaises(ProtocolError):fresh.create_game('C',self.body,self.key)
        self.assertIsNone(fresh.state)
        self.assertIsNone(fresh.secret)
        self.assertEqual(fresh.creates,{})
        self.assertEqual(fresh.tasks,{})

    def test_queued_timeout_pauses_without_counting(self):
        self.now += 5.1
        expired = self.c.tick()
        self.assertEqual(len(expired),1)
        state = self.c.public()
        self.assertTrue(state['paused'])
        self.assertEqual(state['remaining_questions'],7)
        self.assertEqual(self.c.tasks[expired[0]]['executor_state'],'idle')

    def test_running_timeout_blocks_lane_until_late_terminal(self):
        cmd = self.start()
        self.now += 15.1
        self.c.tick()
        task = self.c.lookup('A',cmd['command_id'])
        self.assertEqual(task['status'],'expired')
        self.assertEqual(task['executor_state'],'unknown')
        self.assertTrue(task['cancel_requested'])
        self.assertIsNone(self.c.next('A','A','main')['command'])
        (result, replay), event = self.event('task.result',dict(status='success',result={'spoken':True},error=None),cmd)
        self.assertEqual(result['disposition'],'ignored_for_game')
        self.assertEqual(self.c.lookup('A',cmd['command_id'])['executor_state'],'idle')
        self.assertEqual(self.c.public()['remaining_questions'],7)
        self.assertTrue(self.c.event('A',event,self.instance)[1])
        self.assertEqual(self.c.next('A','A','main')['command']['command_type'],'speech.listen')

    def test_late_result_without_polling_cannot_advance(self):
        cmd = self.start()
        self.now += 16
        (result,_), _ = self.event('task.result',dict(status='success',result={'spoken':True},error=None),cmd)
        self.assertEqual(result['disposition'],'ignored_for_game')
        self.assertTrue(self.c.public()['paused'])

    def test_duplicate_start_cannot_extend_timeout(self):
        cmd = self.start()
        deadline = self.c.deadlines[cmd['command_id']]
        self.now += 2
        self.event('task.started',{},cmd)
        self.assertEqual(self.c.deadlines[cmd['command_id']],deadline)
        self.assertLess(self.c.lookup('A',cmd['command_id'])['remaining_ms'],15000)

    def test_accepted_start_deadline(self):
        cmd = self.c.next('A','A','main')['command']
        self.event('task.accepted',{},cmd)
        self.now += 3.1
        self.c.tick()
        self.assertEqual(self.c.lookup('A',cmd['command_id'])['executor_state'],'unknown')

    def test_timeout_journal_failure_does_not_publish_pause(self):
        self.now += 6
        with patch.object(self.c,'_save',side_effect=OSError('disk')):
            with self.assertRaises(ProtocolError):self.c.tick()
        self.assertFalse(self.c.public()['paused'])
        self.assertTrue(any(t['status']=='queued' and t['command']['target']=='A' for t in self.c.tasks.values()))

    def test_history_http_never_serves_private_snapshot(self):
        server = create_server(self.c,0)
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:'+str(server.server_port)
            gid = self.c.public()['game_id']
            with urlopen(base+'/api/v1/games?limit=20',timeout=2) as response:
                self.assertEqual(json.load(response)['data']['games'][0]['game_id'],gid)
            with urlopen(base+'/api/v1/games/'+gid+'/public',timeout=2) as response:
                text = response.read().decode()
                self.assertNotIn('secret',text)
                self.assertNotIn('decision_seed',text)
                self.assertNotIn('private-token',text)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_corrupt_store_fails_instead_of_resetting(self):
        self.c.path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError):DurableCoordinator(self.tokens,self.tmp.name)


class DurableGameFlowTests(game_tests.NetworkGameTests):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch('test_network_game.Coordinator', side_effect=lambda tokens: DurableCoordinator(tokens, temp.name)):
            super().setUp()
            prepare_robot_card(self.c)


if __name__=='__main__':unittest.main()
