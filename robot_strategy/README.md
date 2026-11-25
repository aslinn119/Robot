# 策略与行为

负责人：D。开发分支 `feat/d-platform-strategy`。本模块包含离线容错推理、七问路径验证和头部动作示例。

## 当前证据（2026-11-19）

- 离线策略：1～10、严格大于/小于/等于、至多一次谎言；全树验证 111 个合法节点、56 个终止回答路径，最大深度 7。
- 机器人 Python 3.8.10 已跑通首版 8 项测试和全树验证；本地后续新增测试见开发记录。
- 慢速回正：控制器返回完成，现场确认平稳回正。
- 首版摇头（左右各 5°、每段 1.5 秒）：现场确认发生，但幅度和速度偏小。
- 首版点头（5°）：控制器返回完成，但现场没有观察到点头，**未通过实机验收**。
- 当前本地新版：点头 10°、摇头左右各 12°、每段 1 秒，增加各转折点缓存反馈。**尚未上传、尚未实测**，机器人已交给同学调试。

详细证据与限制见 [D 阶段一记录](../docs/records/2026-11-19_D_stage1.md)。

扩展动作前先查 [机器人已有动作资源与复用指南](../docs/reference/robot_actions_2026-11-19/README.md)：包含原版脚本、DemoFrame 数据、调用接口、语音映射和完整索引，避免从零重复编写。

## 本地快速运行

在仓库根目录的 Windows PowerShell 执行，无需 ROS：

```powershell
$env:PYTHONPATH = "$PWD\robot_strategy\src"
& D:\Anaconda\python.exe -X utf8 -m unittest discover -s robot_strategy\tests -v
& D:\Anaconda\python.exe -X utf8 robot_strategy\scripts\verify_strategy.py
& D:\Anaconda\python.exe -X utf8 robot_strategy\scripts\strategy_demo.py
& D:\Anaconda\python.exe -X utf8 robot_strategy\scripts\head_action.py nod
& D:\Anaconda\python.exe -X utf8 robot_strategy\scripts\head_action.py shake
```

后两条只预览；只有显式 `--run` 才导入 ROS 并发送动作。核心仅使用 Python 标准库。

## 动作与语言的时序约定（用户确认）

当前普通动作每段 1 秒、回正至少 3 秒均为独立测试的暂定值，不是最终交互时长。后续必须与 A 的语音模块共同调整：结合具体台词长度、播报开始与结束反馈，确定动作何时开始、动作速度及是否需要停顿。不能仅等待固定秒数就认定播报结束；动作完成和播报完成分别反馈，由集成层协调下一轮收音。动作总时长不必机械地等于台词时长，但节奏需匹配。若协调需要超出当前试验边界，应先修改并验证轨迹规划，不能直接绕过限速。

## 策略接口（D 的本地原型格式）

```python
from robot_strategy.strategy import suggest, answer_suggestion

history = [{"kind": "gt", "number": 5, "answer": True}]
result = suggest(history, remaining=6)
# result: s0、s1、status、proposal
# proposal 为 {"kind": "gt"/"lt"/"eq"/"submit", "number": ...}，或 None
```

输入仅含已确认的公开问答；不传秘密值、待确认问题、取消或重播事件。这里的历史格式由 D 明确定义，尚未与 C 的实际代码做联调。`remaining` 必须等于 `7-len(history)`。

- `s0`：与历史无矛盾的数字；`s1`：恰有一次矛盾的数字。
- `question`：建议继续提问；`certain`：唯一候选，建议最终提交。
- `inconsistent`：候选为空，应由裁判暂停核查；`insufficient`：剩余次数不能保证辨认，不伪造确定答案。
- 搜索以剩余问数和候选不一致数为状态，缓存子问题；只有所有非空合法回答分支都可解时才采用问题。全树验证使用独立直接真值计算核对候选，不以贪心平衡代替证明。
- `answer_suggestion(secret, kind, number, lies_used=0, use_lie=False)` 仅供机器人藏牌侧调用；默认全真，显式请求说谎时检查额度。建议本身不扣额度，裁判确认后提交。猜牌侧不调用此私密接口。
- 不直接发送 C 事件、不修改次数或胜负；局号、请求号、确认、去重和角色权限由后续适配层与 C 共同落实。

