"""模拟 ROS：回到零不应掩盖中间动作未收到的情况。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts' / 'head_action.py'
spec = importlib.util.spec_from_file_location('d_head_action_test', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HeadFeedbackTests(unittest.TestCase):
    def run_fake(self, accept):
        cache, sent, clock = [0., 0.], [], [0.]
        def publish(message):
            sent.append(message.positions)
            if accept:
                cache[:] = message.positions
        publisher = SimpleNamespace(get_num_connections=lambda: 1, publish=publish,
                                    unregister=lambda: None)
        def proxy(name, _):
            if name.endswith('GetStatus'):
                return lambda *a: SimpleNamespace(data='pause', poseQueueSize=0, jointQueueSize=0)
            if name.endswith('GetMasterID'):
                return lambda *a: SimpleNamespace(data=2)
            return lambda *a: SimpleNamespace(getData=[0.] * 20 + cache)
        rospy = SimpleNamespace(init_node=lambda *a, **kw: None,
                                wait_for_service=lambda *a, **kw: None, ServiceProxy=proxy,
                                Publisher=lambda *a, **kw: publisher,
                                is_shutdown=lambda: False, signal_shutdown=lambda *a: None)
        modules = {'rospy': rospy, 'bodyhub': SimpleNamespace(),
                   'bodyhub.msg': SimpleNamespace(JointControlPoint=SimpleNamespace),
                   'bodyhub.srv': SimpleNamespace(SrvString=object, SrvTLSstring=object,
                                                  SrvServoAllRead=object)}
        fake_time = SimpleNamespace(monotonic=lambda: clock[0],
                                    sleep=lambda value: clock.__setitem__(0, clock[0]+value))
        with patch.dict('sys.modules', modules), patch.object(module, 'time', fake_time), \
                patch.object(module, 'bounded', lambda call, *a: call(*a)):
            return module.execute(SimpleNamespace(action='nod', amplitude=10., seconds=1.))

    def test_unreceived_intermediate_target_fails(self):
        with self.assertRaisesRegex(TimeoutError, '中间目标角'):
            self.run_fake(False)

    def test_waypoints_are_required(self):
        result = self.run_fake(True)
        self.assertEqual(result['status'], 'controller_completed')
        self.assertEqual([p['cache'] for p in result['waypoints']], [[0., 10.], [0., 0.]])
        self.assertFalse(result['physical_verified'])
