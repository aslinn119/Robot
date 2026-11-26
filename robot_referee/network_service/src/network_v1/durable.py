"""Atomic private journal and deadline handling for the mock coordinator."""
import copy
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .player import GameCoordinator as Coordinator
from .transport import ProtocolError


class DurableCoordinator(Coordinator):
    FIELDS = ('tasks', 'receipts', 'modules', 'state', 'secret', 'seed',
              'lie_used', 'creates', 'after_say', 'last_answer', 'deadlines', 'archives',
              'candidate', 'mismatch_count', 'capture_attempt', 'evidence', 'evidence_requests', 'exit_context')

    def __init__(self, tokens, directory, clock=time.monotonic):
        super().__init__(tokens)
        self.directory = Path(directory)
        self.path = self.directory / 'network_private.json'
        self.clock = clock
        self.deadlines = {}
        self.archives = {}
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if saved.get('format') != 1:
                raise ValueError('Unsupported network journal format')
            self.creates = saved['creates']
            self.archives = saved['archives']
            self.evidence = saved.get('evidence', {})
            self.evidence_requests = saved.get('evidence_requests', {})
            old = saved['current']
            if old:
                state = copy.deepcopy(old['state'])
                if state and state['phase'] != 'finished':
                    state.update(phase='finished', paused=False, resume_phase=None,
                                 pending=None, locked_question=None,
                                 ended_at=datetime.now().astimezone().isoformat(),
                                 result=dict(outcome='interrupted', reason_code='SERVER_INTERRUPTED',
                                             revealed_number=None, lie_count=None, lie_rounds=[]))
                if state:
                    self.archives[state['game_id']] = state
            # New process does not replay commands. Mock-only mode stays enforced.
            self._save()

    def _checkpoint(self):
        return {name: copy.deepcopy(getattr(self, name)) for name in self.FIELDS}

    def _restore(self, snapshot):
        for name, value in snapshot.items():
            setattr(self, name, value)

    def _save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        current = None
        if self.state:
            current = dict(state=self.state, secret=self.secret, seed=self.seed,
                           lie_used=self.lie_used, tasks=self.tasks, candidate=self.candidate, mismatch_count=self.mismatch_count,
                           receipts=[dict(source=k[0], request_id=k[1], fingerprint=v[0], response=v[1])
                                     for k, v in self.receipts.items()])
        data = dict(format=1, server_instance_id=self.instance, creates=self.creates,
                    archives=self.archives, current=current, evidence=self.evidence, evidence_requests=self.evidence_requests)
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)
        fd, temporary = tempfile.mkstemp(prefix='.network-', suffix='.tmp', dir=str(self.directory))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _transaction(self, operation):
        with self.lock:
            snapshot = self._checkpoint()
            try:
                result = operation()
                self._save()
                return copy.deepcopy(result)
            except OSError as error:
                self._restore(snapshot)
                raise ProtocolError(503, 'JOURNAL_UNAVAILABLE') from error
            except Exception:
                self._restore(snapshot)
                raise

    def enqueue(self, command):
        super().enqueue(command)
        if command['command_id'] not in self.deadlines:
            self.deadlines[command['command_id']] = self.clock() + 5.0

    def create_game(self, role, body, key):
        def operation():
            if key not in self.creates and any(t['executor_state'] == 'unknown' for t in self.tasks.values()):
                raise ProtocolError(409, 'EXECUTOR_NOT_IDLE')
            result = super(DurableCoordinator, self).create_game(role, body, key)
            return result
        return self._transaction(operation)

    def event(self, role, event, instance):
        self.tick()
        def operation():
            result, replay = super(DurableCoordinator, self).event(role, event, instance)
            if not replay and event['event_type'] in ('task.accepted', 'task.started'):
                cid = event['command_id']
                task = self.tasks[cid]
                # Duplicate lifecycle messages must not extend a deadline.
                marker = '_accepted_at' if event['event_type'] == 'task.accepted' else '_started_at'
                if marker not in task:
                    task[marker] = self.clock()
                    self.deadlines[cid] = self.clock() + (3.0 if marker == '_accepted_at' else task['command']['timeout_ms'] / 1000.0)
            return result, replay
        return self._transaction(operation)

    def upload_evidence(self, role, body, key):
        self.tick()
        return self._transaction(lambda: super(DurableCoordinator, self).upload_evidence(role, body, key))

    def tick(self):
        """Expire tasks without assuming a running executor has physically stopped."""
        def operation():
            expired = []
            for cid, task in self.tasks.items():
                if task['status'] in ('queued', 'accepted', 'running') and self.clock() >= self.deadlines[cid]:
                    previous = task['status']
                    task['status'] = 'expired'
                    task['remaining_ms'] = 0
                    task['cancel_requested'] = previous != 'queued'
                    task['executor_state'] = 'idle' if previous == 'queued' else 'unknown'
                    expired.append(cid)
            if expired and self.state and self.state['phase'] != 'finished' and not self.state['paused']:
                self.control('pause')
            return expired
        with self.lock:
            if not any(t['status'] in ('queued', 'accepted', 'running') and self.clock() >= self.deadlines[cid] for cid, t in self.tasks.items()):
                return []
        return self._transaction(operation)

    def next(self, role, module, lane):
        self.tick()
        with self.lock:
            # Preserve authorization checks even when a lane is blocked.
            result = super().next(role, module, lane)
            if any(t['command']['target'] == module and t['lane'] == lane and t['executor_state'] == 'unknown' for t in self.tasks.values()):
                return {'command': None}
            return result

    def lookup(self, role, cid):
        self.tick()
        with self.lock:
            result = super().lookup(role, cid)
            for key in list(result):
                if key.startswith('_'):
                    del result[key]
            if result['status'] in ('queued', 'accepted', 'running'):
                result['remaining_ms'] = max(0, int((self.deadlines[cid] - self.clock()) * 1000))
            return result

    def game_public(self, game_id):
        with self.lock:
            if self.state and self.state['game_id'] == game_id:
                return self.public()
            if game_id not in self.archives:
                raise ProtocolError(404, 'NOT_FOUND')
            return copy.deepcopy(self.archives[game_id])

    def game_list(self, limit=20):
        if not 1 <= limit <= 100:
            raise ProtocolError(400, 'BAD_REQUEST')
        with self.lock:
            states = list(self.archives.values())
            if self.state:
                states = [s for s in states if s['game_id'] != self.state['game_id']] + [self.state]
            states.sort(key=lambda s: s['started_at'], reverse=True)
            return [{key: s[key] for key in ('game_id', 'mode', 'runtime_mode', 'phase', 'started_at', 'ended_at')} for s in states[:limit]]

    def finish(self, outcome, reason, number):
        super().finish(outcome, reason, number)
        self.archives[self.state['game_id']] = self.public()
