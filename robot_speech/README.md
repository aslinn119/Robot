# robot_speech — A 模块（语音交互）

纯 Python 的离线中文意图解析 + AIUI IAT 结果组装。
**不依赖 ROS**，可在 Windows 上独立运行和测试；ROS 接入留到上机阶段。

> **协议版本：TEAM_INTERFACE v1.0（2026-11-26）**
> 现行 A→C 链路是 **HTTP 拉命令**（`http_client.py`）→ 命令循环（`command_agent.py`）
> → 两条命令处理器（`speech_commands.py`），协议正本见仓库根目录 `TEAM_INTERFACE.md`。
>
> **v0.2 的进程内编排已移除**（`session.py` / `referee_client.py` / `referee_protocol.py`
> 及对应测试、`check_c_interface.py`、`dialogue_demo.py`、`referee_demo.py`）。
> 它们按「A 自己提议、自己开确认窗口」的旧协议编写，v1.0 把编排权交给 C 之后已无用途。
> 下面 §10 之后仍有部分段落描述那套流程，**仅作历史对照**，不要照着写代码。

本目录刻意与小组仓库 `robot_speech/` 保持同构（`src/robot_speech/` +
`scripts/` + `tests/`），整包复制即可，无需改动目录结构。

> 当前状态：离线部分已完成并通过 368 项测试；A→C 走 v1.0 的 HTTP 命令循环，
> 已用本地假 C 服务跑通全链路。**尚未**与 C 的 8780 服务真实联调、
> **尚未**打通 IAT 出口。

## 上机实测（2026-11-26 · Roban / Ubuntu 20.04 / Noetic）

在实验室机器人上实测，解决了三个悬了很久的问题中的两个：

| 问题 | 结论 | 依据 |
| --- | --- | --- |
| 播报完成信号从哪来 | **`/aiui/play_end`**（`std_msgs/Empty`，`/ros_aiui_node` 发布，原本无订阅者） | `rostopic info`；一次 `text_to_speak` 只产生一条，出现在说完之后 |
| `text_to_speak` 是否阻塞 | **不阻塞**，约 1 秒就返回，只代表「已提交」 | `time rosservice call` → `real 0m0.990s` |
| 识别出口是否存在 | `/aiui/iat` 与 `/aiui/nlp` **都在** | `rostopic list`（内容待验证） |

`RosSpeaker` 已改为订阅 `/aiui/play_end` 判定完成，实测返回
`PlaybackStatus.COMPLETED`、`elapsed=6.7s`，不再是 `UNVERIFIED`。

服务接口细节：请求字段是 `text`（不是 `data`），响应字段是 `is_success`。

> 已知边界：唤醒应答也发 `play_end`。若在它尚未播完时发起新播报，
> 可能把它的结束信号误算成我们的。靠「上一个播报没结束就不发下一个」的半双工约束规避。

---

---

## 1. 目录

```text
robot_speech/
├── src/robot_speech/
│   ├── __init__.py        对外入口
│   ├── intents.py         意图 / 比较符 / 拒绝原因 / ParseResult
│   ├── speech_parser.py   中文意图解析（纯文本）
│   ├── iat_parser.py      AIUI IAT 事件解析与拼接
│   ├── referee_protocol.py A→C 事件构造（纯函数）
│   ├── referee_client.py  A→C 会话层（request_id / 确认窗口绑定 / 重试）
│   ├── ports.py           设备端口：SpeechInput / SpeechOutput
│   ├── simulated_devices.py 离线模拟设备
│   ├── eventlog.py        JSONL 事件日志
│   ├── probe.py           设备探测记录（无 rospy）
│   └── session.py         交互流程编排（播完才开窗、窗口归属判定）
├── scripts/
│   ├── speech_cli.py      单句 / 交互 / IAT 回放
│   ├── referee_demo.py    A→C 时序演示（用测试替身）
│   ├── dialogue_demo.py   交互流程演示（三条场景）+ 落日志
│   ├── device_probe.py    上机诊断入口（不需要 C）
│   └── speech_node.py     ROS 薄壳（只在机器人上运行）
├── evidence/logs/         三条场景的 JSONL 日志（可复现，见 §12）
├── tests/
│   ├── test_speech_parser.py
│   ├── test_iat_parser.py
│   ├── test_referee_client.py
│   ├── test_session.py
│   ├── support/fake_referee.py   ← C 的最小测试替身，仅测试用
│   └── fixtures/simulated_iat_events.jsonl   ← 全部是模拟数据
├── pytest.ini
└── README.md
```

## 2. 快速开始

```powershell
# 在 A_speech\robot_speech 目录下
python -m pytest                                   # 跑全部测试
python scripts\speech_cli.py "大于五吗"             # 单句
python scripts\speech_cli.py --json "大于十五吗"    # 输出统一 JSON
python scripts\speech_cli.py                       # 交互模式
python scripts\speech_cli.py --iat tests\fixtures\simulated_iat_events.jsonl
python scripts\referee_demo.py                     # A→C 时序演示
python scripts\dialogue_demo.py                    # 交互流程演示（三条场景 + 落日志）
python scripts\dialogue_demo.py --log-raw          # 同上，日志里带原始语音文本
```

## 3. 支持表达清单（阶段一交付物）

