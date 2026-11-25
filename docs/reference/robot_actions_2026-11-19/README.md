# 机器人已有动作资源与复用指南

盘点日期：2026-11-19。机器人 IP：10.129.108.111。通过 Z 盘只读查看文件；本轮没有导入厂商 Python 模块、执行动作、调用控制服务或修改机器人文件。

## 查阅入口

- 本页：按用途选动作、查调用方式和限制。
- [动作帧详细索引](frame_index.md)：文件、源码行号、数据变量、写入关节、关键帧变化关节、源码时间。
- [全部脚本索引 CSV](source_index.csv)：221 个 Python 文件的路径、调用名称和 SHA-256，可用编辑器或 Excel 搜索。
- [完整静态分析 JSON](source_index.json)：帧格式、头部关键角、依赖模块、调用行号及失败项。
- [语音映射与音频目录](voice_and_music_index.json)：25 条现有语音配置入口、配置文件哈希、13 个项目音频文件名。
- [本组 D 实测记录](../../records/2026-11-19_D_stage1.md)：与本页的源码盘点分开，避免混淆原版预设与本组试验。

建议先复用已有动作数据或已有执行接口，再加本组的控制权检查、超时、执行反馈和语音协调。不需要从零重写全部轨迹，但也不能把现有脚本不加检查地整体启动。

## 范围与证据边界

扫描了 `catkin_ws/src/` 下的 `ros_actions_node`、`leju_lib_pkg`、`ros_dance_node`、`ros_gesture_node`、`actexecpackage`、`headcontroller`、`leju_test_nodes` 七个包，共发现 221 个 Python 文件，215 个完成读取和 AST 解析；40 个文件含可提取的动作帧字面量，共 66 个变量。包含原版案例、学生变体、库与测试代码，**不是 66 个互不重复且已验收的动作**。同时列出 19 个 JSON/YAML 等文件路径，其中也有 CI 配置，不全是动作数据。

另外核对了语音入口配置和项目 Music 目录。没有穷尽机器人整个磁盘、其他用户目录或未导出的图形编辑器项目；文件名也不能证明来自厂商原版，个人改版以名称和源码为线索另行判断。读取期间其他同学可能改文件，因此本资料是一次逐文件快照，不是原子版本快照。哈希用于下次确认版本。

**下表时间均为源码标称值，不是现场测得时长。** 列表帧按各帧运动时间和停顿相加；贝塞尔帧记录时间轴最后一个时间点。真实用时还受初始化、起始姿态插值、通信、等待和音频影响。关节“关键帧变化”仅比较已写关键点；常量目标仍然会驱动机器人离开当前姿态。

## 优先考虑的独立脚本

