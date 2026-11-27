"""Operator-controlled module recovery and opt-in, motion-free robot sessions."""
import copy
import json
from datetime import datetime
from .durable import DurableCoordinator
from .transport import ProtocolError, OWNERS


def uuid_valid(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


class ManagedCoordinator(DurableCoordinator):
    def __init__(self, tokens, directory, clock=None, enable_robot=False):
        self.allow_robot = enable_robot
        self.motion_enabled = False
        if clock is None:
            super().__init__(tokens, directory)
        else:
            super().__init__(tokens, directory, clock)

    def health(self):
        with self.lock:
            states = {r: self.modules.get(r, {}).get('status', 'offline') for r in 'ABD'}
            for role in states:
                if self.clock() - self.modules.get(role, {}).get('seen', -100) > 6:
                    states[role] = 'offline'
            return dict(protocol_version='1.0', service_status='degraded', server_instance_id=self.instance, modules=states)

    def operator_modules(self, role):
        if role != 'C':
            raise ProtocolError(403, 'FORBIDDEN')
        with self.lock:
            return {'modules': {r: dict(instance_id=m.get('instance'), module_status=self.health()['modules'][r],
                                       runtime_mode=m.get('runtime_mode'), capabilities=m.get('capabilities', []),
                                       active_command_ids=m.get('active_command_ids', []))
                                for r in 'ABD' for m in [self.modules.get(r, {})]},
                    'robot_enabled': self.allow_robot, 'motion_enabled': False}

    def robot_requirements(self):
        if not self.allow_robot:
            raise ProtocolError(503, 'ROBOT_MODE_DISABLED')
        needed = {'A': {'speech.say', 'speech.listen'}, 'B': {'vision.capture', 'registration.confirm'}, 'D': {'strategy.decide'}}
        for role, capabilities in needed.items():
            module = self.modules.get(role)
            if not module or self.clock() - module['seen'] > 6:
                raise ProtocolError(503, 'MODULE_OFFLINE')
            if module['status'] != 'ready' or module.get('active_command_ids'):
                raise ProtocolError(503, 'MODULE_NOT_READY')
            if not capabilities.issubset(module.get('capabilities', [])):
                raise ProtocolError(503, 'CAPABILITY_UNAVAILABLE')
            # A and B must report actual devices. Pure D strategy is hardware-independent.
            if role in 'AB' and module.get('runtime_mode') != 'robot':
                raise ProtocolError(503, 'RUNTIME_MODE_MISMATCH')
            if role == 'D' and module.get('runtime_mode') == 'mock' and set(module['capabilities']) != {'strategy.decide'}:
                raise ProtocolError(503, 'RUNTIME_MODE_MISMATCH')

    def create_game(self, role, body, key):
        with self.lock:
            # Validate authorization/shape before robot readiness diagnostics.
            if role != 'C':
                raise ProtocolError(403, 'FORBIDDEN')
            if not isinstance(body, dict) or set(body) != {'protocol_version', 'mode', 'runtime_mode'} or body['protocol_version'] != '1.0' or body['mode'] not in ('robot_hides', 'player_hides') or body['runtime_mode'] not in ('robot', 'mock') or not uuid_valid(key):
                raise ProtocolError(400, 'BAD_REQUEST')
            if key not in self.creates and body['runtime_mode'] == 'robot':
                self.robot_requirements()
            return super().create_game(role, body, key)

    def heartbeat_check(self, role, event, instance):
        payload = event.get('payload')
        fields = {'instance_id', 'module_status', 'active_command_ids', 'capabilities', 'runtime_mode'}
        if role not in ('A', 'B', 'D') or not isinstance(payload, dict) or set(payload) != fields or not uuid_valid(instance) or payload['instance_id'] != instance:
            raise ProtocolError(400, 'BAD_REQUEST')
        if instance in self.retired_instances.get(role, []):
            raise ProtocolError(409, 'INSTANCE_RETIRED')
        caps, active = payload['capabilities'], payload['active_command_ids']
        allowed = {kind for kind, (owner, _) in OWNERS.items() if owner == role}
        if payload['runtime_mode'] not in ('mock', 'robot') or not isinstance(caps, list) or any(not isinstance(c, str) or c not in allowed for c in caps) or len(set(caps)) != len(caps) or not isinstance(active, list) or len(active) > (2 if role == 'D' else 1) or any(not uuid_valid(c) for c in active) or len(set(active)) != len(active):
            raise ProtocolError(400, 'BAD_REQUEST')
        for cid in active:
            if cid not in self.tasks or self.tasks[cid]['command']['target'] != role:
                raise ProtocolError(409, 'INVALID_ACTIVE_COMMAND')
        old = self.modules.get(role)
        if old and old['instance'] == instance and (old.get('runtime_mode') != payload['runtime_mode'] or old.get('capabilities') != caps):
            active_game = self.state and self.state['phase'] != 'finished'
            if active_game:
                raise ProtocolError(409, 'MODULE_CONFIG_CHANGED')

    def event(self, role, event, instance):
        self.tick()
        if isinstance(event, dict) and event.get('event_type') == 'control.module_reset':
            return self._transaction(lambda: self.reset_event(role, event))
        def operation():
            if role in ('A', 'B', 'D') and instance in self.retired_instances.get(role, []):
                raise ProtocolError(409, 'INSTANCE_RETIRED')
            heartbeat = isinstance(event, dict) and event.get('event_type') == 'module.heartbeat'
            if heartbeat:
                self.heartbeat_check(role, event, instance)
            result, replay = super(ManagedCoordinator, self).event(role, event, instance)
            if heartbeat and not replay:
                module = self.modules[role]
                module.update(seen=self.clock(), runtime_mode=event['payload']['runtime_mode'],
                              capabilities=copy.deepcopy(event['payload']['capabilities']),
                              active_command_ids=list(event['payload']['active_command_ids']))
            return result, replay
        return self._transaction(operation)

    def reset_event(self, role, event):
        if role != 'C' or event.get('source') != 'C':
            raise ProtocolError(403, 'FORBIDDEN')
        if set(event) != {'protocol_version','request_id','game_id','input_epoch','source','command_id','event_type','payload'} or event['protocol_version'] != '1.0' or not uuid_valid(event['request_id']) or event['command_id'] is not None:
            raise ProtocolError(400, 'BAD_REQUEST')
        key = ('C', event['request_id'])
        fingerprint = json.dumps(event, sort_keys=True, allow_nan=False)
        if key in self.receipts:
            original, response = self.receipts[key]
            if original != fingerprint:
                raise ProtocolError(409, 'REQUEST_CONFLICT')
            return copy.deepcopy(response), True
        payload = event['payload']
        if not isinstance(payload, dict) or set(payload) != {'module','previous_instance_id','confirmed_idle'} or payload['module'] not in ('A','B','D') or not uuid_valid(payload['previous_instance_id']):
            raise ProtocolError(400, 'BAD_REQUEST')
        if payload['confirmed_idle'] is not True:
            raise ProtocolError(409, 'IDLE_CONFIRMATION_REQUIRED')
        active_game = self.state and self.state['phase'] != 'finished'
        if active_game:
            self.current(event)
        elif event['game_id'] is not None or event['input_epoch'] is not None:
            raise ProtocolError(409, 'STALE_INPUT')
        module = payload['module']
        old = self.modules.get(module)
        if not old:
            raise ProtocolError(409, 'MODULE_NOT_BOUND')
        if old['instance'] != payload['previous_instance_id']:
            raise ProtocolError(409, 'INSTANCE_MISMATCH')
        if self.clock() - old['seen'] <= 6:
            raise ProtocolError(409, 'MODULE_STILL_ONLINE')
        if active_game and not self.state['paused']:
            self.control('pause')
        affected = []
        for cid, task in self.tasks.items():
            if task['command']['target'] == module and (task['status'] in ('queued','accepted','running') or task['executor_state'] == 'unknown'):
                task.update(status='cancelled', cancel_requested=True, executor_state='idle', remaining_ms=0)
                task['_operator_reset'] = event['request_id']
                affected.append(cid)
        self.retired_instances.setdefault(module, []).append(old['instance'])
        del self.modules[module]
        self.reset_audit.append(dict(request_id=event['request_id'], module=module,
                                     previous_instance_id=old['instance'], confirmed_idle=True,
                                     affected_command_ids=affected, at=datetime.now().astimezone().isoformat()))
        response = dict(disposition='applied', command_status=None)
        self.receipts[key] = (fingerprint, response)
        return response, False

    def control(self, action):
        if action == 'resume':
            if any(t['status'] in ('accepted','running') or t['executor_state'] == 'unknown' for t in self.tasks.values()):
                raise ProtocolError(409, 'EXECUTOR_NOT_IDLE')
            if self.state and self.state['runtime_mode'] == 'robot':
                self.robot_requirements()
        return super().control(action)

    def tick(self):
        expired = super().tick()
        def pause_if_lost():
            if self.state and self.state['phase'] != 'finished' and not self.state['paused']:
                # Only monitor roles that registered. Mock unit fixtures may omit roles.
                if any(self.clock() - m['seen'] > 6 for m in self.modules.values()):
                    self.control('pause')
        with self.lock:
            if self.state and self.state['phase'] != 'finished' and not self.state['paused'] and any(self.clock()-m['seen']>6 for m in self.modules.values()):
                self._transaction(pause_if_lost)
        return expired
