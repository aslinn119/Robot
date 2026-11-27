"""C-only operator client. Never infer hardware idle from heartbeat loss."""
import argparse,json,os,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError

def main():
    parser=argparse.ArgumentParser(description='Inspect/reset module bindings as C operator')
    parser.add_argument('--server',default='http://127.0.0.1:8780')
    sub=parser.add_subparsers(dest='operation',required=True)
    sub.add_parser('list')
    reset=sub.add_parser('reset')
    reset.add_argument('--module',choices=['A','B','D'],required=True)
    reset.add_argument('--previous-instance-id',required=True)
    reset.add_argument('--confirmed-idle',action='store_true',required=True,help='Only after manually stopping old process and checking device idle')
    reset.add_argument('--request-id',default=None,help='Reuse on retry to preserve idempotence')
    args=parser.parse_args()
    token=os.environ.get('ROBAN_TOKEN_C','')
    if not token:parser.error('Set ROBAN_TOKEN_C; never put the token in command arguments.')
    def call(path,body=None):
        req=Request(args.server.rstrip('/')+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=5) as response:return json.load(response)
        except HTTPError as error:
            print(error.read().decode());raise SystemExit(1)
    if args.operation=='list':print(json.dumps(call('/api/v1/operator/modules'),ensure_ascii=False,indent=2));return
    rid=args.request_id or uuid.uuid4().hex
    if len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid):parser.error('request-id must be 32 lowercase hex characters')
    path=Path(__file__).resolve().parents[1]/'runtime'/'operator_requests'/(rid+'.json')
    if args.request_id:
        if not path.exists():parser.error('Retry request not found; omit --request-id for a new operation')
        body=json.loads(path.read_text(encoding='utf-8'))
        if body['payload']!=dict(module=args.module,previous_instance_id=args.previous_instance_id,confirmed_idle=True):parser.error('Retry parameters differ from saved request')
    else:
        state=call('/api/v1/state/public')['data']['state']
        active=state and state['phase']!='finished'
        body=dict(protocol_version='1.0',request_id=rid,source='C',event_type='control.module_reset',game_id=state['game_id'] if active else None,input_epoch=state['input_epoch'] if active else None,command_id=None,payload=dict(module=args.module,previous_instance_id=args.previous_instance_id,confirmed_idle=True))
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(body,indent=2),encoding='utf-8')
    print('Request ID:',rid)
    print(json.dumps(call('/api/v1/events',body),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
