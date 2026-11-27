"""Robot-hides coordinator. All commands are queued; never touches hardware."""
import copy
import json
import secrets
import uuid
from .transport import Transport, ProtocolError


def uid():
    return uuid.uuid4().hex


class Coordinator(Transport):
    def __init__(self, tokens):
        super().__init__(tokens)
        self.state = None
        self.secret = None
        self.seed = None
        self.lie_used = False
        self.creates = {}
        self.after_say = {}
        self.last_answer = None

    def public(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def create_game(self, role, body, key):
        with self.lock:
            if role != 'C':
                raise ProtocolError(403, 'FORBIDDEN')
            if not isinstance(key, str) or len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
                raise ProtocolError(400, 'BAD_REQUEST')
            if key in self.creates:
                original, response = self.creates[key]
                if original != body:
                    raise ProtocolError(409, 'REQUEST_CONFLICT')
                return copy.deepcopy(response), True
            if not isinstance(body, dict) or set(body) != {'protocol_version', 'mode', 'runtime_mode'} or body['protocol_version'] != '1.0' or body['runtime_mode'] not in ('mock', 'robot'):
                raise ProtocolError(400, 'BAD_REQUEST')
            if body['mode'] != 'robot_hides':
                raise ProtocolError(503, 'SERVICE_UNAVAILABLE')
            if self.state and self.state['phase'] != 'finished':
                raise ProtocolError(409, 'GAME_ACTIVE')
            # Until persistent recovery is available, only simulation is enabled.
            if body['runtime_mode'] == 'robot' and not getattr(self, 'allow_robot', False):
                raise ProtocolError(503, 'SERVICE_UNAVAILABLE')
            from datetime import datetime
            if any(task['status'] in ('accepted', 'running') for task in self.tasks.values()):
                raise ProtocolError(409, 'EXECUTOR_NOT_IDLE')
            for task in self.tasks.values():
                if task['status'] == 'queued':
                    task['status'] = 'cancelled'
            self.secret, self.seed = secrets.randbelow(10) + 1, secrets.randbelow(2**31)
            self.lie_used = False
            self.last_answer = None
            self.state = dict(protocol_version='1.0', game_id=uid(), mode='robot_hides', runtime_mode=body['runtime_mode'], phase='waiting_question', paused=False, resume_phase=None, input_epoch=0, remaining_questions=7, history=[], pending=None, locked_question=None, final_submission=None, result=None, started_at=datetime.now().astimezone().isoformat(), ended_at=None)
            self.say('请提问。最多七次提问，最后提交一个数字。', 'prompt', 'listen')
            response = {'state': self.public()}
            self.creates[key] = (copy.deepcopy(body), copy.deepcopy(response))
            return response, False

    def command(self, kind, payload):
        role = 'D' if kind.startswith(('strategy.', 'motion.')) else 'A'
        cmd = dict(protocol_version='1.0', command_id=uid(), game_id=self.state['game_id'], input_epoch=self.state['input_epoch'], target=role, command_type=kind, timeout_ms=5000 if kind == 'strategy.decide' else 15000, payload=payload)
        self.enqueue(cmd)
        return cmd['command_id']

    def say(self, text, purpose, after=None, answer_id=None):
        cid = self.command('speech.say', dict(text=text, purpose=purpose, answer_id=answer_id, sync_group_id=answer_id))
        self.after_say[cid] = after

    def listen(self):
        s = self.state
        p = s['pending']
        allowed = ['confirm', 'cancel', 'pause', 'exit', 'help'] if p else ['question', 'final_submit', 'pause', 'exit', 'repeat_last', 'help']
        if s['remaining_questions'] == 0 and not p:
            allowed.remove('question')
        if s['paused']:
            allowed = ['resume', 'exit', 'help']
        self.command('speech.listen', dict(allowed_intents=allowed, pending_id=p['pending_id'] if p else None, pending_version=p['pending_version'] if p else None, question_id=None, max_listen_ms=15000))

    def event(self, role, event, instance):
        # Transaction: a rejected business result must not consume its request or task.
        with self.lock:
            names = ('tasks', 'receipts', 'modules', 'state', 'secret', 'seed', 'lie_used', 'after_say', 'last_answer')
            backup = {n: copy.deepcopy(getattr(self, n)) for n in names}
            try:
                key = (role, event.get('request_id')) if isinstance(event, dict) else None
                if key in self.receipts:
                    return super().event(role, event, instance)
                if isinstance(event, dict) and event.get('event_type') in ('control.pause', 'control.resume', 'control.exit'):
                    if role != 'C' or set(event) != {'protocol_version','request_id','game_id','input_epoch','source','command_id','event_type','payload'} or event.get('protocol_version') != '1.0' or event.get('source') != role or not isinstance(event.get('request_id'), str) or len(event['request_id']) != 32 or any(c not in '0123456789abcdef' for c in event['request_id']) or event.get('command_id') is not None:
                        raise ProtocolError(400, 'BAD_REQUEST')
                    self.current(event)
                    kind = event['event_type']
                    if event['payload'] != ({'confirmed': True} if kind == 'control.exit' else {}):
                        raise ProtocolError(400, 'BAD_REQUEST')
                    self.control(kind.split('.')[1])
                    result = dict(disposition='applied', command_status=None)
                    self.receipts[key] = (json.dumps(event, sort_keys=True, allow_nan=False), result)
                    return result, False
                task = self.tasks.get(event.get('command_id')) if isinstance(event, dict) else None
                was_terminal = task and 'result_payload' in task
                result, replay = super().event(role, event, instance)
                if task and self.state and event['event_type'] in ('task.result', 'task.started'):
                    cmd = task['command']
                    if cmd['game_id'] != self.state['game_id'] or cmd['input_epoch'] != self.state['input_epoch'] or self.state['phase'] == 'finished':
                        result['disposition'] = 'ignored_for_game'
                    elif event['event_type'] == 'task.result' and not was_terminal:
                        payload = event['payload']
                        if payload['status'] == 'success':
                            self.apply_result(cmd, payload['result'])
                            result['disposition'] = 'applied'
                        else:
                            # Fail closed: do not count, guess, or blindly retry actions.
                            self.control('pause')
                    elif event['event_type'] == 'task.started' and cmd['command_type'] == 'speech.say' and cmd['payload']['answer_id'] and getattr(self, 'motion_enabled', True):
                        aid = cmd['payload']['answer_id']
                        if not any(t['command']['command_type'] == 'motion.execute' and t['command']['payload']['answer_id'] == aid for t in self.tasks.values()):
                            self.command('motion.execute', dict(action='nod' if self.last_answer['answer'] else 'shake', sync_group_id=aid, reason='spoken_answer', answer_id=aid))
                return result, replay
            except Exception:
                for name, value in backup.items():
                    setattr(self, name, value)
                raise

    def current(self, event):
        if not self.state or self.state['phase'] == 'finished' or event['game_id'] != self.state['game_id'] or type(event['input_epoch']) is not int or event['input_epoch'] != self.state['input_epoch']:
            raise ProtocolError(409, 'STALE_INPUT')

    def control(self, action):
        s = self.state
        if action == 'pause' and s['paused'] or action == 'resume' and not s['paused']:
            raise ProtocolError(409, 'INVALID_PHASE')
        for t in self.tasks.values():
            if t['command']['game_id'] == s['game_id']:
                if t['status'] == 'queued':
                    t['status'] = 'cancelled'
                elif t['status'] in ('accepted', 'running'):
                    t['cancel_requested'] = True
        s['input_epoch'] += 1
        if action == 'pause':
            s['resume_phase'], s['phase'], s['paused'] = s['phase'], 'paused', True
            self.listen()
        elif action == 'resume':
            s['phase'], s['resume_phase'], s['paused'] = s['resume_phase'], None, False
            if s['pending']:
                s['pending']['pending_id'] = uid()
                s['pending']['pending_version'] += 1
            if s['phase'] == 'waiting_strategy':
                self.strategy()
            else:
                self.say('已恢复，请继续。', 'feedback', 'listen')
        else:
            self.finish('exited', 'USER_EXIT', None)

    def apply_result(self, cmd, r):
        kind = cmd['command_type']
        if kind == 'speech.say':
            if set(r) != {'spoken'} or r['spoken'] is not True:
                raise ProtocolError(400, 'BAD_RESULT')
            if self.after_say.get(cmd['command_id']) == 'listen':
                self.listen()
        elif kind == 'speech.listen':
            self.input(cmd['payload'], r)
        elif kind == 'strategy.decide':
            self.answer(r)
        elif kind == 'motion.execute':
            if set(r) != {'action','executed'} or r['action'] != cmd['payload']['action'] or r['executed'] is not True:
                raise ProtocolError(400, 'BAD_RESULT')

    def input(self, window, r):
        fields = {'intent','comparison','number','answer','pending_id','pending_version','question_id','utterance','parser','reason'}
        if set(r) != fields or r['parser'] not in ('rule','qwen','manual_mock') or not isinstance(r['utterance'], str) or len(r['utterance']) > 160:
            raise ProtocolError(400, 'BAD_RESULT')
        if any(r[k] != window[k] for k in ('pending_id','pending_version','question_id')):
            raise ProtocolError(409, 'STALE_INPUT')
        intent = r['intent']
        if intent == 'unsupported':
            if r['reason'] not in ('ambiguous','unsupported') or any(r[k] is not None for k in ('comparison','number','answer')):
                raise ProtocolError(400, 'BAD_RESULT')
            self.say('没有听清有效操作，请重说。', 'feedback', 'listen')
            return
        if intent not in window['allowed_intents']:
            raise ProtocolError(409, 'INVALID_INTENT')
        if r['reason'] is not None or r['answer'] is not None or (intent != 'question' and r['comparison'] is not None) or (intent not in ('question','final_submit') and r['number'] is not None):
            raise ProtocolError(400, 'BAD_RESULT')
        if intent in ('pause','resume'):
            self.control(intent)
            return
        if intent == 'help':
            self.say('可以问大于、小于或等于某个数字，或最终提交。', 'feedback', 'listen')
            return
        if intent == 'repeat_last':
            self.say(self.last_answer['text'] if self.last_answer else '还没有回答记录。', 'feedback', 'listen')
            return
        s = self.state
        if intent in ('question','final_submit','exit'):
            if intent != 'exit' and (type(r['number']) is not int or not 1 <= r['number'] <= 10):
                raise ProtocolError(400, 'BAD_RESULT')
            if intent == 'question' and (r['comparison'] not in ('gt','lt','eq') or s['remaining_questions'] == 0):
                raise ProtocolError(409, 'INVALID_INTENT')
            s['pending'] = dict(pending_id=uid(), pending_version=1, kind=intent, comparison=r['comparison'] if intent == 'question' else None, number=r['number'] if intent != 'exit' else None, answer=None)
            s['phase'] = 'waiting_question_confirm' if intent == 'question' else 'waiting_final_confirm'
            text = ('问题：数字%s%s。' % ({'gt':'大于','lt':'小于','eq':'等于'}[r['comparison']], r['number'])) if intent == 'question' else ('最终提交数字%s。' % r['number'] if intent == 'final_submit' else '结束当前对局。')
            self.say(text + '请确认，或取消。', 'confirmation', 'listen')
        elif intent == 'cancel':
            s['pending'] = None
            s['phase'] = 'waiting_question'
            self.say('已取消，不扣次数。', 'feedback', 'listen')
        elif intent == 'confirm':
            p = s['pending']
            if not p:
                raise ProtocolError(409, 'INVALID_PHASE')
            s['pending'] = None
            if p['kind'] == 'exit':
                self.finish('exited', 'USER_EXIT', None)
            elif p['kind'] == 'final_submit':
                s['final_submission'] = p['number']
                self.finish('guesser_win' if p['number'] == self.secret else 'hider_win', 'CORRECT_GUESS' if p['number'] == self.secret else 'WRONG_GUESS', self.secret)
            else:
                s['locked_question'] = dict(question_id=uid(), comparison=p['comparison'], number=p['number'])
                s['phase'] = 'waiting_strategy'
                self.strategy()

    def strategy(self):
        s = self.state
        self.command('strategy.decide', dict(purpose='answer_question', mode='robot_hides', secret=self.secret, question=s['locked_question'], question_ordinal=len(s['history'])+1, history=s['history'], lie_used=self.lie_used, max_lies=1, decision_seed=self.seed))

    def answer(self, r):
        s = self.state
        q = s['locked_question']
        if s['phase'] != 'waiting_strategy' or set(r) != {'decision','comparison','number','answer','lie_applied','candidates','certainty'} or r['decision'] != 'answer' or type(r['answer']) is not bool or type(r['lie_applied']) is not bool or r['comparison'] is not None or r['number'] is not None or r['candidates'] != [] or r['certainty'] != 'not_final':
            raise ProtocolError(400, 'BAD_RESULT')
        truth = {'gt': self.secret > q['number'], 'lt': self.secret < q['number'], 'eq': self.secret == q['number']}[q['comparison']]
        lie = r['answer'] != truth
        if lie != r['lie_applied'] or lie and self.lie_used:
            raise ProtocolError(409, 'INVALID_STRATEGY')
        self.lie_used |= lie
        s['history'].append(dict(q, answer=r['answer']))
        s['remaining_questions'] -= 1
        s['locked_question'] = None
        s['phase'] = 'waiting_question'
        self.last_answer = dict(answer=r['answer'], text='是。' if r['answer'] else '不是。')
        self.say(self.last_answer['text'], 'answer', 'listen', uid())

    def finish(self, outcome, reason, number):
        from datetime import datetime
        s = self.state
        # Lie rounds are calculated from committed public answers, only at game end.
        rounds = []
        for i, q in enumerate(s['history'], 1):
            truth = {'gt':self.secret > q['number'], 'lt':self.secret < q['number'], 'eq':self.secret == q['number']}[q['comparison']]
            if q['answer'] != truth:
                rounds.append(i)
        s.update(phase='finished', paused=False, resume_phase=None, pending=None, locked_question=None, ended_at=datetime.now().astimezone().isoformat(), result=dict(outcome=outcome, reason_code=reason, revealed_number=number, lie_count=len(rounds) if number is not None else None, lie_rounds=rounds if number is not None else []))
        self.say('本局结束。', 'result')