| 类别 | 用户说法 | 输出 |
| --- | --- | --- |
| 大于 | `大于五吗` `比五大吗` `超过七吗` `高于二吗` `大过三吗` | `ASK` / `GT` / n |
| 小于 | `小于八吗` `比五小吗` `低于三吗` `少于四吗` `小过二吗` | `ASK` / `LT` / n |
| 等于 | `是七吗` `等于九吗` `就是三吗` `是数字十吗` | `ASK` / `EQ` / n |
| 最终提交 | `我确定是七` `确定是七` `最终答案是十` `最终提交五` `答案是三` `我的答案是八` `我猜是九` `我选六` | `FINAL` / n |
| 确认 | `确认` `确定` `我确认` `我确定` `确认无误` `可以确认` `确认一下` `就这样` | `CONFIRM` |
| 取消 | `取消` `取消问题` `取消这次` `算了` `不要了` `撤销` `不提了` | `CANCEL` |
| 肯定 | `是` `是的` `对` `对的` `嗯` `好` `好的` `可以` `行` `没错` `正确` `没有问题` | `AFFIRM` |
| 否定 | `不是` `不对` `不` `否` `没有` `不好` `不确认` `否认` | `DENY` |
| 暂停 | `暂停` `暂停游戏` `暂停一下` `先停一下` `等一下` `等一等` `停一下` | `PAUSE` |
| 继续 | `继续` `继续游戏` `接着来` `接着说` `恢复` `继续提问` | `RESUME` |
| 退出 | `退出` `退出游戏` `结束游戏` `不玩了` `我要退出` `结束` | `EXIT` |

**数字**：1～10，同时接受中文（一/二/两/…/十）与阿拉伯数字，接受全角数字。
**归一化**：全角转半角、去空白与标点、剥句尾语气词（吗/呢/啊/呀/吧/么/嘛）、
剥句首填充词（那么/请问/那个/麻烦/嗯/呃/啊/哦/那）。**只做无语义清洗，不改实词。**

两条清洗的边界（评审提出的回归项，已修并留测试）：

- **数字的写法必须在清洗前判定**。负号、小数点、数字之间的空格一旦被删掉，
  `大于-5吗` 会变成 `大于5`、`是1.0吗` 和 `是1 0吗` 会变成 `是10`。
  现在先由 `has_unsafe_number_format()` 拦下；数字整体两侧有空格（`大于 5 吗`）仍然正常。
- **句末「吗」表达疑问，不是噪声**。`确认吗` 不是 `确认`，`我确定是七吗` 不是最终提交。
  归一化仍会剥掉它（句式模板需要），但解析前由 `has_question_particle()` 记录，
  非 ASK 类意图带疑问语气一律拒绝。

### 明确拒绝的输入

| 输入 | 拒绝原因 | 说明 |
| --- | --- | --- |
| `大于十五吗` `大于零吗` `大于一百吗` `最终答案是十五` | `OUT_OF_RANGE` | 数字不在 1～10 |
| `大于五而且小于八吗` `大于五，小于八吗` | `COMPOUND` | 两问合一 |
| `大于五小于八` `是七还是八` `五和八` | `MULTIPLE_NUMBERS` | 一句话多个数字 |
| `是不是七` `不是七吗` | `NEGATION_AMBIGUOUS` | 否定歧义，不猜 |
| `大于等于五吗` `不小于五吗` `不等于五吗` | `UNSUPPORTED_OPERATOR` | 规则只允许严格比较 |
| `大于-5吗` `是1.0吗` `是1 0吗` `是.5吗` `是1,0吗` `是1。0吗` | `INVALID_NUMBER_FORMAT` | 负数、小数、被空格或分隔符拆开的数字——清洗会把它改写成合法输入，所以在清洗前拒绝 |
| `确认吗` `确认？` `我确定是七吗` `是吗` | `UNEXPECTED_QUESTION` | 句末疑问语气词或问号把陈述变成提问，不能当成确认或提交 |
| `大于` `五` `今天天气不错` `鲁班鲁班` | `NO_INTENT` | 无匹配句式 |
| 空串 / 纯标点 | `EMPTY` | |
| `None` / 数字 / bytes / 列表 | `FORMAT_ERROR` | `parse()` 不抛异常 |
| 超过 60 字 | `TOO_LONG` | 防噪声 |

## 4. 对外接口（已与小组协商的 5 个字段）

```python
from robot_speech import parse

result = parse("大于五吗")
result.to_dict()
# {"intent": "ASK", "operator": "GT", "value": 5,
#  "confidence": 1.0, "raw_text": "大于五吗"}
```

拒绝时：`{"intent": "UNKNOWN", "operator": None, "value": None, "confidence": 0.0, "raw_text": ...}`。

- `confidence` 目前只有两种取值：**1.0（精确句式命中）/ 0.0（拒绝）**。
  它不是模型置信度，**不要**在没拿到实机数据前赋予概率含义。
- `to_debug_dict()` 额外给出 `normalized_text` / `accepted` / `reason`，只用于日志与 CLI。
- 调试视图与统一视图分离，是为了避免把内部字段泄漏进接口。

### AFFIRM / DENY 的语义由阶段决定

`是`、`对`、`不是` 在「确认窗口」里等于确认/取消，在「回答窗口」里等于 `yes`/`no`
（见 `docs/player_hides_v03.md`「「是」要根据当前环节解释」）。
**解析器只输出词面含义，由阶段二适配层结合裁判返回的 `phase` 决定映射**——A 不自行判断阶段。

## 5. 设计决策

| 决策 | 理由 |
| --- | --- |
| 句式用「骨架 + 精确匹配」，不用模糊匹配 | 项目方案要求「拒绝或要求重新表达，而不是猜测」。模板可枚举、可审计 |
| 拒绝原因用枚举而不是字符串 | 上层可统计、可分层处理（越界提示 vs 复合提示） |
| 控制词整句匹配，且**先于**数字抽取 | 「等一下」「先停一下」里含中文数字，否则会被误判成提问 |
| `parse()` 对任何输入都不抛异常 | ROS 回调里直接调用，不能让坏消息把节点打挂 |
| 数字解析自实现，不引第三方库 | 规则只要 1～10，加个中文数字库属于过度设计 |
| IAT 组装规则全部标注为「假设」 | 没有真实样本，不能把推断写成结论 |