以下相对路径均位于 `/home/lemon/robot_ros_application/catkin_ws/src/ros_actions_node/scripts/`，本地映射为 `Z:\robot_ros_application\catkin_ws\src\ros_actions_node\scripts\`。

| 动作 | 文件 / 数据 / 调用 | 源码时间 | 复用判断 |
| --- | --- | --- | --- |
| 点头 | `点头.py:12`，`u70b9u5934_frames`，`client_action.custom_action` | 时间轴到 2000 ms | ID22 关键角 20→0；写入 ID1～22。可研究俯仰轨迹，不能称头部专用调用 |
| 摇头 | `摇头.py:12`，`shake_head_frames`，`client_action.action` | 5 帧，共 3900 ms | ID21 为 0→-24→24→-24→0；ID13～18 也随帧变化，写入全身 |
| 举手 | `举手.py:12`，`hands_up_frames`，`custom_action` | 时间轴到 6900 ms | ID13 关键角 -150→59.2→0，其他关节仍有全身目标；幅度较大，需另做实机验收 |
| 伸展手臂 | `伸展手臂.py:12`，`u4f38u5c55u624bu81c2_frames` | 时间轴到 3000 ms | 写入全身；肩臂展开后收回，可作为演示参考 |
| 鞠躬 | `鞠躬.py:12`，`u97a0u8eac_frames` | 时间轴到 4800 ms | 身体及手臂姿态变化；与下文 `DemoFrame.bow` 不是同一组数据 |
| 下蹲并起身 | `下蹲.py:11`，`squat_frames`，`action` | 3 帧，共 3600 ms | 腿部、手臂一起变化；猜牌基础交互不必接入 |
| Say-yeah 舞蹈 | `Say-yeah舞蹈案例.py:12`，`dance_frames` | 时间轴到 69710 ms | 全身长动作，绑定 `say_yeah.mp3`；适合展示备选 |
| 武当太极 | `武当太极.py:11`，`tai_chi_frames` | 时间轴到 143200 ms | 全身长动作，绑定 `tai_chi.wav`；不作为简短反馈动作 |
| 宣讲动作 | `高职招生宣讲.py:12,16`，`bow_frames`、`speech_frames` | 两段分别到 3000 / 48400 ms | 包含鞠躬和讲话动作，音频 `Vocational_lecture.mp3`；可参考语言动作配合，不直接等同本组台词 |

以上均只查源码，本轮未运行。原版点头的 20°轨迹是参考依据，不是已确认的当前安全范围，也没有解决本组 5°点头未观察到的原因。

## 可直接作为数据参考的 DemoFrame

路径：`ros_actions_node/scripts/action/demo_frame.py`，类名 `DemoFrame`。这是已有帧数据类，不是一个“执行后自动展示全部动作”的独立入口。下列中文名按变量和轨迹作用途解释，实际表现待验证。

| 变量（行号） | 含义 / 用途 | 源码时间 |
| --- | --- | --- |
| `squat`（3） | 下蹲 | 2000 ms |
| `squat_to_stand`（8） | 下蹲再起身 | 3800 ms |
| `shake_head`（14） | 摇头伴随身体动作；不同于根目录摇头 | 5000 ms |
| `head_toward_face`（20） | 抬头朝向面部的姿态参考 | 4000 ms |
| `touch_leg`（25） | 手触腿动作 | 3500 ms |
| `snicker`（31） | 偷笑式表达，可作为趣味反馈备选 | 5000 ms |
| `bow`（40） | 鞠躬，包含停留姿态 | 7000 ms |
| `anthropomorphic_speech`（47） | 拟人讲话手势，适合研究讲规则时配合表达 | 5000 ms |
| `hug`（55） | 拥抱式动作 | 10000 ms |
| `bend_over`（65） | 弯腰 | 3000 ms |
| `pick_up_trash`（70） | 弯腰抓取/捡拾序列 | 6300 ms |
| `stand_on_one_foot`（83） | 单脚站立，贝塞尔数据 | 时间轴到 14000 ms |
| `dream_seeker_abbreviated_version`（85） | 命名为“追梦人简版”的长动作数据 | 时间轴到 179400 ms |

所有列出的帧数据都含全身目标。存在腿部、躯干和手臂运动，不能仅按变量名裁成安全的头部动作；提取局部前需要核对各关节映射及起止姿态。

## 其他动作资源和完整行为案例

| 类别 | 位置 | 说明 |
| --- | --- | --- |
| 石头、剪刀、布 | `ros_gesture_node/RPS_game/actions/{rock,scissors,paper}.py:12` | 各有 22 关节贝塞尔数据，时间轴到 2000 ms，并引用对应 WAV。实际手势效果未验证 |
| 舞蹈 ROS 服务 | `ros_dance_node/scripts/dance_node.py` | `ros_dance_node/dance_action`，类型 `DanceAction`。9 帧标称 18200 ms。请求虽有 `danceName`，回调没有按名称选择动作，只执行固定 `act_frames` |
| 踢球帧 | `ros_actions_node/scripts/action/kickball_frame.py:2` | `kick_ball_points_frames`，时间轴到 4700 ms；踢球案例还依赖视觉、行走、场地 |
| 原地踏步 | `ros_actions_node/scripts/原地踏步.py` → `check_gait/march_on_the_spot.py` | 前者是 shell 启动包装，不是独立帧列表 |
| 行走及复杂运动 | `S形曲线行走案例.py`、`上楼梯案例.py`、`避障案例.py`、`踢红球案例.py` | 完整行为案例，需环境与相应节点；不应当作静态动作预设 |
| 自平衡 / 抗扰动 | `自平衡案例.py`、`退出自平衡.py`、`抗扰动案例.py` | 涉及状态、步态或节点切换；抗扰动脚本含 kill/launch 操作 |
| 面部 / 声源跟随 | `人脸追踪案例.py`、`人脸追踪+语音对话.py`、`全方位声源定位.py` | 持续行为，会与固定头部动作争用；声源定位脚本含节点终止与 launch |
| 学生改版 | `nod_head_wuling.py`、`nod_bezier_wuling.py`、`shake_head_wuling.py`、`点头_liujie.py`、`摇头改幅度_liujie.py` 等 | 单独保留来源；存在动态生成帧、参数或依赖原脚本的情况。文件存在不等于已验收 |

`ros_gesture_node/scripts/gestures.py` 中的“比心、点赞、OK、胜利”等主要是**视觉手势识别标签**，不能据此声称机器人具备这些手部动作。

## 已有调用接口：优先复用什么

路径前缀：`/home/lemon/robot_ros_application/catkin_ws/src/leju_lib_pkg/`。

| 入口 | 实际源码行为 | 接入建议 |
| --- | --- | --- |
| `src/lejufunc/client_action.py` 的 `action(act_frames)` | 接收 `(22关节角,运动毫秒,暂停毫秒)` 列表，先读取当前缓存并向传入列表插入起始帧，再插值发送 | 重复调用前深拷贝帧，避免原数据被反复插入起始帧；追加超时与请求去重 |
| 同文件 `custom_action(music, act_frames)` | 接收按关节编号组织的贝塞尔关键点与音频列表，调用 `send_custom_bezier` | 可复用曲线数据；先检查全身目标、音频依赖、等待和清理行为 |
| `src/lejufunc/ServoJointTrajectory.py:81` 的 `SERVO.HeadJointTransfer(arraySend,time)` | 读取缓存 `[20:]`，向 `HeadPosition` 发插值帧，控制 ID=2，时间单位毫秒 | 这是现成的头部专用接口；后续可对比本组适配器，不能把所有原动作包装都当头部专用 |
| `lejulib.py` 的 `node_initial()` | 默认 `stateJump=True`，会请求控制状态；导入时还加载多个库并建立 ROS 对象 | 检查控制权，避免将导入当成无副作用读取 |
| `src/lejufunc/client_logger.py:76` 的 `finishsend()` | 可调用 reset_bodyhub，结束音频播放，发布结束消息 | 会影响共享状态；不能直接放入本组任意 `finally` 而不审查 |
| `src/lejufunc/ServoJointTrajectory.py:98` 的 `MotoWait()` | 转调 `WaitForActionExecute` 等待控制器状态 | 当前实现没有本组要求的总体超时；返回也不是视觉到位证明 |
| `actexecpackage/scripts/ActExecPackageNode.py:136` | 执行 `os.system(actNaemString)` | 是旧的命令执行框架，不是经过验证的命名动作注册表；不向它拼接用户自然语言 |

`client_action.custom_action` / `music_action` 结束时还会通过 shell 清理 `play` 进程；这可能影响其他播报。音频播放器用 `play`，依赖音频文件和相关软件。当前 `Music/` 中找到 `say_yeah.mp3`、`tai_chi.wav`、`Vocational_lecture.mp3`、三种猜拳 WAV 及情绪音频等共 13 个文件，详见 JSON。

这些旧封装提供了轨迹与音频并发方式，但不等于已经与 A 的实时 TTS 完成协调。**本组正式动作时间仍需根据台词与播报开始/结束事件安排，不能照抄预设时长。**

## 语音、按钮与源码的关系

当前 `ros_AIUI_node/config/VoiceControlConfig.json` 已将点头、摇头、举手、伸展手臂、下蹲、跳舞、太极等映射到对应脚本；前进、后退、左右平移、左右转向映射到函数名。配置共 25 项，含检测和停止等非动作项。这里只验证了磁盘配置，未触发语音、未确认运行中的节点已经加载同一版本。

`ros_socket_node/scripts/transfer.py` 和 `execute_demo_programe.py` 也把程序目录指向 `ros_actions_node/scripts`，支持“预设主要是这些脚本与帧数据”的判断。源码引用 `/home/lemon/.lejuconfig/BackBtnsConfig.json` 作为背部按键映射，但本轮 Z 盘下该文件不存在，**没有确认实体按键当前绑定了什么**。

## 本组建议的复用顺序

1. 猜牌基础反馈：点头、摇头、回正；重点核对俯仰实际执行和 A 的播报节奏。现有头部专用接口值得优先比较。
2. 开场与结束：评估鞠躬、举手或简短讲话手势；先核对腿部姿态和幅度，再实测。
3. 趣味扩展：`snicker`、拟人讲话、猜拳等，属于备选，不宣称已可直接接入。
4. 长舞蹈、太极、单脚站立、踢球、行走等保留资料即可，是否加入由项目需求决定。

此顺序是基于代码范围和猜牌场景的建议，不是实机比较结果。本轮没有为任何原版预设新增“已通过”状态。

## 未读取成功的项目

Z 盘拒绝读取：`my_battery_monitor.py`、`my_battery_monitor_liujie.py`、`点头_bezier100_liujie.py`、`点头_bezier500_liujie.py`、`tracking/shake_head_my.py`（均在 ros_actions_node/scripts 下）。`compete/stair_convert.py` 无法按 UTF-8 解码。原始错误已写入 JSON，没有改权限或猜测内容。

## 更新资料

Z 盘可读时，在本地仓库根目录运行：

```powershell
& D:\Anaconda\python.exe -X utf8 robot_strategy\tools\catalog_actions.py --root Z:/robot_ros_application --output docs/reference/robot_actions_新日期
```

该脚本只生成 Python 源码与帧索引，不执行机器人代码。输出目录必须在被扫描源码外。语音/音频 JSON 与本页为本次人工核对资料，不会随上述命令自动刷新；更新时需重新核对，保留日期和未验证项。
