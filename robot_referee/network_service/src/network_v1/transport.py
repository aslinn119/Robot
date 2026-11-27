"""Protocol 1.0 task transport foundation; no robot hardware calls."""
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from datetime import datetime

OWNERS={'speech.say':('A','main'),'speech.listen':('A','main'),'vision.capture':('B','main'),'registration.confirm':('B','main'),'strategy.decide':('D','strategy'),'motion.execute':('D','motion')}
TERMINAL={'succeeded','failed','cancelled','expired'}

class ProtocolError(Exception):
    def __init__(self,status,code): self.status,self.code=status,code

class Transport:
    def __init__(self,tokens):
        if set(tokens)!={'A','B','C','D'} or len(set(tokens.values()))!=4 or not all(tokens.values()):
            raise ValueError('Four distinct nonempty role tokens are required')
        self.tokens=dict(tokens);self.instance=uuid.uuid4().hex
        self.lock=threading.RLock();self.tasks={};self.receipts={};self.modules={}
    def authorize(self,header):
        if not header.startswith('Bearer '):raise ProtocolError(401,'UNAUTHORIZED')
        for role,token in self.tokens.items():
            if secrets.compare_digest(header[7:],token):return role
        raise ProtocolError(401,'UNAUTHORIZED')
    def health(self):
        with self.lock:
            states={r:self.modules.get(r,{}).get('status','offline') for r in 'ABD'}
            for r in states:
                if time.monotonic()-self.modules.get(r,{}).get('seen',0)>6:states[r]='offline'
            return {'protocol_version':'1.0','service_status':'degraded','server_instance_id':self.instance,'modules':states}
    def enqueue(self,command):
        with self.lock:
            owner,lane=OWNERS[command['command_type']]
            if owner!=command['target']:raise ValueError('Invalid command owner')
            cid=command['command_id']
            if cid in self.tasks:
                if self.tasks[cid]['command']!=command:raise ValueError('Conflicting command')
                return
            self.tasks[cid]={'command':json.loads(json.dumps(command)),'status':'queued','cancel_requested':False,'remaining_ms':command['timeout_ms'],'executor_state':'idle','lane':lane}
    def next(self,role,module,lane):
        with self.lock:
            if role!=module:raise ProtocolError(403,'FORBIDDEN')
            if module not in 'ABD' or lane not in ({'strategy','motion'} if module=='D' else {'main'}):raise ProtocolError(400,'BAD_REQUEST')
            tasks=[t for t in self.tasks.values() if t['command']['target']==module and t['lane']==lane]
            if any(t['status'] in ('accepted','running') for t in tasks):return {'command':None}
            for t in tasks:
                if t['status']=='queued':return {'command':json.loads(json.dumps(t['command']))}
            return {'command':None}
    def lookup(self,role,cid):
        with self.lock:
            if cid not in self.tasks:raise ProtocolError(404,'NOT_FOUND')
            task=self.tasks[cid]
            if role not in (task['command']['target'],'C'):raise ProtocolError(403,'FORBIDDEN')
            return {k:json.loads(json.dumps(v)) for k,v in task.items() if k!='lane'}
    def event(self,role,event,instance):
        with self.lock:
            required={'protocol_version','request_id','game_id','input_epoch','source','command_id','event_type','payload'}
            if not isinstance(event,dict) or set(event)!=required or event['protocol_version']!='1.0':raise ProtocolError(400,'BAD_REQUEST')
            if event['source']!=role:raise ProtocolError(403,'FORBIDDEN')
            rid=event['request_id']
            if not isinstance(rid,str) or len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid):raise ProtocolError(400,'BAD_REQUEST')
            key=(role,rid);fingerprint=json.dumps(event,sort_keys=True,allow_nan=False)
            if key in self.receipts:
                old,result=self.receipts[key]
                if old!=fingerprint:raise ProtocolError(409,'REQUEST_CONFLICT')
                return result,True
            kind=event['event_type'];payload=event['payload']
            if kind=='module.heartbeat':
                if role not in 'ABD' or not isinstance(payload,dict) or payload.get('instance_id')!=instance or not instance:raise ProtocolError(400,'BAD_REQUEST')
                old=self.modules.get(role)
                if old and old['instance']!=instance:raise ProtocolError(409,'MODULE_CONFLICT')
                if any(event[k] is not None for k in ('game_id','input_epoch','command_id')):raise ProtocolError(400,'BAD_REQUEST')
                if payload.get('module_status') not in ('ready','busy','degraded','unknown'):raise ProtocolError(400,'BAD_REQUEST')
                self.modules[role]={'instance':instance,'seen':time.monotonic(),'status':payload['module_status']}
                result={'disposition':'recorded','command_status':None}
            elif kind in ('task.accepted','task.started','task.result'):
                if self.modules.get(role,{}).get('instance')!=instance:raise ProtocolError(409,'MODULE_CONFLICT')
                task=self.tasks.get(event['command_id'])
                if not task:raise ProtocolError(404,'NOT_FOUND')
                cmd=task['command']
                if cmd['target']!=role:raise ProtocolError(403,'FORBIDDEN')
                if event['game_id']!=cmd['game_id'] or type(event['input_epoch']) is not int or event['input_epoch']!=cmd['input_epoch']:raise ProtocolError(409,'STALE_INPUT')
                if kind in ('task.accepted','task.started') and payload!={}:raise ProtocolError(400,'BAD_REQUEST')
                if kind=='task.accepted':
                    if task['status'] not in ('queued','accepted'):raise ProtocolError(409,'COMMAND_NOT_RUNNABLE')
                    task['status']='accepted'
                elif kind=='task.started':
                    if task['status'] not in ('accepted','running'):raise ProtocolError(409,'COMMAND_NOT_RUNNABLE')
                    task['status']='running';task['executor_state']='busy'
                else:
                    if not isinstance(payload,dict) or set(payload)!={'status','result','error'}:raise ProtocolError(400,'BAD_REQUEST')
                    status=payload['status']
                    if status not in ('success','failed','cancelled'):raise ProtocolError(400,'BAD_REQUEST')
                    if status=='success' and (not isinstance(payload['result'],dict) or payload['error'] is not None):raise ProtocolError(400,'BAD_REQUEST')
                    if status!='success' and (payload['result'] is not None or not isinstance(payload['error'],dict)):raise ProtocolError(400,'BAD_REQUEST')
                    if 'result_payload' in task:
                        if task['result_payload']!=payload:raise ProtocolError(409,'RESULT_CONFLICT')
                    else:
                        if task['status'] not in ('accepted','running') and not (task['status']=='expired' and task['executor_state']=='unknown'):raise ProtocolError(409,'COMMAND_NOT_RUNNABLE')
                        task['result_payload']=json.loads(json.dumps(payload));task['status']={'success':'succeeded','failed':'failed','cancelled':'cancelled'}[status];task['executor_state']='idle'
                result={'disposition':'recorded','command_status':task['status']}
            else:raise ProtocolError(503,'SERVICE_UNAVAILABLE')
            self.receipts[key]=(fingerprint,result)
            return result,False