## 6. 测试

```powershell
python -m pytest
# 304 passed in 0.25s   （Python 3.12.14 / pytest 9.2.0）
python scripts\referee_demo.py                       # A→C 时序演示
python scripts\dialogue_demo.py                      # 交互流程演示 + 落日志
python -m pytest tests\test_referee_client.py -v      # 只看 A→C 时序
python -m pytest tests\test_session.py -v             # 只看交互流程
python -m pytest tests\test_attribution.py -v         # 只看窗口归属与探测
```

上机时（机器人上，先 source ROS 与厂商工作空间，然后从模块根目录运行）：

```bash
python3 scripts/device_probe.py
```

完整说明与参数见 §13。

覆盖交接文档「任务 3」的 10 类场景：正常比较、等于、最终确认、暂停继续、
1～10 边界、非法数字、复合、否定、多数字、空白与异常输入；另加控制意图、
归一化、数字抽取、接口结构与不变量、`parse()` 不抛异常，
以及清洗边界回归（`INVALID_NUMBER_FORMAT`、`UNEXPECTED_QUESTION`）。

IAT 部分覆盖：字典/JSON 字符串/字节输入、缺字段、坏 `cw`、坏 `ls`、
空负载、非法 JSON、非法 UTF-8；累积更新、重复片段、迟到短片段、修订、
最终结果、空片段、自动开始新句、`reset()`、事件序号、fixture 回放；
两种组装模式、模式参数校验、重复最终事件去重、中间有新事件时同名句子仍被接受。

A→C 适配层覆盖：payload 映射、`action_for` 路径判定、确认窗口绑定、
取消后旧确认迟到、旧确认不带取消、有效确认只生效一次、同 request_id 重试、
同编号不同内容冲突、旧局拒绝、重复响应不覆盖状态、timestamp 开关与重试稳定性。

交互流程覆盖：播完才开窗、播报失败/超时不开窗、UNVERIFIED 默认拦下（诊断模式可放行）、
只重播不重新提议、取消后旧确认被本地拒收、新问题作废旧窗口、
同一待确认项重开窗口后第一扇窗的结果仍被拒、未知窗口 key、无窗口时「确认」与「是」的处理、
有效确认只生效一次、重播不影响问答、C 拒绝上报、整场脚本运行、事件时间线记录、
日志上下文与 JSONL 落盘、原始文本默认不记。

窗口归属覆盖：到达早于窗口生效判过期（即使 key 一致）、到达晚于生效可接受、
无时间戳的离线输入不受影响、UNKNOWN 归属只观察不提交（确认与取消都是）、
ARRIVAL 默认拒收、ARRIVAL 显式放开后才提交且记 inferred、CAPTURE 记 captured、
A 的确认在 B 开窗后到达时 B 仍待确认且 C 请求数不变、
探测器的消息计数与观察窗口统计、无参数启动与参数覆盖。

> ⚠️ IAT 测试**全部基于模拟数据**（每条都带 `_simulated: true`）。
> 通过只说明「按当前假设的逻辑自洽」，**不构成实机验证**。

## 7. 假设与遗留问题

### IAT（最高优先级）

1. `ls` 字段在最终结果时的真实取值与语义，仍是按 `parse_iat()` 推断的。
2. **`ws` 是累积式还是增量式，尚未确定**。`IatAssembler(mode="cumulative"|"delta")`
   显式暴露两种假设，默认 `cumulative`（与 `parse_iat` 的用法一致）。
   若真实事件是增量式却用了默认模式，`大于` + `五吗` 会拼成 `五吗`——
   反过来用 `delta` 接累积式事件会重复叠加。**必须用真实样本选定后再接入游戏。**
3. **一句话的边界未定义**：一次唤醒对应几次 VAD、事件如何切分、何时该 reset，
   全部未知。当前靠 `is_final` 与自动重置兜底。
4. 迟到短片段的「前缀判定」是保守选择：宁可丢弃一次合法的缩短修订，也不截断已识别文本。
5. 最终结果去重只覆盖「最终事件之后**紧邻**的重复推送」；中间隔了其他事件就不再算重复，
   否则玩家连说两遍同一句话会被误吞。
6. `cw` 是同一位置的 n-best 候选，只取 `cw[0]`（与参考实现一致）；不做多候选重排。
7. **没有真实 IAT 样本**，也没有证据表明 IAT 结果能进入统一解析器。

### 解析器

8. 句式是**严格枚举**，真实用户会有「大于五的吧」「五以上的」等说法，目前会 `NO_INTENT`。
   扩充句式必须同时补测试，且不能放宽到「猜测」。
9. 「十分」「一点」这类含数字的普通词会被当成数字处理，可能误判为 `NO_INTENT`。
10. `has_unsafe_number_format()` 只拦截「符号 / 小数点 / 分隔符**紧邻**数字」的写法。
    句末标点不是数字的一部分，正常放行：`大于五.`、`大于五。`、`大于五！` 都解析为 `ASK/GT(5)`。
11. `confidence` 未做任何区分度。

