import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from network_v1.managed import ManagedCoordinator
from network_v1.transport import ProtocolError,create_server
from threading import Thread
from urllib.request import Request,urlopen

CAPS={'A':['speech.say','speech.listen'],'B':['vision.capture','registration.confirm'],'D':['strategy.decide']}

class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=100.
        self.tokens={r:'test-'+r for r in 'ABCD'}
        self.c=ManagedCoordinator(self.tokens,self.temp.name,clock=lambda:self.now,enable_robot=True)
        self.ids={r:uuid4().hex for r in 'ABD'}
        for r in 'ABD':self.heartbeat(r)

    def envelope(self,role,kind,payload,cmd=None):
        return dict(protocol_version='1.0',request_id=uuid4().hex,game_id=cmd['game_id'] if cmd else None,input_epoch=cmd['input_epoch'] if cmd else None,source=role,command_id=cmd['command_id'] if cmd else None,event_type=kind,payload=payload)

    def heartbeat(self,role,mode=None,status='ready',caps=None,active=None):
        e=self.envelope(role,'module.heartbeat',dict(instance_id=self.ids[role],module_status=status,active_command_ids=active or [],capabilities=CAPS[role] if caps is None else caps,runtime_mode=mode or ('mock' if role=='D' else 'robot')))
        return self.c.event(role,e,self.ids[role])

    def create(self,mode='player_hides',runtime='robot'):
        return self.c.create_game('C',dict(protocol_version='1.0',mode=mode,runtime_mode=runtime),uuid4().hex)

    def reset(self,module='A',**changes):
        active=self.c.state and self.c.state['phase']!='finished'
        e=self.envelope('C','control.module_reset',dict(module=module,previous_instance_id=self.ids[module],confirmed_idle=True))
        if active:e.update(game_id=self.c.state['game_id'],input_epoch=self.c.state['input_epoch'])
        e.update(changes)
        return e

    def expired(self):
        self.now+=7
        self.c.tick()

    def assert_code(self,code,call):
        with self.assertRaises(ProtocolError) as caught:call()
        self.assertEqual(caught.exception.code,code)

    def test_robot_both_modes_and_real_label(self):
        for mode in ('player_hides','robot_hides'):
            with self.subTest(mode=mode):
                response,_=self.create(mode)
                self.assertEqual(response['state']['runtime_mode'],'robot')
                self.assertEqual(response['state']['phase'],'waiting_strategy' if mode=='player_hides' else 'registration_capture')
                self.c.state=None
                self.c.tasks={}

    def test_robot_flag_required(self):
        self.c.allow_robot=False
        self.assert_code('ROBOT_MODE_DISABLED',lambda:self.create())

    def test_robot_a_and_b_cannot_be_mock(self):
        for role in 'AB':
            self.heartbeat(role,mode='mock')
            self.assert_code('RUNTIME_MODE_MISMATCH',lambda:self.create())
            self.heartbeat(role)

    def test_missing_capability(self):
        self.heartbeat('B',caps=['vision.capture'])
        self.assert_code('CAPABILITY_UNAVAILABLE',lambda:self.create())

    def test_busy_degraded_unknown_rejected(self):
        for status in ('busy','degraded','unknown'):
            self.heartbeat('A',status=status)
            self.assert_code('MODULE_NOT_READY',lambda:self.create())

    def test_stale_heartbeat_rejected(self):
        self.expired()
        self.assert_code('MODULE_OFFLINE',lambda:self.create())

    def test_mock_d_with_motion_not_accepted_for_robot(self):
        self.heartbeat('D',caps=['strategy.decide','motion.execute'])
        self.assert_code('RUNTIME_MODE_MISMATCH',lambda:self.create())

    def test_query_c_only_includes_binding(self):
        response=self.c.operator_modules('C')
        self.assertEqual(response['modules']['A']['instance_id'],self.ids['A'])
        self.assertFalse(response['motion_enabled'])
        self.assert_code('FORBIDDEN',lambda:self.c.operator_modules('A'))

    def test_bad_heartbeat_not_recorded(self):
        e=self.envelope('A','module.heartbeat',dict(instance_id=self.ids['A'],module_status='ready',active_command_ids=[],capabilities=['vision.capture'],runtime_mode='robot'))
        before=copy.deepcopy(self.c.modules)
        self.assert_code('BAD_REQUEST',lambda:self.c.event('A',e,self.ids['A']))
        self.assertEqual(before,self.c.modules)

    def test_reset_without_game_and_new_instance(self):
        self.expired()
        e=self.reset()
        result,replay=self.c.event('C',e,'')
        self.assertEqual(result,dict(disposition='applied',command_status=None));self.assertFalse(replay)
        self.assertNotIn('A',self.c.modules)
        old=self.ids['A'];self.ids['A']=uuid4().hex
        self.heartbeat('A')
        self.assertEqual(self.c.modules['A']['instance'],self.ids['A'])
        self.ids['A']=old
        self.assert_code('INSTANCE_RETIRED',lambda:self.heartbeat('A'))

    def test_reset_online_rejected(self):
        self.assert_code('MODULE_STILL_ONLINE',lambda:self.c.event('C',self.reset(),''))

    def test_reset_requires_explicit_true(self):
        self.expired()
        for value in (False,1,'true',None):
            e=self.reset();e['payload']['confirmed_idle']=value
            self.assert_code('IDLE_CONFIRMATION_REQUIRED',lambda:self.c.event('C',e,''))

    def test_wrong_old_instance(self):
        self.expired();e=self.reset();e['payload']['previous_instance_id']=uuid4().hex
        self.assert_code('INSTANCE_MISMATCH',lambda:self.c.event('C',e,''))

    def test_reset_a_cannot_impersonate_c(self):
        e=self.reset();e['source']='A'
        self.assert_code('FORBIDDEN',lambda:self.c.event('A',e,self.ids['A']))

    def test_reset_missing_extra_fields(self):
        self.expired()
        e=self.reset();del e['payload']['module']
        self.assert_code('BAD_REQUEST',lambda:self.c.event('C',e,''))
        e=self.reset();e['payload']['extra']=True
        self.assert_code('BAD_REQUEST',lambda:self.c.event('C',e,''))

    def test_reset_idempotence_and_conflict(self):
        self.expired();e=self.reset()
        self.c.event('C',e,'')
        self.assertTrue(self.c.event('C',e,'')[1])
        self.assertEqual(len(self.c.reset_audit),1)
        e['payload']['module']='B'
        self.assert_code('REQUEST_CONFLICT',lambda:self.c.event('C',e,''))

    def test_reset_disk_failure_rolls_back_everything(self):
        self.expired();e=self.reset();before=self.c.path.read_bytes()
        with patch('network_v1.durable.os.replace',side_effect=OSError('disk')):
            self.assert_code('JOURNAL_UNAVAILABLE',lambda:self.c.event('C',e,''))
        self.assertIn('A',self.c.modules);self.assertEqual(self.c.retired_instances,{})
        self.assertEqual(before,self.c.path.read_bytes())
        self.c.event('C',e,'')
        self.assertEqual(len(self.c.reset_audit),1)

    def test_retired_ids_and_reset_receipt_survive_restart(self):
        self.expired();e=self.reset();self.c.event('C',e,'')
        self.c=ManagedCoordinator(self.tokens,self.temp.name,clock=lambda:self.now)
        self.assertTrue(self.c.event('C',e,'')[1])
        self.assert_code('INSTANCE_RETIRED',lambda:self.heartbeat('A'))

    def test_old_running_task_never_transfers_or_advances(self):
        self.create()
        cmd=self.c.next('A','A','main')['command']
        for kind in ('task.accepted','task.started'):
            self.c.event('A',self.envelope('A',kind,{},cmd),self.ids['A'])
        before_history=copy.deepcopy(self.c.state['history'])
        self.expired()
        e=self.reset();self.c.event('C',e,'')
        task=self.c.tasks[cmd['command_id']]
        self.assertEqual(task['status'],'cancelled');self.assertEqual(task['executor_state'],'idle')
        self.assertNotIn('result_payload',task)
        old=self.ids['A'];self.ids['A']=uuid4().hex;self.heartbeat('A')
        e=self.envelope('A','task.result',dict(status='success',result={'spoken':True},error=None),cmd)
        self.assert_code('INSTANCE_RETIRED',lambda:self.c.event('A',e,old))
        self.assert_code('COMMAND_NOT_RUNNABLE',lambda:self.c.event('A',e,self.ids['A']))
        self.assertEqual(self.c.state['history'],before_history)
        self.assertEqual(self.c.state['remaining_questions'],7)
        self.assertTrue(self.c.state['paused'])

    def test_no_motion_is_enqueued(self):
        self.create(runtime='mock')
        # Construct an answer speech in the active mock game, then start it.
        for t in self.c.tasks.values():t['status']='cancelled'
        self.c.last_answer=dict(answer=True,text='yes')
        self.c.say('yes','answer','listen',uuid4().hex)
        cmd=self.c.next('A','A','main')['command']
        for kind in ('task.accepted','task.started'):
            self.c.event('A',self.envelope('A',kind,{},cmd),self.ids['A'])
        self.assertFalse(any(t['command']['command_type']=='motion.execute' for t in self.c.tasks.values()))

    def test_mode_change_in_game_rejected(self):
        self.create()
        self.assert_code('MODULE_CONFIG_CHANGED',lambda:self.heartbeat('A',mode='mock'))

    def test_late_speech_finishes_without_advancing_cancelled_window(self):
        self.create()
        cmd=self.c.next('A','A','main')['command']
        for kind in ('task.accepted','task.started'):
            self.c.event('A',self.envelope('A',kind,{},cmd),self.ids['A'])
        state=self.c.public()
        pause=self.envelope('C','control.pause',{})
        pause.update(game_id=state['game_id'],input_epoch=state['input_epoch'])
        self.c.event('C',pause,'')
        self.assertIsNone(self.c.next('A','A','main')['command'])
        self.assert_code('EXECUTOR_NOT_IDLE',lambda:self.c.control('resume'))
        result,_=self.c.event('A',self.envelope('A','task.result',dict(status='success',result={'spoken':True},error=None),cmd),self.ids['A'])
        self.assertEqual(result['disposition'],'ignored_for_game')
        self.assertTrue(self.c.state['paused'])
        self.assertEqual(self.c.state['remaining_questions'],7)
        next_cmd=self.c.next('A','A','main')['command']
        self.assertEqual(next_cmd['payload']['allowed_intents'],['resume','exit','help'])

    def test_robot_create_retry_survives_offline(self):
        key=uuid4().hex;body=dict(protocol_version='1.0',mode='player_hides',runtime_mode='robot')
        response,_=self.c.create_game('C',body,key)
        self.expired()
        old,replay=self.c.create_game('C',body,key)
        self.assertTrue(replay);self.assertEqual(old,response)

    def test_http_operator_and_reset(self):
        self.expired();e=self.reset()
        server=create_server(self.c,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            req=Request(base+'/api/v1/operator/modules',headers={'Authorization':'Bearer test-C'})
            with urlopen(req,timeout=3) as response:self.assertEqual(json.load(response)['data']['modules']['A']['instance_id'],self.ids['A'])
            req=Request(base+'/api/v1/events',data=json.dumps(e).encode(),headers={'Authorization':'Bearer test-C','Content-Type':'application/json'})
            with urlopen(req,timeout=3) as response:self.assertEqual(response.status,200)
        finally:server.shutdown();server.server_close();thread.join()

    def test_both_robot_flows_with_simulated_device_receipts(self):
        import test_network_player as fixtures
        for mode in ('player_hides','robot_hides'):
            with self.subTest(mode=mode):
                f=fixtures.PlayerNetworkTests('runTest');f.setUp()
                try:
                    f.c=self.c
                    f.instances=self.ids
                    self.create(mode)
                    if mode=='player_hides':
                        f.prompt();f.question(True);f.final();f.reveal()
                    else:
                        f.capture(7)
                        cmd=f.take('B')
                        f.done(cmd,dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=True))
                        f.prompt()
                        def utter(intent,number=None,comparison=None):
                            cmd=f.take();p=cmd['payload']
                            f.done(cmd,dict(intent=intent,number=number,comparison=comparison,answer=None,pending_id=p['pending_id'],pending_version=p['pending_version'],question_id=p['question_id'],utterance='simulated robot-mode device',parser='rule',reason=None))
                        utter('question',5,'gt');f.prompt();utter('confirm')
                        cmd=f.take('D','strategy')
                        f.done(cmd,dict(decision='answer',comparison=None,number=None,answer=True,lie_applied=False,candidates=[],certainty='not_final'))
                        f.prompt();utter('final_submit',7);f.prompt();utter('confirm')
                    self.assertEqual(self.c.public()['runtime_mode'],'robot')
                    self.assertEqual(self.c.public()['result']['outcome'],'guesser_win')
                    self.assertFalse(any(t['command']['command_type']=='motion.execute' for t in self.c.tasks.values()))
                    self.c.state=None;self.c.tasks={}
                finally:f.doCleanups()

if __name__=='__main__':unittest.main()
