#!/usr/bin/env python3
"""默认仅预览。--run 只控制头部，不抢占控制权、不复位全身。"""
import argparse
import json
import sys
import time
import threading
import queue
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from robot_strategy.head_motion import trajectory


def bounded(call, *args):
    # 超时后主流程停止发送；只读 RPC 的迟到响应不会恢复动作。
    results = queue.Queue()
    def worker():
        try:
            results.put((True, call(*args)))
        except Exception as exc:
            results.put((False, exc))
    threading.Thread(target=worker, daemon=True).start()
    try:
        ok, value = results.get(timeout=2)
    except queue.Empty:
        raise TimeoutError('只读服务调用超过 2 秒')
    if not ok:
        raise value
    return value


def execute(args):
    import rospy
    from bodyhub.msg import JointControlPoint
    from bodyhub.srv import SrvString, SrvTLSstring, SrvServoAllRead
    rospy.init_node('d_head_action', anonymous=True, disable_signals=True)
    prefix = '/MediumSize/BodyHub/'
    for name in ('GetStatus', 'GetMasterID', 'GetJointAngle'):
        rospy.wait_for_service(prefix + name, timeout=3)
    status = rospy.ServiceProxy(prefix + 'GetStatus', SrvString)
    owner = rospy.ServiceProxy(prefix + 'GetMasterID', SrvTLSstring)
    angles = rospy.ServiceProxy(prefix + 'GetJointAngle', SrvServoAllRead)
    def check(allow_running=False):
        current = bounded(status, 'get')
        if bounded(owner, 'get').data != 2:
            raise RuntimeError('控制 ID 不是 2，拒绝抢占')
        allowed = ('ready', 'pause', 'running') if allow_running else ('ready', 'pause')
        if current.data not in allowed or current.poseQueueSize or current.jointQueueSize:
            raise RuntimeError('状态不允许或存在全身队列：' + str(current))
        return current
    def read_head():
        values = list(bounded(angles, list(range(1, 23)), 22).getData)
        if len(values) != 22:
            raise RuntimeError('指令角缓存不是 22 维')
        return values[20:22]
    check()
    start = read_head()
    points = trajectory(args.action, start, args.amplitude, args.seconds)
    publisher = rospy.Publisher(prefix + 'HeadPosition', JointControlPoint, queue_size=2)
    deadline = time.monotonic() + 3
    while publisher.get_num_connections() == 0:
        if time.monotonic() > deadline:
            raise TimeoutError('头部话题没有订阅者')
        time.sleep(.05)
    # 检查当前缓存稳定性；不能替代现场确认及排他调度。
    time.sleep(.3)
    if any(abs(a - b) > .2 for a, b in zip(start, read_head())):
        raise RuntimeError('头部缓存正在变化，请先停用其他头部控制')
    check()
    print(json.dumps({'status': 'started', 'action': args.action, 'start_cache': start,
                      'target_cache': points[-1]}, ensure_ascii=False), flush=True)
    started = time.monotonic()
    deadline = started + len(points) / 50 + 12
    feedback = []
    segments = {'nod': 2, 'shake': 3, 'center': 1}[args.action]
    segment_frames = len(points) // segments
    try:
        for i, point in enumerate(points):
            if rospy.is_shutdown() or time.monotonic() > deadline:
                raise TimeoutError('动作被中断或超时')
            if i % 25 == 0:
                check(allow_running=True)
            publisher.publish(JointControlPoint(positions=list(point), mainControlID=2))
            time.sleep(.02)
            if (i + 1) % segment_frames == 0:
                # 每个转折点都检查缓存，不能只凭最终回到零判断整个动作执行过。
                waypoint_deadline = min(deadline, time.monotonic() + 2)
                while time.monotonic() < waypoint_deadline:
                    check(allow_running=True)
                    cache = read_head()
                    if all(abs(a-b) < .2 for a,b in zip(cache, point)):
                        entry = {'segment': (i+1)//segment_frames,
                                 'target': list(point), 'cache': cache}
                        feedback.append(entry)
                        print(json.dumps(dict(entry, status='waypoint_cache_reached'),
                                         ensure_ascii=False), flush=True)
                        break
                    time.sleep(.05)
                else:
                    raise TimeoutError('中间目标角未得到指令缓存确认')
        stable = 0
        while time.monotonic() < deadline:
            current = check(allow_running=True)
            final = read_head()
            matched = all(abs(a - b) < .2 for a, b in zip(final, points[-1]))
            stable = stable + 1 if current.data == 'pause' and matched else 0
            if stable >= 3:
                return {'status': 'controller_completed', 'action': args.action,
                        'final_cache': final, 'bodyhub_state': current.data,
                        'seconds': round(time.monotonic() - started, 3),
                        'waypoints': feedback,
                        'physical_verified': False}
            time.sleep(.1)
        raise TimeoutError('未得到稳定 pause 和目标指令角缓存反馈')
    finally:
        publisher.unregister()
        rospy.signal_shutdown('D 动作示例结束')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('nod', 'shake', 'center'))
    parser.add_argument('--amplitude', type=float, default=None,
                        help='点头默认 10 度；摇头默认左右各 12 度')
    # 暂定测试值：正式交互须与 A 按台词和播报开始/结束反馈协调。
    parser.add_argument('--seconds', type=float, default=1.,
                        help='普通动作每段暂定 1 秒，后续须与语言协调；回正另行限速')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.amplitude is None:
        args.amplitude = 12. if args.action == 'shake' else 10.
    try:
        points = trajectory(args.action, [0., 0.], args.amplitude, args.seconds)
        result = execute(args) if args.run else {
            'status': 'preview_only', 'action': args.action, 'frames': len(points),
            'duration_nominal': len(points) / 50, 'amplitude': args.amplitude,
            'seconds_per_segment': args.seconds,
            'note': '预览假设起始角为零；--run 读取实际缓存重新规划'}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc),
                          'physical_verified': False}, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