### 未做 / 明确留到后续阶段

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 与 C 的 `RefereeService` 真实联调 | 未做 | `event_service.py` 至今不在仓库；目前用 `tests/support/fake_referee.py` 替代 |
| A↔C 传输层（ROS 话题/服务） | 未做 | 全组接口未冻结；`speech_node.build_referee()` 故意抛 `NotImplementedError` |
| 玩家藏牌（v0.3）的「是/不是」 | 未做 | `AFFIRM`/`DENY` 目前只在**确认窗口打开**时映射成 confirm/cancel；进入 answer 阶段应映射成 `propose(kind="yes"/"no", number=None)`。`referee_protocol` 已预留 `KIND_YES`/`KIND_NO`，等 C 提供 `PlayerHidesService` 再接 |
| PAUSE / RESUME 的实际状态控制 | 未做 | 目前只播报一句并记日志；C 的两份原型文档都没定义暂停/恢复的状态转换，A 不擅自冻结会话 |
| 播报完成/失败/超时事件 | 部分 | `PlaybackResult` 已定义四种状态，但设备侧拿不到可靠完成信号（见 §13） |
| 回声抑制、收音窗口控制 | 未做 | `RosInput.drain_before_listen` 只能清**已积压**的消息 |
| 日志轮转 | 未做 | 现在每次启动一个文件，够用；长期运行前再加 |

## 8. 与仓库的关系

本目录是 `A_speech/robot_speech/`，**没有**改动 `aslinn119/Robot` 仓库，
也**没有**改动 `A_speech/aiui_reference/` 下三份参考源码。
阶段一验收通过后，按下表复制：

| 本地 | 仓库目标 |
| --- | --- |
| `src/robot_speech/*.py` | `robot_speech/src/robot_speech/` |
| `scripts/speech_cli.py` | `robot_speech/scripts/` |
| `tests/` | `robot_speech/tests/` |
| 本 README 相关章节 | `robot_speech/README.md` 与 `docs/` |

## 9. 修订记录

### 2026-11-19 · 第 2 版（评审回归）

评审在 Python 3.13 上复现了 4 个边界问题，全部修复并补回归测试：

| # | 现象 | 根因 | 修法 | 回归测试 |
| --- | --- | --- | --- | --- |
| 1 | `大于-5吗` → `ASK/GT(5)` | 清洗删除负号 | 清洗前用 `has_unsafe_number_format()` 拒绝 | `test_invalid_number_format` |
| 2 | `是1.0吗` / `是1 0吗` → `ASK/EQ(10)` | 清洗删除小数点与数字间空格 | 同上 | `test_invalid_number_format` |
| 3 | `确认吗` → `CONFIRM` | 剥句尾语气词时把疑问当噪声 | `has_question_particle()` + 非 ASK 意图拒绝 | `test_question_particle_on_non_ask` |
| 4 | `我确定是七吗` → `FINAL(7)` | 同上 | 同上 | `test_question_particle_on_non_ask` |
| 5 | 增量式事件 `大于`+`五吗` → `五吗` | 累积式假设下「非前缀」被当修订 | 增加 `mode="delta"`，两种假设都可见可选 | `test_delta_mode_appends_fragments` |
| 6 | 同一最终事件连推两次 → 两次最终结果 | 无最终结果去重 | 紧邻重复的最终事件返回 `is_final=False, is_duplicate=True` | `test_duplicate_final_event_is_deduplicated` |
| 7 | 同一位置的多个 `cw` 被首尾拼接 | 误把 n-best 候选当续写 | 只取 `cw[0]`，与参考实现一致 | `test_parse_segment_uses_first_candidate_only` |

测试从 167 增至 203，全部通过。新增 2 个拒绝原因：`INVALID_NUMBER_FORMAT`、`UNEXPECTED_QUESTION`。

### 2026-11-19 · 第 3 版（评审二次复核）

| # | 现象 | 修法 | 回归测试 |
| --- | --- | --- | --- |
| 1 | `确认？` → `CONFIRM`、`我确定是七？` → `FINAL(7)`：问号被当噪声 | `has_question_particle()` 除语气词外也识别问号（NFKC 后只有半角 `?`） | `test_question_particle_on_non_ask` |
| 2 | `是.5吗` → `EQ(5)`：小数点前没有数字时没被拦 | 增加「小数点紧邻数字」的独立模式 | `test_invalid_number_format` |
| 3 | `是1,0吗` / `是1。0吗` → `EQ(10)`：分隔符被删后数字拼接 | 增加「数字间夹分隔符」模式 | `test_invalid_number_format` |
| 4 | README 称 `大于五.` 会被拒绝，实际能解析 | 文档订正：句末标点不是数字的一部分，正常放行 | `test_sentence_final_punctuation_is_tolerated` |

测试从 203 增至 216。同时新增阶段二 A→C 适配层（见 §10），总计 258 项。

### 2026-11-19 · 第 4 版（阶段三骨架）

新增设备端口与交互流程编排（见 §11）：`ports.py`、`simulated_devices.py`、
`session.py`、`scripts/dialogue_demo.py`、`scripts/speech_node.py`、`tests/test_session.py`。

三条上机前必须跑通的场景已离线验证：播完才开窗、迟到确认不串轮、有效确认只生效一次。
测试从 258 增至 **277**。

`speech_node.py` 只做了语法检查，未在机器人上运行。

### 2026-11-19 · 第 5 版（事件日志）

新增 `eventlog.py` 与 `evidence/logs/`，三条场景各落一份 JSONL（见 §12）。

| 改动 | 说明 |
| --- | --- |
| 事件日志 | 一次运行一个文件、一个事件一行；模拟演示与 ROS 入口共用 |
| 默认不记原文 | `--log-raw` / `~log_raw_text` 才写语音与播报文本 |
| `UNVERIFIED` 收紧 | 默认**不开窗**；只有诊断模式才放行，并写 `window.open.unverified` |
| 开窗身份拆分 | `pending_key`（C 的待确认项）与 `key`（含 `window_id`，每次开窗唯一） |
| 重播重开窗 | `retry_recitation()` 为同一待确认项**重新开一扇窗**，旧窗口结果仍被拒收 |

测试从 277 增至 **288**。

