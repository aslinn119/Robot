#!/usr/bin/env python3
"""静态盘点厂商源码；不导入、执行或修改被扫描文件。"""
import argparse
import ast
import csv
import hashlib
import json
import os
from pathlib import Path

SCOPES = ('ros_actions_node', 'leju_lib_pkg', 'ros_dance_node',
          'ros_gesture_node', 'actexecpackage', 'headcontroller', 'leju_test_nodes')


def name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return name(node.value) + '.' + node.attr
    return ''


def frame_summary(value):
    try:
        if isinstance(value, dict) and value and all(str(k).isdigit() for k in value):
            series = {int(k): [(float(p[0][0]), float(p[0][1])) for p in v]
                      for k, v in value.items()}
            if not all(series.values()):
                return None
            return {'format': 'bezier', 'joint_ids': sorted(series),
                    'varying_joint_ids': sorted(k for k,v in series.items() if len(set(x[1] for x in v)) > 1),
                    'timeline_end_ms': max(x[0] for v in series.values() for x in v),
                    'head_key_values': {str(k): [x[1] for x in series[k]] for k in (21,22) if k in series}}
        if isinstance(value, (list, tuple)) and value and all(
                len(v) == 3 and isinstance(v[0], (list, tuple)) and len(v[0]) == 22
                and all(isinstance(x, (int, float)) for x in v[0]) for v in value):
            return {'format': 'frame_list', 'joint_ids': list(range(1,23)),
                    'varying_joint_ids': [k+1 for k in range(22) if len(set(v[0][k] for v in value)) > 1],
                    'frame_count': len(value),
                    'nominal_total_ms': sum(v[1]+v[2] for v in value),
                    'head_key_values': {str(k): [v[0][k-1] for v in value] for k in (21,22)}}
    except (TypeError, ValueError, IndexError, KeyError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='Z:/robot_ros_application')
    parser.add_argument('--output', default='docs/reference/robot_actions_2026-11-19')
    args = parser.parse_args()
    root, output = Path(args.root), Path(args.output)
    if not root.is_dir():
        raise SystemExit('源目录不存在，停止；不覆盖现有资料')
    if root.resolve() == output.resolve() or root.resolve() in output.resolve().parents:
        raise SystemExit('输出必须在被扫描源码目录之外')
    rows, errors, assets = [], [], []
    for scope in SCOPES:
        folder = root / 'catkin_ws/src' / scope
        if not folder.is_dir():
            errors.append({'path': str(folder), 'error': '目录不存在或无法访问'})
            continue
        for current, dirs, files in os.walk(folder, onerror=lambda e: errors.append({'path': e.filename, 'error': str(e)})):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'build', 'devel')]
            for filename in sorted(files):
                path = Path(current) / filename
                if path.suffix.lower() in ('.json', '.yaml', '.yml', '.act', '.mtn', '.d6a'):
                    assets.append(path.relative_to(root).as_posix())
                if path.suffix != '.py':
                    continue
                rel = path.relative_to(root).as_posix()
                row = {'path': rel, 'remote_path': '/home/lemon/robot_ros_application/' + rel,
                       'sha256': '', 'parse_status': '', 'calls': [], 'frames': [], 'imports': []}
                try:
                    raw = path.read_bytes()
                    row['sha256'] = hashlib.sha256(raw).hexdigest()
                    tree = ast.parse(raw.decode('utf-8-sig'))
                    row['parse_status'] = '静态解析成功；未运行'
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            call = name(node.func)
                            if call and any(term in call.lower() for term in (
                                    'action', 'servo', 'joint', 'walk', 'gripper', 'node_initial', 'finishsend')):
                                row['calls'].append({'name': call, 'line': node.lineno})
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            row['imports'].append(node.module if isinstance(node, ast.ImportFrom)
                                                  else ','.join(a.name for a in node.names))
                        if isinstance(node, ast.Assign):
                            try:
                                summary = frame_summary(ast.literal_eval(node.value))
                            except (ValueError, TypeError, SyntaxError):
                                summary = None
                            if summary:
                                row['frames'].append(dict(summary, variable=','.join(name(t) for t in node.targets),
                                                          line=node.lineno))
                except Exception as exc:
                    row['parse_status'] = '解析失败：' + str(exc)
                    errors.append({'path': rel, 'error': str(exc)})
                rows.append(row)
    rows.sort(key=lambda r: r['path'])
    output.mkdir(parents=True, exist_ok=True)
    report = {'source': str(root), 'scopes': list(SCOPES), 'files': rows,
              'data_asset_paths': sorted(assets), 'errors': errors,
              'limitations': '只覆盖列出的七个包；字面量提取不执行循环、分支或函数，不证明运行可用、时长或物理动作。'}
    (output / 'source_index.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # CSV 只是索引，不包含可执行指令；全量详情见 JSON。
    with (output / 'source_index.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['文件', '机器人路径', '读取状态', '调用名称', '动作数据变量', 'SHA256'])
        for row in rows:
            writer.writerow([row['path'], row['remote_path'], row['parse_status'],
                             '; '.join(sorted(set(c['name'] for c in row['calls']))),
                             '; '.join(f['variable'] for f in row['frames']), row['sha256']])
    lines = ['# 静态动作数据索引', '', '自动提取字面量；时间是源码标称值，不是实测时间。'
             '“变化关节”只比较关键帧，恒定目标也会被写入。', '',
             '| 文件与行号 | 数据变量 | 格式 | 写入关节 | 关键帧变化关节 | 源码时间 |',
             '| --- | --- | --- | --- | --- | --- |']
    for row in rows:
        for frame in row['frames']:
            timing = frame.get('nominal_total_ms', frame.get('timeline_end_ms'))
            lines.append('| {}:{} | {} | {} | {} | {} | {} ms |'.format(
                row['path'], frame['line'], frame['variable'], frame['format'],
                ','.join(map(str,frame['joint_ids'])), ','.join(map(str,frame['varying_joint_ids'])), timing))
    (output / 'frame_index.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'files': len(rows), 'files_with_literal_frames': sum(bool(r['frames']) for r in rows),
                      'frame_variables': sum(len(r['frames']) for r in rows),
                      'data_assets': len(assets), 'errors': errors}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
