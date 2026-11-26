#!/usr/bin/env python3
"""保留原版全身姿态的游戏动作。默认预览，不导入厂商执行库。"""
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path


EXPRESSIONS = {
    'think': ('head_toward_face', 4000, '思考结束，抬头看向玩家再提问'),
    'win': ('snicker', 5000, '胜局后做一次偷笑动作'),
    'bow_taught': ('bow', 4100, '手摆示教髋部配合低头行礼'),
    'bow_brisk': ('bow', 4100, '浅屈膝配合明显低头，连贯行礼'),
    'bow_lean': ('bow', 5900, '浅屈膝、髋部前倾试验'),
    'bow_deeper': ('bow', 9100, '保留上一版手臂姿态，加深俯身'),
    'bow_trial': ('bow', 8300, '胸前收手后俯身行礼'),
    'lose': ('bow', 7000, '输局后向玩家鞠躬致意'),
}
DEMO_SHA256 = '2904b20f36859847d0b2a0a65a68fbf1aebab4ace4f87f0ed13514aaeda02d5b'


def expression_plan(action, source_dir, run=False):
    preset, duration, meaning = EXPRESSIONS[action]
    source = source_dir / 'action' / 'demo_frame.py'
    result = dict(action=action, preset=preset, meaning=meaning,
                  timeline_end_ms=duration, source=str(source), source_checked=False)
    if not run and not source.exists():
        return result
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DEMO_SHA256:
        raise ValueError('DemoFrame 与已盘点版本不同，请先核对原动作')
    cls = next(n for n in ast.parse(raw.decode('utf-8-sig')).body
               if isinstance(n, ast.ClassDef) and n.name == 'DemoFrame')
    frames = next(ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == preset for t in n.targets))
    if not frames or any(len(f) != 3 or len(f[0]) != 22 for f in frames):
        raise ValueError('DemoFrame 格式与全身动作入口不匹配')
    if action in ('bow_trial', 'bow_deeper', 'bow_lean', 'bow_brisk', 'bow_taught'):
        def last_pose(name):
            assignment = next(n for n in cls.body if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
            return ast.literal_eval(assignment.value)[-1][0]

        base = list(frames[0][0])
        gathered = base.copy()
        gathered[12:18] = last_pose('hug')[12:18]
        bowed = gathered.copy()
        bend = last_pose('bend_over')
        bowed[:12] = bend[:12]
        bowed[21] = bend[21]
        frames = [(base, 1500, 0), (gathered, 1500, 0), (bowed, 1800, 0),
                  (bowed, 700, 0), (gathered, 1500, 0), (base, 1300, 0)]
        result['preset'] = 'bow + hug + bend_over'
        if action == 'bow_deeper':
            # 增加对称髋屈目标，保留膝踝支撑姿态；躯干实际倾角待现场观察。
            deeper = bowed.copy()
            deeper[2] += 5
            deeper[8] -= 5
            frames = [(base, 1500, 0), (gathered, 1500, 0), (deeper, 2200, 0),
                      (deeper, 700, 0), (gathered, 1900, 0), (base, 1300, 0)]
        if action in ('bow_lean', 'bow_brisk', 'bow_taught'):
            # 保留双臂端点，减小屈膝和低头；实际躯干倾角由现场侧视核对。
            lean = gathered.copy()
            lean[:12] = [0, 0, 15, -10, -5, 0, 0, 0, -15, 10, 5, 0]
            lean[21] = 3
            # 手臂和髋部同步，沿用厂商贝塞尔插值，最低点不另加停顿。
            frames = [(base, 1300, 0), (lean, 2300, 0), (base, 2300, 0)]
            if action in ('bow_brisk', 'bow_taught'):
                if action == 'bow_taught':
                    # teach-kBTQmo：取两次编码器读数之差，施加到游戏基姿态。
                    lean[:12] = base[:12]
                    lean[2] += 18.90625
                    lean[8] -= 17.5
                lean[21] = 15
                frames = [(base, 1000, 0), (lean, 1500, 0), (base, 1600, 0)]
    return dict(result, source_checked=True, frames=list(frames))


def read_frames(source, variable):
    raw = source.read_bytes()
    tree = ast.parse(raw.decode('utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == variable for t in node.targets):
            return ast.literal_eval(node.value), hashlib.sha256(raw).hexdigest()
    raise ValueError('原版动作变量不存在，不能猜测生成')


def plan(action, source_dir, cycles=2, beat_ms=500):
    if type(cycles) is not int or not 1 <= cycles <= 3:
        raise ValueError('试验次数限定 1～3 次')
    if type(beat_ms) is not int or not 400 <= beat_ms <= 1000:
        raise ValueError('每段暂限 400～1000 毫秒；后续与语音协调')
    if action == 'nod':
        source = source_dir / '点头.py'
        original, digest = read_frames(source, 'u70b9u5934_frames')
        if set(original) != set(map(str, range(1, 23))):
            raise ValueError('原版点头不是预期的 22 关节结构')
        base = [original[str(i)][-1][0][1] for i in range(1, 23)]
        peak = [original[str(i)][0][0][1] for i in range(1, 23)]
        if peak[20:] != [0, 20] or base[20:] != [0, 0] or peak[:20] != base[:20]:
            raise ValueError('原版点头轨迹已变更，需重新检查')
        poses = [base] + [p for _ in range(cycles) for p in (peak, base)]
    elif action == 'shake':
        source = source_dir / '摇头.py'
        original, digest = read_frames(source, 'shake_head_frames')
        if len(original) != 5 or any(len(f[0]) != 22 for f in original):
            raise ValueError('原版摇头帧结构已变更')
        base, left, right = [list(original[i][0]) for i in (0, 1, 2)]
        if [base[20:], left[20:], right[20:]] != [[0, 0], [-24, 0], [24, 0]]:
            raise ValueError('原版摇头角度已变更，需重新检查')
        # 每轮是一侧→另一侧→回中，保留原版对应的手臂及身体姿态。
        poses = [base] + [p for _ in range(cycles) for p in (left, right, base)]
    else:
        raise ValueError('未知动作')
    # 第一秒调整到原版基姿态，之后按暂定节拍执行。所有关节写入 1～22。
    times = [1000 + i * beat_ms for i in range(len(poses))]
    frames = {str(j+1): [[[t, pose[j]], [0, 0], [0, 0]]
                         for t, pose in zip(times, poses)] for j in range(22)}
    return {'action': action, 'cycles': cycles, 'beat_ms': beat_ms,
            'source': str(source), 'source_sha256': digest,
            'timeline_end_ms': times[-1], 'head_targets': [p[20:] for p in poses],
            'joint_ids': list(range(1, 23)), 'frames': frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('nod', 'shake', *EXPRESSIONS))
    parser.add_argument('--source-dir', type=Path, default=Path(
        '/home/lemon/robot_ros_application/catkin_ws/src/ros_actions_node/scripts'))
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--beat-ms', type=int, default=500)
    parser.add_argument('--run', action='store_true', help='现场确认后执行原版全身姿态变体')
    args = parser.parse_args()
    if args.action in EXPRESSIONS:
        result = expression_plan(args.action, args.source_dir, args.run)
    else:
        result = plan(args.action, args.source_dir, args.cycles, args.beat_ms)
    if not args.run:
        print(json.dumps(dict(result, status='plan_only_not_executed'), ensure_ascii=False, indent=2))
        return
    # 只在显式执行时导入厂商模块；本入口应通过 timeout 限定整个进程。
    import rospy
    from bodyhub.srv import SrvString, SrvTLSstring
    from head_action import bounded
    sys.path.insert(0, str(args.source_dir))
    from lejulib import node_initial, client_action, SetBodyhubTo_setStatus, finishsend
    node_initial(name='d_game_gesture', stateJump=False)
    acquired = False
    try:
        prefix = '/MediumSize/BodyHub/'
        for endpoint in ('GetStatus', 'GetMasterID'):
            rospy.wait_for_service(prefix + endpoint, timeout=2)
        status = rospy.ServiceProxy(prefix + 'GetStatus', SrvString)
        owner = rospy.ServiceProxy(prefix + 'GetMasterID', SrvTLSstring)
        current = bounded(status, 'get')
        if bounded(owner, 'get').data not in (0, 2) or current.data not in ('preReady', 'ready', 'pause'):
            raise RuntimeError('机器人状态或控制权不允许执行')
        if current.poseQueueSize or current.jointQueueSize:
            raise RuntimeError('存在其他排队动作')
        if SetBodyhubTo_setStatus(2) is not True:
            raise RuntimeError('未取得 ready 状态')
        acquired = True
        started = {'status': 'started', 'action': args.action}
        if args.action in ('nod', 'shake'):
            started.update(cycles=args.cycles, beat_ms=args.beat_ms)
        print(json.dumps(started, ensure_ascii=False), flush=True)
        if args.action in EXPRESSIONS:
            client_action.action(result['frames'])
        else:
            client_action.custom_action([], result['frames'])
        print(json.dumps({'status': 'sdk_returned', 'physical_verified': False,
                          'bodyhub_state': bounded(status, 'get').data}, ensure_ascii=False), flush=True)
    finally:
        if acquired:
            finishsend()
        rospy.signal_shutdown('游戏动作结束')


if __name__ == '__main__':
    main()