### 2026-11-19 · 第 6 版（窗口归属修正 + 上机诊断入口）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | `RosInput` 在**出队时**才取 `window_key`，等于用「处理时刻」冒充「采集时刻」 | 改在 ROS 回调里打标并带上到达时刻；归属标为 `ARRIVAL` |
| 2 | key 对得上但结果其实早就到了 | 新增独立判据：**到达时间早于窗口生效 → 判过期**（`arrived_before_window`） |
| 3 | 归属不可信的结果被直接用来提交 | 新增 `WindowAttribution`；`UNKNOWN` 一律**只观察不提交** |
| 4 | 每次启动追加同一文件、`seq` 从头计 | 每次启动一个文件 + 唯一 `session`（`robot-<run_id>`） |
| 5 | `log.anchor` 排在 `session.start` 之后 | 锚点改为文件第一行 |
| 6 | C 没接好时上机无从下手 | 新增 `scripts/device_probe.py` + `probe.py`，独立记录 TTS 返回、消息到达与观察窗口 |

日志新增 `input.attribution` / `probe.*` 事件，`input.stale` 增加
`arrived_before_window` 这个 reason。测试从 288 增至 **299**。

### 2026-11-19 · 第 7 版（诊断入口可启动 + 默认只信采集时绑定）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | `get_param("~run_id")` 不带默认值，参数未设置时抛 `KeyError`，脚本起不来 | 抽出 `resolve_probe_config()`，**每个 key 都带默认值**；用模拟 `get_param` 做无参数启动检查 |
| 2 | 探针把「没抛异常」当成服务接受 | 检查响应里的 `is_success`；缺该字段时记 `accepted_unknown` 并写原始响应 |
| 3 | 探针没有播放完成信号 | 新增人工打点 `tts.observed`，与服务接受、机器信号**分开记录** |
| 4 | 按到达时间推断的确认仍会提交给 C | 默认只接受 `CAPTURE`；`ARRIVAL` 需显式 `allow_inferred_attribution` |

新增测试：评审指定的「A 的确认在 B 开窗后到达」场景——B 保持待确认、C 请求数不变；
以及无参数启动、参数覆盖、`is_success` 分支。测试从 299 增至 **304**。

### 2026-11-19 · 第 8 版（启动方式与探针输出）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | README 写 `rosrun robot_speech device_probe.py`，但本目录没有 `package.xml`/`CMakeLists.txt` | 改为「加载环境 + 模块根目录 `python3 scripts/device_probe.py`」，并注明 `rosrun` 路径需现场验证 |
| 2 | 终端把**话题消息数**标成「机器信号」 | 三个口径分开打印：TTS 服务状态 / 人工参照 / 候选完成信号 / 话题消息数 |
| 3 | TTS 失败后仍可能打印「服务已提交」 | `ProbeSpeaker` 返回 `TtsOutcome`，终端按 `accepted` / `rejected` / `failed` / `accepted_unknown` 如实显示 |
| 4 | `RosSpeaker` 未检查 `is_success` | 与探针同步：`is_success=False` → `FAILED`；字段缺失 → `accepted_unknown` |

测试仍为 304 项（本轮只改脚本与文档，未新增可离线测的逻辑）。

### 2026-11-19 · 第 9 版（上机前最后两处）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | §6 仍留着 `rosrun robot_speech device_probe.py _topics:=...` 的旧示例，容易复制错 | 换成 `python3 scripts/device_probe.py`，并指向 §13 |
| 2 | TTS 未初始化（`outcome is None`）时仍会提示人工打点，回车可能被记成「听到播完」 | `can_hear = outcome is not None and outcome.submitted`；其余情况只观察话题 |

`rosrun` 现在只在「为什么用不了」的说明里出现，不再作为可执行命令。

### 2026-11-25 · 第 10 版（外部复核后的修正）

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | `speech_node.py` 缺 `src` 路径注入，`python3 scripts/speech_node.py` 会 `ModuleNotFoundError` | 与其他脚本一致，先注入 `../src` |
| 2 | `speech_node.py` 的 `get_param("~run_id")` 无默认值 → `KeyError` | 改为 `get_param("~run_id", "") or ...` |
| 3 | `speech_node.py` 退出时不关日志句柄 | `try/finally` 里 `session.end` + `log.close()` |
| 4 | `RosSpeaker` 不等服务，第一句可能直接吃异常 | 构造时 `wait_for_service(timeout=5)`，超时只告警 |
| 5 | **IAT 末尾补发的 `ls=True` 不带新词时返回 `is_final=False`**，上层永远等不到收尾 | 新增 `_closing_final()`：没有新词也算收尾，且不标 duplicate |

第 5 条是真 bug：最终事件若 `ws` 为空或与上一条相同，`is_final` 会被吞掉，
整句话随后被下一句的 `auto_reset` 清空。测试从 304 增至 **309**。

> 复核里另有几条判断经核实**不成立**，记录在此免得后人再被带偏：
> - 「`set[str]` / `str | None` 在 Python 3.8 会报错」——不会。这两个都出现在
>   **注解**里，而注解在运行时不被求值（实测：写入一个未定义名字的注解也不抛错）。
>   3.8 上仍建议跑一次 pytest 作为保险，但不是阻塞项。
> - 「项目方案书规划了 Qwen3 补充解析」——在工作区全部文档与 PDF 提取文本里
>   **找不到任何 Qwen/通义相关记载**，这条无法核实，暂不采纳。

---

## 10. 阶段二 · A → C 适配层

阶段二原计划包含「请求编号 + 确认绑定 + 模拟成功/失败」。本轮先把**时序**做出来，
C 用测试替身，计次与胜负仍归 C。

### 文件

