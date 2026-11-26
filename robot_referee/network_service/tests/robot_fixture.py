"""Initialize a real-card robot-hides fixture without exposing it to A."""
import base64, io
from uuid import uuid4
from PIL import Image

def prepare_robot_card(c, value=7):
    instance=uuid4().hex
    def send(kind,payload,cmd=None):
        return c.event('B',dict(protocol_version='1.0',request_id=uuid4().hex,source='B',event_type=kind,payload=payload,game_id=cmd['game_id'] if cmd else None,input_epoch=cmd['input_epoch'] if cmd else None,command_id=cmd['command_id'] if cmd else None),instance)
    send('module.heartbeat',dict(instance_id=instance,module_status='ready',active_command_ids=[],capabilities=['vision.capture','registration.confirm'],runtime_mode='mock'))
    def take():
        cmd=c.next('B','B','main')['command']
        send('task.accepted',{},cmd);send('task.started',{},cmd)
        return cmd
    cmd=take()
    stream=io.BytesIO();Image.new('RGB',(16,16),'white').save(stream,'JPEG')
    e,_=c.upload_evidence('B',dict(protocol_version='1.0',game_id=cmd['game_id'],command_id=cmd['command_id'],input_epoch=cmd['input_epoch'],mime_type='image/jpeg',image_base64=base64.b64encode(stream.getvalue()).decode()),uuid4().hex)
    send('task.result',dict(status='success',error=None,result=dict(purpose='registration',value=value,marker_id=value-1,consistent_frames=3,frame_seq=1,captured_at='2026-11-26T10:00:00+08:00',evidence_id=e['evidence_id'])),cmd)
    cmd=take()
    send('task.result',dict(status='success',error=None,result=dict(candidate_id=cmd['payload']['candidate_id'],candidate_version=cmd['payload']['candidate_version'],confirmed=True)),cmd)