def create_server(transport,port=8780,host='127.0.0.1'):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_json(self,status,code,data=None,replayed=False):
            body=json.dumps({'ok':status<400,'code':code,'message':code,'replayed':replayed,'server_time':datetime.now().astimezone().isoformat(timespec='seconds'),'server_instance_id':transport.instance,'data':data or {}},ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            try:
                url=urlsplit(self.path)
                if url.path=='/api/v1/health':self.send_json(200,'OK',transport.health());return
                if url.path=='/api/v1/state/public' and hasattr(transport,'public'):
                    self.send_json(200,'OK',{'state':transport.public()});return
                parts=url.path.split('/')
                if url.path=='/api/v1/games' and hasattr(transport,'game_list'):
                    try: limit=int(parse_qs(url.query).get('limit',['20'])[0])
                    except ValueError: raise ProtocolError(400,'BAD_REQUEST')
                    self.send_json(200,'OK',{'games':transport.game_list(limit)});return
                if len(parts)==6 and parts[1:4]==['api','v1','games'] and parts[5]=='public' and hasattr(transport,'game_public'):
                    self.send_json(200,'OK',{'state':transport.game_public(parts[4])});return
                role=transport.authorize(self.headers.get('Authorization',''))
                if url.path=='/api/v1/operator/modules' and hasattr(transport,'operator_modules'):
                    self.send_json(200,'OK',transport.operator_modules(role));return
                if len(parts)==5 and parts[1:4]==['api','v1','evidence'] and hasattr(transport,'evidence_image'):
                    raw=transport.evidence_image(role,parts[4])
                    self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw);return
                if len(parts)==7 and parts[1:4]==['api','v1','modules'] and parts[5:]==['commands','next']:
                    q=parse_qs(url.query);module=parts[4];lane=q.get('lane',['main'])[0]
                    self.send_json(200,'OK',transport.next(role,module,lane));return
                if len(parts)==5 and parts[1:4]==['api','v1','commands']:
                    self.send_json(200,'OK',transport.lookup(role,parts[4]));return
                raise ProtocolError(503,'SERVICE_UNAVAILABLE')
            except ProtocolError as e:self.send_json(e.status,e.code)
        def do_POST(self):
            try:
                role=transport.authorize(self.headers.get('Authorization',''))
                size=int(self.headers.get('Content-Length','0'))
                if size<1:raise ProtocolError(400,'BAD_REQUEST')
                if size>(4*1024*1024 if self.path=='/api/v1/evidence' else 65536):raise ProtocolError(413,'PAYLOAD_TOO_LARGE')
                event=json.loads(self.rfile.read(size).decode('utf-8'))
                if self.path=='/api/v1/evidence' and hasattr(transport,'upload_evidence'):
                    result,replay=transport.upload_evidence(role,event,self.headers.get('Idempotency-Key',''))
                    self.send_json(200 if replay else 201,'OK',result,replay);return
                if self.path=='/api/v1/games' and hasattr(transport,'create_game'):
                    result,replay=transport.create_game(role,event,self.headers.get('Idempotency-Key',''))
                    self.send_json(200 if replay else 201,'OK',result,replay);return
                if self.path!='/api/v1/events':raise ProtocolError(503,'SERVICE_UNAVAILABLE')
                result,replay=transport.event(role,event,self.headers.get('X-Roban-Instance',''))
                self.send_json(200,'OK',result,replay)
            except ProtocolError as e:self.send_json(e.status,e.code)
            except (ValueError,TypeError,UnicodeError):self.send_json(400,'BAD_REQUEST')
    return ThreadingHTTPServer((host,port),Handler)