| 文件 | 职责 |
| --- | --- |
| `src/robot_speech/referee_protocol.py` | 纯函数：解析结果 → payload、事件构造、`action_for` 路径判定 |
| `src/robot_speech/referee_client.py` | 会话层：request_id、确认窗口绑定、重试、状态同步 |
| `tests/support/fake_referee.py` | **C 的最小测试替身**（不是 C 的实现） |
| `tests/test_referee_client.py` | 时序测试 |
| `scripts/referee_demo.py` | 可独立演示的时序脚本 |

### 三条必须守住的规则

1. **绑定发生在开窗时，不在收到「是」时。**
   `open_confirm_window()` 立刻快照 `pending_id` + `version`，此后无论中间发生了什么，
   确认发出去的都是那一组。v0.2 原话：「异步适配器必须在打开收音窗口时绑定这些字段，
   不能收到迟到的「是」后才查询并绑定新问题。」

2. **重试复用同一个事件 dict。**
   去重键是 `game_id + request_id + 完全相同内容`。重试若重新生成 `timestamp`，
   会被判成「相同编号改变内容」→ `request_conflict`。`resend()` 原样重发。

3. **重复响应里的 state 是旧快照。**
   命中 `duplicate=true` 时忽略响应里的 state，重新取 `public_state()`。

### 客户端不替 C 做决定

- `confirm()` **不拦截过期窗口**。过期与否由 C 判断；A 擅自丢弃会让「迟到确认」
  永远测不出来。想知道是否过期用 `is_stale()` 记日志。
- 本层不判断阶段。`action_for()` 只有在**确认窗口打开**时才把「是/不是」解释成
  confirm/cancel；否则返回 `REJECT`，等上层给上下文。

### 复现

```powershell
python scripts\referee_demo.py
python -m pytest tests\test_referee_client.py -v
```

核心断言（`test_late_confirm_after_cancel_does_not_touch_new_pending`）：

```text
提议 A → 开窗绑定 (p1, v1) → 取消 A → 提议 B (p2, v2)
→ A 的旧确认迟到，payload 仍是 (p1, v1)
→ C 拒绝；history 仍为空、remaining 仍是 7、pending 仍是 B
→ 对 B 有效确认：remaining 6、history 1
→ 同 request_id 重试：duplicate=True，remaining 与 history 不再变化
```

### 需要与 C 对齐的未冻结项

| 项 | 现状 | 影响 |
| --- | --- | --- |
| 同一局内旧待确认项的错误码 | v0.2 只有跨局的 `stale_game`；替身用临时码 `pending_mismatch` | 测试只锁定「拒绝且状态不变」，不锁定码值 |
| `state.pending` 的字段结构 | 替身用平铺 `kind`/`number`；客户端两种写法都兼容 | 复述文本取哪个字段要定 |
| 公共字段 `timestamp` | 默认带、可关；重试复用原值 | 若 C 校验不接受该字段，构造时关掉 |
| 提议未确认时又来新提议 | 替身选择「替换 pending 并递增 version」，v0.2 未明确 | 影响旧确认被拒的方式 |
| 播报完成/失败/超时事件 | C 尚未实现 | 阶段三前要定字段 |

---

## 11. 阶段三骨架 · 交互流程与设备端口

上机只能查两件事：**机器人到底播完没有**、**玩家说完后识别结果从哪来**。
所以先把这两处抽成端口，流程代码按「拿到明确信号才继续」写死；上机时只替换实现。

### 11.1 两个端口

```python
class SpeechInput(Protocol):
    def stream(self) -> Iterator[Utterance]: ...

class SpeechOutput(Protocol):
    def speak(self, text: str) -> PlaybackResult: ...
```

`PlaybackResult.status` 有四种：

| 状态 | 含义 | 会话怎么处理 |
| --- | --- | --- |
| `completed` | 确认播完 | 打开确认窗口 |
| `failed` | 明确失败 | 不开窗，提示重说 |
| `timeout` | 等完成信号超时 | 不开窗，提示重说 |
| `unverified` | 请求已提交，但没有完成信号 | **默认不开窗**；只有显式打开诊断模式才开窗并在日志标记 |

`unverified` 是为实机准备的：`/aiui/text_to_speak` 返回 True 时我们不知道播完没有。
**默认路径要求「观察到播完」**——否则即使跑完一局，日志也无法证明「播完 → 开窗」成立。
需要现场诊断时用 `allow_unverified_playback=True`（ROS 参数 `~allow_unverified_playback`），
此时会额外写一条 `window.open.unverified`，记录里一眼能看出哪几轮是按未知状态推进的。

### 11.2 迟到结果靠窗口身份挡住，不靠猜

```python
Utterance(text="确认", window_key=ConfirmWindow.key,
          window_source=WindowAttribution.ARRIVAL, captured_at=123.4)
#                                 ^ 这个 key 是怎么来的      ^ 结果到达时刻
```

**`window_key` 本身不可信，必须同时说明它是怎么来的。**

| `window_source` | 含义 | 会话怎么处理 |
| --- | --- | --- |
| `CAPTURE` | 收音开始那一刻绑定的 | 正常提交，日志记 `captured` |
| `ARRIVAL` | 结果**到达**时按当时的窗口推断的 | **默认不提交**；显式 `allow_inferred_attribution` 才提交并记 `inferred` |
| `UNKNOWN` | 没有归属信息 | **只观察，不提交**，日志记 `unknown` / `observation_only` |

默认只接受**采集时绑定**的确认：玩家在窗口 A 说「确认」、结果在 B 开窗后才到，
到达时打标会指向 B，这种情况下任何基于 `window_key` 的判断都会错，只能拒收。

在此基础上再加一条**独立判据**：

> **结果到达时间早于窗口生效时间 → 它不可能属于这扇窗。**

