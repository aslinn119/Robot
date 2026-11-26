import sys,json,unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request,urlopen
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from network_v1.transport import Transport,ProtocolError,create_server

class NetworkFoundationTests(unittest.TestCase):
    def setUp(self):
        self.t=Transport({r:'test-token-'+r for r in 'ABCD'})
        self.instance=uuid4().hex;self.gid=uuid4().hex;self.cid=uuid4().hex
        self.event('module.heartbeat',{'instance_id':self.instance,'module_status':'ready','active_command_ids':[],'capabilities':['speech.say'],'runtime_mode':'mock'},heartbeat=True)
        self.t.enqueue({'protocol_version':'1.0','command_id':self.cid,'game_id':self.gid,'input_epoch':0,'target':'A','command_type':'speech.say','timeout_ms':15000,'payload':{'text':'测试','purpose':'prompt','answer_id':None,'sync_group_id':None}})
    def envelope(self,kind,payload,heartbeat=False):
        return {'protocol_version':'1.0','request_id':uuid4().hex,'game_id':None if heartbeat else self.gid,'input_epoch':None if heartbeat else 0,'source':'A','command_id':None if heartbeat else self.cid,'event_type':kind,'payload':payload}
    def event(self,kind,payload,heartbeat=False):return self.t.event('A',self.envelope(kind,payload,heartbeat),self.instance)
    def test_health(self):self.assertEqual(self.t.health()['modules']['A'],'ready')
    def test_auth(self):
        self.assertEqual(self.t.authorize('Bearer test-token-A'),'A')
        with self.assertRaises(ProtocolError):self.t.authorize('Bearer invalid')
    def test_no_cross_role(self):
        with self.assertRaises(ProtocolError):self.t.lookup('B',self.cid)
    def test_task_flow(self):
        self.assertEqual(self.t.next('A','A','main')['command']['command_id'],self.cid)
        self.event('task.accepted',{});self.event('task.started',{})
        self.event('task.result',{'status':'success','result':{'spoken':True},'error':None})
        self.assertEqual(self.t.lookup('A',self.cid)['status'],'succeeded')
        self.assertIsNone(self.t.next('A','A','main')['command'])
    def test_request_deduplication(self):
        event=self.envelope('task.accepted',{})
        self.assertFalse(self.t.event('A',event,self.instance)[1])
        self.assertTrue(self.t.event('A',event,self.instance)[1])
        event['event_type']='task.started'
        with self.assertRaises(ProtocolError):self.t.event('A',event,self.instance)
    def test_result_conflict(self):
        self.event('task.accepted',{});self.event('task.started',{})
        self.event('task.result',{'status':'success','result':{'spoken':True},'error':None})
        with self.assertRaises(ProtocolError):self.event('task.result',{'status':'failed','result':None,'error':{'code':'TTS_FAILED','message':'失败'}})
    def test_stale_input(self):
        event=self.envelope('task.accepted',{});event['input_epoch']=1
        with self.assertRaises(ProtocolError):self.t.event('A',event,self.instance)
    def test_http_paths(self):
        server=create_server(self.t,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with urlopen(base+'/api/v1/health',timeout=2) as response:self.assertTrue(json.load(response)['ok'])
            req=Request(base+'/api/v1/modules/A/commands/next?lane=main&wait_ms=1000',headers={'Authorization':'Bearer test-token-A'})
            with urlopen(req,timeout=2) as response:self.assertEqual(json.load(response)['data']['command']['command_id'],self.cid)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
