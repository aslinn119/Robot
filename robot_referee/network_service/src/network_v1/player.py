"""Player-hides orchestration and private JPEG evidence handling."""
import base64
import copy
import hashlib
import io
import warnings
from datetime import datetime
from PIL import Image
from .coordinator import Coordinator, uid
from .transport import ProtocolError


class GameCoordinator(Coordinator):
    def __init__(self, tokens):
        super().__init__(tokens)
        self.candidate = None
        self.mismatch_count = 0
        self.capture_attempt = 0
        self.evidence = {}
        self.evidence_requests = {}
        self.exit_context = None

    def create_game(self, role, body, key):
        if not isinstance(body, dict) or body.get('mode') not in ('player_hides','robot_hides'):
            return super().create_game(role, body, key)
        if role != 'C':
            raise ProtocolError(403, 'FORBIDDEN')
        if key in self.creates:
            original, response = self.creates[key]
            if original != body:
                raise ProtocolError(409, 'REQUEST_CONFLICT')
            return copy.deepcopy(response), True
        translated = dict(body, mode='robot_hides')
        super().create_game(role, translated, key)
        self.secret = None
        self.candidate = None
        self.mismatch_count = self.capture_attempt = 0
        self.exit_context = None
        for task in self.tasks.values():
            if task['status'] == 'queued':
                task['status'] = 'cancelled'
        self.state.update(mode=body['mode'])
        if body['mode'] == 'player_hides':
            self.state['phase'] = 'waiting_strategy'
            self.say('请藏好卡牌，不要让我看到牌面。现在开始猜牌。', 'prompt', 'strategy')
        else:
            self.state['phase'] = 'registration_capture'
            self.capture('registration')
        response = {'state': self.public()}
        self.creates[key] = (copy.deepcopy(body), copy.deepcopy(response))
        return response, False

    def command(self, kind, payload):
        if kind not in ('vision.capture', 'registration.confirm'):
            return super().command(kind, payload)
        command = dict(protocol_version='1.0', command_id=uid(), game_id=self.state['game_id'], input_epoch=self.state['input_epoch'], target='B', command_type=kind, timeout_ms=30000 if kind == 'registration.confirm' else 5000, payload=payload)
        self.enqueue(command)
        return command['command_id']

    def capture(self, purpose):
        self.capture_attempt += 1
        self.candidate = None
        self.state.update(phase='registration_capture' if purpose == 'registration' else 'reveal_capture', pending=None)
        self.command('vision.capture', dict(purpose=purpose, camera_topic='/camera/color/image_raw', dictionary='DICT_4X4_50', min_consistent_frames=3, min_marker_side_px=25, attempt=self.capture_attempt))

    def private_confirm(self):
        c = self.candidate
        self.command('registration.confirm', dict(candidate_id=c['id'], candidate_version=c['version'], value=c['value'], evidence_id=c['evidence_id']))

    def listen(self):
        s = self.state
        if not s or s['mode'] != 'player_hides':
            return super().listen()
        p = s['pending']
        if p and p['kind'] == 'exit':
            allowed = ['confirm', 'cancel', 'help']
        elif s['paused']:
            allowed = ['resume', 'exit', 'help']
        elif p:
            allowed = ['confirm', 'cancel', 'pause', 'exit', 'help']
        elif s['phase'] == 'waiting_answer':
            allowed = ['answer', 'pause', 'exit', 'help', 'repeat_last']
        else:
            raise ProtocolError(409, 'INVALID_PHASE')
        question = s['locked_question']
        self.command('speech.listen', dict(allowed_intents=allowed, pending_id=p['pending_id'] if p else None, pending_version=p['pending_version'] if p else None, question_id=question['question_id'] if question else None, max_listen_ms=15000))

    def strategy(self):
        if self.state['mode'] != 'player_hides':
            return super().strategy()
        self.state['phase'] = 'waiting_strategy'
        self.command('strategy.decide', dict(purpose='guess_next', mode='player_hides', history=self.state['history'], remaining_questions=self.state['remaining_questions'], max_lies=1))

    def candidates(self):
        def truth(value, question):
            return {'gt':value > question['number'], 'lt':value < question['number'], 'eq':value == question['number']}[question['comparison']]
        return [n for n in range(1, 11) if sum(truth(n, q) != q['answer'] for q in self.state['history']) <= 1]

    def apply_result(self, cmd, r):
        if self.state['mode'] != 'player_hides' and cmd['command_type'] not in ('vision.capture','registration.confirm'):
            return super().apply_result(cmd, r)
        kind = cmd['command_type']
        if kind == 'speech.say':
            if set(r) != {'spoken'} or r['spoken'] is not True:
                raise ProtocolError(400, 'BAD_RESULT')
            after = self.after_say.get(cmd['command_id'])
            if after == 'strategy':
                self.strategy()
            elif after == 'listen':
                self.listen()
        elif kind == 'vision.capture':
            self.capture_result(cmd, r)
        elif kind == 'registration.confirm':
            c = self.candidate
            if not c or set(r) != {'candidate_id', 'candidate_version', 'confirmed'} or r['candidate_id'] != c['id'] or type(r['candidate_version']) is not int or r['candidate_version'] != c['version'] or type(r['confirmed']) is not bool:
                raise ProtocolError(400, 'BAD_RESULT')
            if not r['confirmed']:
                self.capture('registration')
            else:
                self.secret = c['value']
                self.candidate = None
                self.state.update(pending=None, phase='waiting_question')
                self.say('我已经记住卡牌，请收好牌，现在可以提问。', 'prompt', 'listen')
        elif kind == 'strategy.decide':
            self.guess_result(r)
        elif kind == 'speech.listen':
            self.player_input(cmd['payload'], r)
        else:
            super().apply_result(cmd, r)

    def capture_result(self, cmd, r):
        fields = {'purpose','value','marker_id','consistent_frames','frame_seq','captured_at','evidence_id'}
        if set(r) != fields or r['purpose'] != cmd['payload']['purpose'] or type(r['value']) is not int or not 1 <= r['value'] <= 10 or type(r['marker_id']) is not int or r['marker_id'] != r['value']-1 or type(r['consistent_frames']) is not int or r['consistent_frames'] < 3 or type(r['frame_seq']) is not int or r['frame_seq'] < 0:
            raise ProtocolError(400, 'BAD_RESULT')
        try:
            stamp = datetime.fromisoformat(r['captured_at'])
            if stamp.tzinfo is None:
                raise ValueError()
        except (TypeError, ValueError):
            raise ProtocolError(400, 'BAD_RESULT')
        evidence = self.evidence.get(r['evidence_id'])
        if not evidence or evidence['command_id'] != cmd['command_id'] or evidence['game_id'] != cmd['game_id']:
            raise ProtocolError(409, 'EVIDENCE_REQUIRED')
        self.candidate = dict(id=uid(), version=self.capture_attempt, value=r['value'], evidence_id=r['evidence_id'])
        if r['purpose'] == 'registration':
            self.state['phase'] = 'registration_confirm'
            self.private_confirm()
        else:
            self.pending('reveal', number=r['value'])
            self.state['phase'] = 'reveal_confirm'
            self.say('揭牌数字是%s，请确认或取消重新采集。' % r['value'], 'confirmation', 'listen')

    def pending(self, kind, number=None, answer=None):
        self.state['pending'] = dict(pending_id=uid(), pending_version=1, kind=kind, comparison=None, number=number, answer=answer)

    def guess_result(self, r):
        fields = {'decision','comparison','number','answer','lie_applied','candidates','certainty'}
        if self.state['phase'] != 'waiting_strategy' or set(r) != fields or r['answer'] is not None or r['lie_applied'] is not None or type(r['number']) is not int or not 1 <= r['number'] <= 10 or not isinstance(r['candidates'], list) or any(type(n) is not int for n in r['candidates']) or r['candidates'] != self.candidates():
            raise ProtocolError(400, 'BAD_RESULT')
        if r['decision'] == 'question':
            if self.state['remaining_questions'] < 1 or r['comparison'] not in ('gt','lt','eq') or r['certainty'] != 'not_final':
                raise ProtocolError(409, 'INVALID_STRATEGY')
            self.state['locked_question'] = dict(question_id=uid(), comparison=r['comparison'], number=r['number'])
            self.state['phase'] = 'waiting_answer'
            text = '数字%s%s吗？' % ({'gt':'大于','lt':'小于','eq':'等于'}[r['comparison']],r['number'])
            self.last_answer = dict(text=text)
            self.say(text, 'question', 'listen')
        elif r['decision'] == 'final_submit':
            expected = 'unique' if len(r['candidates']) == 1 else 'guess'
            if r['comparison'] is not None or r['number'] not in r['candidates'] or r['certainty'] != expected:
                raise ProtocolError(409, 'INVALID_STRATEGY')
            self.pending('final_submit', number=r['number'])
            self.state['phase'] = 'waiting_final_confirm'
            self.say('最终猜测%s，请确认。' % r['number'], 'confirmation', 'listen')
        else:
            raise ProtocolError(400, 'BAD_RESULT')

    def player_input(self, window, r):
        fields = {'intent','comparison','number','answer','pending_id','pending_version','question_id','utterance','parser','reason'}
        if set(r) != fields or r['parser'] not in ('rule','qwen','manual_mock') or not isinstance(r['utterance'],str) or len(r['utterance']) > 160:
            raise ProtocolError(400, 'BAD_RESULT')
        if any(r[k] != window[k] for k in ('pending_id','pending_version','question_id')):
            raise ProtocolError(409, 'STALE_INPUT')
        intent = r['intent']
        if intent == 'unsupported':
            if r['reason'] not in ('ambiguous','unsupported') or any(r[k] is not None for k in ('comparison','number','answer')):
                raise ProtocolError(400,'BAD_RESULT')
            self.say('请重说本次操作。','feedback','listen')
            return
        if intent not in window['allowed_intents'] or r['comparison'] is not None or r['number'] is not None or r['reason'] is not None or (type(r['answer']) is not bool if intent == 'answer' else r['answer'] is not None):
            raise ProtocolError(400,'BAD_RESULT')
        s = self.state
        if intent in ('pause','resume'):
            self.control(intent)
        elif intent == 'help':
            self.say('问题播完后回答是或不是，再确认回答。','feedback','listen')
        elif intent == 'repeat_last':
            self.say(self.last_answer['text'] if self.last_answer else '请继续。','feedback','listen')
        elif intent == 'exit':
            self.exit_context = dict(pending=copy.deepcopy(s['pending']), phase=s['phase'])
            self.pending('exit')
            self.say('确认退出本局吗？','confirmation','listen')
        elif intent == 'answer':
            self.pending('answer', answer=r['answer'])
            s['phase'] = 'waiting_answer_confirm'
            self.say('你的回答是%s，请确认。' % ('是' if r['answer'] else '不是'),'confirmation','listen')
        elif intent == 'cancel':
            p = s['pending']
            s['pending'] = None
            if p['kind'] == 'reveal':
                self.capture('reveal')
            elif p['kind'] == 'answer':
                s['phase'] = 'waiting_answer'
                self.say('已取消回答，请重新回答。','feedback','listen')
            elif p['kind'] == 'exit':
                context = self.exit_context
                self.exit_context = None
                if context:
                    s.update(pending=context['pending'],phase=context['phase'])
                self.say('已取消退出，请继续。','feedback','listen')
            else:
                self.strategy()
        elif intent == 'confirm':
            p = s['pending']
            s['pending'] = None
            if p['kind'] == 'answer':
                s['history'].append(dict(s['locked_question'],answer=p['answer']))
                s['remaining_questions'] -= 1
                s['locked_question'] = None
                self.strategy()
            elif p['kind'] == 'final_submit':
                s['final_submission'] = p['number']
                self.capture('reveal')
            elif p['kind'] == 'exit':
                self.finish('exited','UNVERIFIED',None)
            elif p['kind'] == 'reveal':
                self.verify_reveal(p['number'])

    def verify_reveal(self, value):
        # First knowledge of the player's card: only after final guess is locked.
        self.secret = value
        lies = []
        for i, q in enumerate(self.state['history'],1):
            truth = {'gt':value>q['number'],'lt':value<q['number'],'eq':value==q['number']}[q['comparison']]
            if truth != q['answer']:
                lies.append(i)
        if len(lies) > 1:
            self.finish('invalid','EXCESS_LIES',value)
        else:
            win = self.state['final_submission'] == value
            self.finish('guesser_win' if win else 'hider_win','CORRECT_GUESS' if win else 'WRONG_GUESS',value)

    def control(self, action):
        if not self.state or action != 'resume':
            return super().control(action)
        if not self.state['paused']:
            raise ProtocolError(409,'INVALID_PHASE')
        phase = self.state['resume_phase']
        # Parent resumes with a speech window; B stages instead require private B tasks.
        if phase in ('registration_capture','registration_confirm','reveal_capture'):
            for task in self.tasks.values():
                if task['status'] == 'queued':task['status'] = 'cancelled'
            self.state.update(paused=False,resume_phase=None,phase=phase,input_epoch=self.state['input_epoch']+1)
            if phase == 'registration_confirm' and self.candidate:
                self.candidate['id'] = uid()
                self.candidate['version'] += 1
                self.private_confirm()
            else:
                self.capture('registration' if phase == 'registration_capture' else 'reveal')
        else:
            super().control(action)

    def finish(self, outcome, reason, number):
        # Exit before registration has no truth value and must not reveal anything.
        original = self.secret
        if original is None:
            self.secret = 0  # no reveal: public audit fields remain null
        try:
            super().finish(outcome, reason, number)
        finally:
            self.secret = original

    def upload_evidence(self, role, body, key):
        if role != 'B':raise ProtocolError(403,'FORBIDDEN')
        if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ProtocolError(400,'BAD_REQUEST')
        fields={'protocol_version','game_id','command_id','input_epoch','mime_type','image_base64'}
        if not isinstance(body,dict) or set(body)!=fields or body['protocol_version']!='1.0' or body['mime_type']!='image/jpeg':raise ProtocolError(400,'BAD_REQUEST')
        fingerprint=hashlib.sha256(__import__('json').dumps(body,sort_keys=True).encode()).hexdigest()
        if key in self.evidence_requests:
            original,response=self.evidence_requests[key]
            if original!=fingerprint:raise ProtocolError(409,'REQUEST_CONFLICT')
            return copy.deepcopy(response),True
        self.current(body)
        task=self.tasks.get(body['command_id'])
        if not task or task['command']['command_type']!='vision.capture' or task['command']['input_epoch']!=body['input_epoch'] or task['command']['game_id']!=body['game_id'] or task['status'] not in ('accepted','running'):raise ProtocolError(409,'INVALID_PHASE')
        if any(e['command_id']==body['command_id'] for e in self.evidence.values()):raise ProtocolError(409,'EVIDENCE_EXISTS')
        try:
            raw=base64.b64decode(body['image_base64'],validate=True)
            if len(raw)>2*1024*1024:raise ProtocolError(413,'PAYLOAD_TOO_LARGE')
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format!='JPEG':raise ValueError()
                    image.verify()
                with Image.open(io.BytesIO(raw)) as image:image.load()
        except ProtocolError:raise
        except (ValueError,TypeError,OSError,Image.DecompressionBombWarning,Image.DecompressionBombError):raise ProtocolError(400,'INVALID_IMAGE')
        eid=uid()
        response=dict(evidence_id=eid,sha256=hashlib.sha256(raw).hexdigest())
        self.evidence[eid]=dict(game_id=body['game_id'],command_id=body['command_id'],image_base64=body['image_base64'])
        self.evidence_requests[key]=(fingerprint,response)
        return response,False

    def evidence_image(self,role,eid):
        if role not in ('B','C'):raise ProtocolError(403,'FORBIDDEN')
        if eid not in self.evidence:raise ProtocolError(404,'NOT_FOUND')
        return base64.b64decode(self.evidence[eid]['image_base64'])