实机上 `window_key` 往往只能按到达时刻推断，玩家在窗口 A 说「确认」、结果在窗口 B
打开后才到，key 会指向 B。时间判据不依赖 key，能把这类结果判成过期
（日志 `input.stale reason=arrived_before_window`）。

会话判定顺序：

| 判定 | 条件 | 处理 |
| --- | --- | --- |
| `untrusted` | `window_source == UNKNOWN` | 不提交，播报「听不出属于哪个问题」 |
| `inferred` | `window_source == ARRIVAL` 且未显式放开 | 不提交，播报「可能对不上当前问题」 |
| `stale` | key 属于已关闭窗口，**或到达早于窗口生效** | 不提交，播报「已经过期了」 |
| `unknown` | key 既不是当前也不是已关闭 | 不提交，播报「对不上当前的问题」 |
| `current` | 其余 | 发给 C |

### 11.3 三条场景的实跑（`python scripts\dialogue_demo.py`）

```text
=== 场景 1：播报失败不开窗；观察到播完才开窗 ===
  大于五吗 -> recite_failed (failed)   朗读：没播出来，请再说一次。
       窗口：None（没开）        剩余次数 7（没变）
  确认     -> no_pending
  <retry>  -> proposed   窗口：scenario1|p1|1#w-0002
  确认     -> confirmed  剩余次数 6，历史 1

=== 场景 2：迟到结果不能串到下一轮 ===
  大于五吗 -> proposed   窗口 A：scenario2|p1|1#w-0001
  取消     -> cancelled
  是七吗   -> proposed   窗口 B：scenario2|p2|2#w-0002
  确认     -> stale_confirm   请求数 3 → 3，次数 7，历史 0，待确认仍是 p2

=== 场景 3：有效确认只生效一次 ===
  确认     -> confirmed  剩余 6，历史 1
  确认     -> stale_confirm  请求数 4 → 4，剩余 6，历史 1
  resend   -> duplicate=True  剩余 6，历史 1
```

注意场景 1：复述失败后重试是**重新开一扇窗**（`w-0001` → `w-0002`），
不是复用原来那扇。见 §12.3。

### 11.4 ROS 薄壳（`scripts/speech_node.py`）

只做「设备 ↔ 端口」接线，三个 `TODO(上机)`：

| 位置 | 现状 | 上机要确认 |
| --- | --- | --- |
| `RosSpeaker.completion_probe` | 无完成信号 → `UNVERIFIED`；已按 `is_success` 区分 `accepted` / `rejected` / `accepted_unknown` | 播放完成信号从哪来 |
| `RosInput` | 只能订阅 `/aiui/nlp`（语义结果，非自由听写） | 识别出口与到达延迟 |
| `build_referee()` | 故意抛 `NotImplementedError` | A↔C 话题/服务冻结后再接 |

`RosInput` 还有一个必须上机验证的取舍：默认 `drain_before_listen=True`，
每次开听前清空积压。它会丢掉机器人自己的回声，**也可能丢掉玩家抢先说的话**。

> 本机没有 ROS，`speech_node.py` 只做了语法编译检查（`py_compile` 通过），
> 未在机器人上运行过。

---

## 12. 事件日志（JSONL）

一次运行 = 一个文件，一个事件 = 一行。模拟演示与 ROS 入口共用同一套 `eventlog.EventLog`，
上机时把 `~log_path` 指向机器人上的文件即可，格式完全一致。

```powershell
python scripts\dialogue_demo.py                    # 写到 evidence/logs/
python scripts\dialogue_demo.py --log-raw          # 附带原始语音/播报文本
```

### 12.1 字段

| 字段 | 说明 |
| --- | --- |
| `seq` / `ts` | 序号；单调时钟（秒）。**不能跨进程比较**，所以文件第一行是 `log.anchor`，带墙钟时间 |
| `event` / `result` | 事件名与结局 |
| `session` / `game_id` / `turn` | 会话标签、局号、第几轮。ROS 入口的 `session` 每次启动唯一 |
| `request_id` | 相关请求编号（有则记） |
| `window` / `pending` | 本次开窗身份 / C 的待确认项身份（有则记） |
| `data` | 事件附加信息 |
| `text` | **默认不记**。隐私考量；`--log-raw` 或 `~log_raw_text:=true` 才写 |

### 12.2 事件表

| 事件 | 出现时机 | 关键 `data` |
| --- | --- | --- |
| `session.start` | 会话创建 | `allow_unverified_playback` |
| `log.anchor` | 会话创建 | `wall`（墙钟）、`mono_now` |
| `input.received` | 收到一句识别结果 | `chars`、`sequence`、`window_source`、`captured_at` |
| `input.parsed` | 解析完成 | `intent`、`operator`、`value`、`reason` |
| `input.attribution` | 确认/取消的归属判定 | `source`、`submitted`、`note`（`captured` / `inferred` / `unknown`） |
| `input.stale` | 旧结果被拒收 | `reason`（`window_closed` / `arrived_before_window` / `no_open_window`）、**`sent_to_referee: false`** |
| `propose.sent` / `confirm.sent` / `cancel.sent` | 发请求 | `payload`、`request_id` |
| `referee.response` | 收到 C 响应 | `code`、`duplicate` |
| `window.create` | 分配窗口身份（尚未生效） | `window_id`、`version` |
| `window.activate` | **窗口正式可收确认**（播完之后的证据） | — |
| `window.deferred` | 播报没完成，窗口不生效 | `playback` |
| `window.open.unverified` | 诊断模式下未知状态开窗 | `mode: diagnostic` |
| `window.close` | 窗口关闭 | `cancelled` / `confirmed` / `superseded` / `reopened` |
| `speak.request` / `speak.result` | 每次朗读 | `purpose`（`recite`/`prompt`/`answer`）、`elapsed` |
| `tts.service` | 实机 TTS 服务返回 | `is_success`、`means: request_submitted_only` |
| `tts.probe` | 实机等待完成信号 | `absent` / `completed` / `timeout` |
| `tts.observed` | 诊断入口：人工打点「听到播完」 | `source: operator`、`elapsed` |
| `input.drained` | 清空积压 | `count`、`scope: backlog_only` |
| `retry.requested` / `retry.rejected` | 重播复述 | 拒绝原因 |
| `probe.subscribed` / `probe.message` | 诊断入口：订阅了哪些话题、收到了什么 | `topic`、`size`、`arrived_at`、`in_watch` |
| `probe.watch.begin` / `probe.watch.end` | 诊断入口：观察窗口 | `label`、`messages`、`by_topic` |
| `turn.end` / `session.end` | 轮/场结束 | `turn.status` |