## 机器人上的动作入口

机器人：`lemon@10.129.108.111`。首版独立目录：`/home/lemon/team_project_d/alice_stage1_20261119`，不改厂商文件。

**下列是当前本地新版的命令，需在机器人空闲后先同步新版并核对哈希。远端旧版仍默认 5°。**

在机器人 Linux 终端执行，确认现场无人控制、姿态稳定、头部无遮挡：

```bash
source /opt/ros/noetic/setup.bash
source /home/lemon/robot_ros_application/catkin_ws/devel/setup.bash
cd /home/lemon/team_project_d/alice_stage1_20261119
# 调用前由现场协调，避免声源转头抢占
timeout 5 rosservice call /aiui/pause_head_toward_sound true
timeout 25 python3 robot_strategy/scripts/head_action.py center --run
timeout 25 python3 robot_strategy/scripts/head_action.py nod --amplitude 10 --seconds 1 --run
timeout 25 python3 robot_strategy/scripts/head_action.py shake --amplitude 12 --seconds 1 --run
```

必须一条一条运行并现场核验。恢复声源转头由当次使用者决定：`rosservice call /aiui/pause_head_toward_sound false`。本次交接时暂停设置尚未恢复。

只发布 `/MediumSize/BodyHub/HeadPosition` 的两个角，控制 ID 为 2；不调用全身 reset/stop/setStatus。首发要求 BodyHub 为 ready/pause、ID=2、全身队列为空；运行时持续检查状态。ID=2 为共享编号，**不是独占锁**，需现场协调其他发布者。

普通动作从 ±15° 内起步；回正可从 ±30° 内起步，至少 3 秒，峰值约 7.5°/秒以内。点头幅度上限 15°、摇头 20°；目标水平限 ±30°、俯仰限 ±20°。这些是代码试验边界，**不是实机已标定极限**。普通动作返回开始角，`center` 返回零角。

输出 `started`、`waypoint_cache_reached`、`controller_completed` 或 `failed`。中间与结束反馈均来自指令角缓存，不是编码器实测；`physical_verified` 始终为 false，现场观察单独记入记录。超时/异常停止继续发送，但不保证清除已经进入 BodyHub 的头部队列，也不等于硬件急停。

## 尚未完成

新增原版全身游戏变体：`scripts/game_gesture.py`，快照为 `config/game_gestures_v1.json`。用户已观察原版点头并认可身体姿态，要求更快且连续两次；本变体保留原版基姿态及角度，点头 20°两次、摇头 ±24°两轮，每段暂定 500 ms，先用 1000 ms 进入基姿态。源码标称总时间分别为 3000/4000 ms，不等于实际总时长。未实测变体；不覆盖原脚本。

预览：`python3 robot_strategy/scripts/game_gesture.py nod`；在已协调控制权和声源转头、现场有保护时，执行入口为 `timeout --signal=INT --kill-after=5 30 python3 robot_strategy/scripts/game_gesture.py nod --run`，摇头将 `nod` 换成 `shake`。次数 `--cycles`、节拍 `--beat-ms` 可配置，后续与 A 的语言反馈协调。执行复用厂商 `custom_action`，会写入全部 22 关节并沿用厂商收尾复位与音频清理；`sdk_returned` 不证明实机效果。超时是进程边界，不等同硬件急停。

新版动作实测、点头未观察到的根因、物理角反馈、语音动作协调、跨进程动作去重、C 接口联调与 ROS 节点集成、catkin 构建均待完成。阶段一已交付原型和真实限制，不能称整机完成。
