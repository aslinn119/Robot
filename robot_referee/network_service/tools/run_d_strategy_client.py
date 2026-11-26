"""D strategy lane client; never fetches or executes motion commands."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from network_v1.d_strategy_adapter import decide
from vendor_d.team_strategy import replay_profile
from vendor_d.strategy import opening_questions


def main():
    parser=argparse.ArgumentParser(description='D pure strategy HTTP client (mock only)')
    parser.add_argument('--server',default='http://127.0.0.1:8780')
    args=parser.parse_args()
    token=os.environ.get('ROBAN_TOKEN_D','')
    if not token:parser.error('Set ROBAN_TOKEN_D to the referee D token.')
    instance=uuid.uuid4().hex
    def request(path,body=None):
        headers={'Authorization':'Bearer '+token,'X-Roban-Instance':instance,'Content-Type':'application/json'}
        for attempt in range(3):
            try:
                req=Request(args.server.rstrip('/')+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
                with urlopen(req,timeout=5) as response:return json.load(response)['data']
            except HTTPError as error:
                raise RuntimeError('HTTP %s: %s' % (error.code,error.read().decode())) from error
            except (URLError,TimeoutError):
                if attempt==2:raise
                time.sleep((0.3,0.9)[attempt])
    def event(kind,payload,cmd=None):
        body=dict(protocol_version='1.0',request_id=uuid.uuid4().hex,game_id=cmd['game_id'] if cmd else None,input_epoch=cmd['input_epoch'] if cmd else None,source='D',command_id=cmd['command_id'] if cmd else None,event_type=kind,payload=payload)
        return request('/api/v1/events',body)
    print('D strategy client ready; no motion execution.')
    last_heartbeat=0
    profiles={}
    try:
        while True:
            if time.monotonic()-last_heartbeat>=2:
                event('module.heartbeat',dict(instance_id=instance,module_status='ready',active_command_ids=[],capabilities=['strategy.decide'],runtime_mode='mock'))
                last_heartbeat=time.monotonic()
            cmd=request('/api/v1/modules/D/commands/next?lane=strategy&wait_ms=0')['command']
            if cmd is None:
                time.sleep(0.2)
                continue
            event('task.accepted',{},cmd)
            event('task.started',{},cmd)
            try:
                gid=cmd['game_id']
                if gid not in profiles:
                    summaries=request('/api/v1/games?limit=20')['games']
                    finished=[]
                    for row in reversed(summaries):
                        if row['phase']!='finished' or row['game_id']==gid:
                            continue
                        game=request('/api/v1/games/'+row['game_id']+'/public')['state']
                        if game.get('result',{}).get('outcome') not in ('guesser_win','hider_win'):
                            continue
                        if game['mode']=='player_hides' and game['history']:
                            first=game['history'][0]
                            if (first['comparison'],first['number']) not in opening_questions():
                                continue
                        finished.append(game)
                    profiles[gid]=replay_profile(finished)
                result=decide(cmd['payload'],game_id=gid,profile=profiles[gid])
                payload=dict(status='success',result=result,error=None)
            except (ValueError,KeyError,TypeError) as error:
                payload=dict(status='failed',result=None,error=dict(code='STRATEGY_UNAVAILABLE',message=str(error)))
            event('task.result',payload,cmd)
            print('Completed strategy command:',cmd['command_id'])
    except KeyboardInterrupt:
        print('D strategy client stopped.')


if __name__=='__main__':main()
