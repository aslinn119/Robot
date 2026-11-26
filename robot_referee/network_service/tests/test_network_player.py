import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from PIL import Image
from threading import Thread
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from network_v1.durable import DurableCoordinator
from network_v1.transport import ProtocolError,create_server


class PlayerNetworkTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.c=DurableCoordinator({r:'test-'+r for r in 'ABCD'},temp.name)
        self.instances={r:uuid4().hex for r in 'ABD'}
        for role in 'ABD':
            self.send(role,'module.heartbeat',dict(instance_id=self.instances[role],module_status='ready',active_command_ids=[],capabilities=[],runtime_mode='mock'))
        self.c.create_game('C',dict(protocol_version='1.0',mode='player_hides',runtime_mode='mock'),uuid4().hex)
        stream=io.BytesIO()
        Image.new('RGB',(16,16),'white').save(stream,format='JPEG')
        self.jpeg=stream.getvalue()

    def send(self,role,kind,payload,cmd=None):
        event=dict(protocol_version='1.0',request_id=uuid4().hex,source=role,event_type=kind,payload=payload,game_id=cmd['game_id'] if cmd else None,input_epoch=cmd['input_epoch'] if cmd else None,command_id=cmd['command_id'] if cmd else None)
        return self.c.event(role,event,self.instances[role]),event

    def take(self,role='A',lane='main'):
        cmd=self.c.next(role,role,lane)['command']
        self.assertIsNotNone(cmd)
        self.send(role,'task.accepted',{},cmd)
        self.send(role,'task.started',{},cmd)
        return cmd

    def done(self,cmd,result):
        return self.send(cmd['target'],'task.result',dict(status='success',result=result,error=None),cmd)

    def prompt(self):
        cmd=self.take()
        self.assertEqual(cmd['command_type'],'speech.say')
        self.done(cmd,{'spoken':True})
        return cmd

    def utter(self,intent,answer=None):
        cmd=self.take()
        p=cmd['payload']
        return self.done(cmd,dict(intent=intent,comparison=None,number=None,answer=answer,pending_id=p['pending_id'],pending_version=p['pending_version'],question_id=p['question_id'],utterance='测试',parser='manual_mock',reason=None))

    def capture(self,value):
        cmd=self.take('B')
        body=dict(protocol_version='1.0',game_id=cmd['game_id'],command_id=cmd['command_id'],input_epoch=cmd['input_epoch'],mime_type='image/jpeg',image_base64=base64.b64encode(self.jpeg).decode())
        evidence,_=self.c.upload_evidence('B',body,uuid4().hex)
        self.done(cmd,dict(purpose=cmd['payload']['purpose'],value=value,marker_id=value-1,consistent_frames=3,frame_seq=1,captured_at='2026-11-26T10:00:00+08:00',evidence_id=evidence['evidence_id']))
        return cmd,body,evidence

    def register(self):
        self.prompt()

    def new_robot_game(self):
        self.c.state=None
        self.c.tasks={}
        self.c.create_game('C',dict(protocol_version='1.0',mode='robot_hides',runtime_mode='mock'),uuid4().hex)

    def strategy(self,decision='question',number=5):
        cmd=self.take('D','strategy')
        self.assertNotIn('secret',cmd['payload'])
        candidates=self.c.candidates()
        self.done(cmd,dict(decision=decision,comparison='gt' if decision=='question' else None,number=number,answer=None,lie_applied=None,candidates=candidates,certainty='not_final' if decision=='question' else ('unique' if len(candidates)==1 else 'guess')))
        return cmd

    def question(self,answer):
        self.strategy()
        self.prompt()
        self.utter('answer',answer)
        self.prompt()
        return self.utter('confirm')

    def final(self):
        self.strategy('final_submit',7)
        self.prompt()
        self.utter('confirm')

    def reveal(self,value=7):
        self.capture(value)
        self.prompt()
        self.utter('confirm')

    def test_full_truthful_game(self):
        self.register()
        self.question(True)
        self.final()
        self.reveal()
        result=self.c.public()['result']
        self.assertEqual(result['outcome'],'guesser_win')
        self.assertEqual(result['lie_count'],0)

    def test_one_lie_allowed(self):
        self.register();self.question(False);self.final();self.reveal()
        self.assertEqual(self.c.public()['result']['lie_rounds'],[1])
        self.assertEqual(self.c.public()['result']['outcome'],'guesser_win')

    def test_two_lies_invalid(self):
        self.register();self.question(False);self.question(False)
        # D cannot know registered 7 is now inconsistent; choose a legal candidate.
        candidate=self.c.candidates()[0]
        self.strategy('final_submit',candidate)
        self.prompt();self.utter('confirm');self.reveal()
        self.assertEqual(self.c.public()['result']['reason_code'],'EXCESS_LIES')

    def test_registration_private_and_strategy_sanitized(self):
        self.new_robot_game()
        self.capture(7)
        state=self.c.public()
        self.assertIsNone(state['pending'])
        self.assertIsNone(state['result'])
        self.assertNotIn('evidence_id',json.dumps(state))
        self.assertEqual(self.c.next('A','A','main'),{'command':None})
        cmd=self.take('B')
        self.done(cmd,dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=True))
        speech=self.prompt()
        self.assertNotIn('7',speech['payload']['text'])
        self.assertEqual(self.c.secret,7)
        self.assertEqual(self.c.public()['phase'],'waiting_question')

    def test_answer_count_and_duplicate(self):
        self.register();self.strategy();self.prompt();self.utter('answer',True)
        self.assertEqual(self.c.public()['remaining_questions'],7)
        self.prompt()
        (_, _),event=self.utter('confirm')
        self.c.event('A',event,self.instances['A'])
        self.assertEqual(self.c.public()['remaining_questions'],6)
        self.assertEqual(len(self.c.public()['history']),1)

    def test_cancel_answer_no_count(self):
        self.register();self.strategy();self.prompt();self.utter('answer',False);self.prompt();self.utter('cancel')
        self.assertEqual(self.c.public()['remaining_questions'],7)
        self.assertEqual(self.c.public()['phase'],'waiting_answer')

    def test_first_reveal_is_truth_source(self):
        self.register();self.final();self.reveal(8)
        self.assertEqual(self.c.public()['result']['outcome'],'hider_win')
        self.assertEqual(self.c.public()['result']['revealed_number'],8)

    def test_cancel_reveal_recaptures_before_judging(self):
        self.register();self.final();self.capture(8);self.prompt();self.utter('cancel')
        self.assertIsNone(self.c.secret)
        self.reveal(7)
        self.assertEqual(self.c.public()['result']['outcome'],'guesser_win')

    def test_rejected_registration_recaptures(self):
        self.new_robot_game()
        self.capture(7)
        cmd=self.take('B')
        self.done(cmd,dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=False))
        self.assertIsNone(self.c.secret)
        self.assertEqual(self.c.public()['phase'],'registration_capture')

    def test_wrong_candidate_id_does_not_lock(self):
        self.new_robot_game()
        self.capture(7);cmd=self.take('B')
        with self.assertRaises(ProtocolError):self.done(cmd,dict(candidate_id=uuid4().hex,candidate_version=cmd['payload']['candidate_version'],confirmed=True))
        self.assertIsNone(self.c.secret)
        self.assertEqual(self.c.lookup('B',cmd['command_id'])['status'],'running')

    def test_fake_jpeg_rejected(self):
        self.new_robot_game()
        cmd=self.take('B')
        body=dict(protocol_version='1.0',game_id=cmd['game_id'],command_id=cmd['command_id'],input_epoch=cmd['input_epoch'],mime_type='image/jpeg',image_base64=base64.b64encode(b'not an image').decode())
        with self.assertRaises(ProtocolError):self.c.upload_evidence('B',body,uuid4().hex)
        self.assertEqual(self.c.evidence,{})

    def control(self, action):
        s=self.c.public()
        e=dict(protocol_version='1.0',request_id=uuid4().hex,game_id=s['game_id'],input_epoch=s['input_epoch'],source='C',command_id=None,event_type='control.'+action,payload={})
        return self.c.event('C',e,'')

    def test_pause_registration_resume_private_only(self):
        self.new_robot_game()
        self.capture(7)
        old=self.c.candidate['id']
        self.control('pause');self.control('resume')
        self.assertNotEqual(old,self.c.candidate['id'])
        self.assertIsNone(self.c.next('A','A','main')['command'])
        self.assertEqual(self.take('B')['command_type'],'registration.confirm')

    def test_paused_exit_can_confirm_without_reveal(self):
        self.control('pause')
        self.utter('exit');self.prompt();self.utter('confirm')
        self.assertEqual(self.c.public()['result']['reason_code'],'UNVERIFIED')
        self.assertIsNone(self.c.public()['result']['revealed_number'])

    def test_cancel_exit_restores_answer_pending(self):
        self.register();self.strategy();self.prompt();self.utter('answer',True);self.prompt()
        original=self.c.public()['pending']
        self.utter('exit');self.prompt();self.utter('cancel')
        self.assertEqual(self.c.public()['pending'],original)
        self.prompt();self.utter('confirm')
        self.assertEqual(self.c.public()['remaining_questions'],6)

    def test_evidence_idempotence_and_permissions(self):
        self.new_robot_game()
        cmd=self.take('B')
        body=dict(protocol_version='1.0',game_id=cmd['game_id'],command_id=cmd['command_id'],input_epoch=cmd['input_epoch'],mime_type='image/jpeg',image_base64=base64.b64encode(self.jpeg).decode())
        key=uuid4().hex
        a,_=self.c.upload_evidence('B',body,key)
        b,replay=self.c.upload_evidence('B',body,key)
        self.assertEqual(a,b);self.assertTrue(replay)
        self.assertEqual(self.c.evidence_image('B',a['evidence_id']),self.jpeg)
        with self.assertRaises(ProtocolError):self.c.evidence_image('D',a['evidence_id'])

    def test_http_evidence_and_complete_game(self):
        server=create_server(self.c,0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        original=self.c.upload_evidence
        # Exercise actual HTTP upload/download while the game follows normal tasks.
        def upload(role,body,key):
            self.c.upload_evidence=original
            try:
                req=Request(base+'/api/v1/evidence',data=json.dumps(body).encode(),headers={'Authorization':'Bearer test-B','Idempotency-Key':key,'Content-Type':'application/json'})
                with urlopen(req,timeout=3) as response:result=json.load(response)
                eid=result['data']['evidence_id']
                req=Request(base+'/api/v1/evidence/'+eid,headers={'Authorization':'Bearer test-C'})
                with urlopen(req,timeout=3) as response:
                    self.assertEqual(response.headers['Content-Type'],'image/jpeg')
                    self.assertEqual(response.read(),self.jpeg)
                return result['data'],result['replayed']
            finally:self.c.upload_evidence=upload
        self.c.upload_evidence=upload
        try:self.test_full_truthful_game()
        finally:
            self.c.upload_evidence=original
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
