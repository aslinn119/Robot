# D 模块合入与离线验证

2026-11-22，Windows PowerShell、Anaconda Python 3.12.7。源副本 `.work/Alice_D` 与个人仓库都在 `feat/d-platform-strategy`，基线为 `9d8e3c8`，本地配置的 `origin` 为 `https://github.com/aslinn119/Robot.git`。

- `hide_plan.py` 和 `test_hide_plan.py` 逐文件合入。C 在开局保存私有计划，按正式问题序号请求答复；重播读取已提交记录。
- `lab_head.py` 逐文件合入，独立预览回正、点头、摇头并写 JSONL。预览记录写到 `runtime/` 下可保持工作树干净。
- `game_gesture.py` 合入 `think`、`win`、`lose`，保留 `nod`、`shake` 的轨迹入口以及启动日志里的 `cycles`、`beat_ms`。

在仓库根目录运行以下命令可复查离线结果。

```powershell
$env:PYTHONPATH = "$PWD/robot_strategy/src"
& D:\Anaconda\python.exe -B -X utf8 -m unittest discover -s robot_strategy/tests -v
& D:\Anaconda\python.exe -B -X utf8 robot_strategy/scripts/verify_strategy.py
foreach ($action in 'center','nod','shake') {
    & D:\Anaconda\python.exe -B -X utf8 robot_strategy/scripts/lab_head.py $action --records runtime/d_head_preview
}
foreach ($action in 'think','win','lose') {
    & D:\Anaconda\python.exe -B -X utf8 robot_strategy/scripts/game_gesture.py $action
}
```

本轮 13 项单测通过。猜牌穷举访问 111 个节点，覆盖 56 条合法终止路径，最多 7 问。三项头部预览的 JSONL 均记录退出码 0。三项表情预览给出索引标称时长 4000、5000、7000 ms，现场源文件待核对；合成夹具验证了哈希拒绝、预设帧提取及原有全身点头、摇头的默认双轮轨迹。

待验证：机器人上的原始动作文件、厂商动作调用与实际姿态，及 C 正式问答和重播联调。