### 12.3 三份证据日志

`evidence/logs/` 下三份文件由 `dialogue_demo.py` 生成，可直接 grep。

**`scenario1.jsonl`（为什么开窗）**：`speak.result=failed` → `window.deferred` →
`window.close(reopened)` → `window.create(window_id=w-0002)` → `speak.result=completed` →
`window.activate`。只有最后这条之后才可能出现 `confirm.sent`。

**`scenario2.jsonl`（为什么拒收）**：`window.close(cancelled)` 关闭 `w-0001` →
新问题创建 `w-0002` → 带 `w-0001` 的确认到达 → `input.stale reason=window_closed
sent_to_referee=false`。整份日志里没有任何一次 `confirm.sent` 属于那条迟到确认。

**`scenario3.jsonl`（为什么只扣一次）**：只有一对 `confirm.sent A-0004` /
`referee.response ok`；重复的确认变成 `input.stale`；最后的 `client.resend` 结果是
`duplicate`，`remaining=6 history=1` 没有变化。

### 12.4 这份日志**不能**证明什么

- 不能证明机器人真的播完了——模拟喇叭是即时的，`elapsed` 恒为 0。
- 不能证明识别结果来自麦克风——离线输入是脚本。
- `drain_before_listen` 只能清掉**已积压**的消息；之后才到达的回声或旧识别仍可能进入窗口，
  这一点只有上机能验证。

---

## 13. 上机诊断入口（不需要 C）

`scripts/device_probe.py` 是给上机第一天用的：C 的接口还没接好，也能先把三件事
**分开**查清楚。

### 启动方式

`A_speech/robot_speech/` 这份独立目录**没有 `package.xml` 和 `CMakeLists.txt`**，
所以 `rosrun` 用不了。机器人上按下面的方式启动：

```bash
source /opt/ros/noetic/setup.bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
cd <本模块根目录>            # 例如 robot_speech/
python3 scripts/device_probe.py
```

不需要额外参数。也可以显式指定：

```bash
python3 scripts/device_probe.py _topics:="/aiui/nlp,/aiui/iat,/aiui/peer" _watch_seconds:=8
```

> `rosrun robot_speech device_probe.py` 只有在脚本被放进 catkin 工作空间里某个
> 已构建的包时才能用。**这条路径当天需要现场验证**，不要默认它能跑。

### 它记录什么

终端里输入一句话回车 → 调 TTS 并开始观察；**听到播完时再按一次回车**打点。

三件**不能混为一谈**的事分别记录、分别显示：

| 记录 | 事件 | 含义 |
| --- | --- | --- |
| 服务接受 | `tts.service` | 检查响应里的 `is_success`；**True 只代表请求被接受，不代表播完** |
| 现场听到播完 | `tts.observed` | 人工打点（`machine_signal: false`），相对提交时刻的耗时 |
| 话题消息 | `probe.message` / `probe.watch.end` | 观察窗口内到达的消息数与来源话题 |

终端输出长这样，三个口径分开写：

```text
  TTS 服务 : accepted（请求已接受，不代表播完） (0.12s)
  …观察中（听到播完请按回车）
  人工参照 : 听到播完（相对提交 3.41s，现场参照，不是机器信号）
  完成信号 : 未观察到（本版本未接入完成信号检测）
  话题消息 : 2 条 {'/aiui/nlp': 2}（到达计数，不等于播完信号）
```

TTS 失败或 `is_success=False` 时会显示 `failed` / `rejected`，不会假装「服务已提交」。

**它能回答的**：`/aiui/iat` 到底发不发消息、TTS 之后多久有东西到达、人工听到播完的
时刻附近有没有消息。

**它不能回答的**：「这条消息属于哪次收音」。`probe.message` 记的是**到达时刻**，
不是采集时刻。这正是 §11.2 里 `ARRIVAL` 与 `UNKNOWN` 两种归属要分开的原因。

### 一条待验证的线索：`/aiui/wakeup_mute`

厂商节点还暴露了 `/aiui/wakeup_mute`（`SrvWakeupMute`），它直接触发
`wakeup_callback`，可以**不喊唤醒词**就重开一轮收音，并支持 `need_to_play_reply=False`。
如果上机确认它可用，「唤醒一次后连续多轮收音中断」可能就有了现成的解法。

> 这只是**线索**，未经验证，也**没有**接进代码。上机时可以用
> `rosservice call /aiui/wakeup_mute "need_to_play_reply: false"` 单独试。

日志写到 `~/.ros/robot_speech/probe-<run_id>.jsonl`，与游戏日志同一套格式。

> 本机没有 ROS，`device_probe.py` 只做了 `py_compile`，未在机器人上运行。
> 不带参数的启动检查是用 `resolve_probe_config()` + 模拟 `get_param` 在离线环境做的。
