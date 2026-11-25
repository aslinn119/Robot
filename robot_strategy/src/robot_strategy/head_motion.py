"""头部轨迹规划；角度单位为度，限制为本次小幅试验边界。"""
import math


def trajectory(action, start, amplitude=5.0, seconds=1.5, hz=50):
    if action not in ('nod', 'shake', 'center'):
        raise ValueError('未知动作')
    # 回正单独允许从 ±30 度以内起步；普通动作仍要求 ±15 度。
    # 这些是示例操作边界，不是厂商标定的机械极限。
    limit = 30 if action == 'center' else 15
    if len(start) != 2 or not all(math.isfinite(x) and abs(x) <= limit for x in start):
        raise ValueError('起始头部角超出本示例范围，须现场核查')
    max_amplitude = 20 if action == 'shake' else 15
    if not math.isfinite(amplitude) or not 0 < amplitude <= max_amplitude:
        raise ValueError('幅度超出本动作的试验范围')
    if not math.isfinite(seconds) or not 1 <= seconds <= 5 or hz != 50:
        raise ValueError('每段 1～5 秒，固定 50 Hz')
    if action == 'center':
        # 三次平滑插值的峰值速度不超过 7.5 度/秒，且至少三秒。
        seconds = max(3., max(abs(x) for x in start) / 5.)
    targets = {'nod': [(start[0], start[1] + amplitude), tuple(start)],
               'shake': [(start[0] + amplitude, start[1]),
                         (start[0] - amplitude, start[1]), tuple(start)],
               'center': [(0.0, 0.0)]}[action]
    if any(abs(point[0]) > 30 or abs(point[1]) > 20 for point in targets):
        raise ValueError('目标角超出本示例水平 ±30 度、俯仰 ±20 度边界')
    result = []
    previous = start
    for target in targets:
        for step in range(1, int(seconds * hz) + 1):
            t = step / int(seconds * hz)
            smooth = t * t * (3 - 2 * t)
            result.append(tuple(a + (b - a) * smooth for a, b in zip(previous, target)))
        previous = target
    return result
