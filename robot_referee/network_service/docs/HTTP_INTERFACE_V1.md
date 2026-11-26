# Roban 多轮猜牌机器人统一接口规范

**版本 1.0 · 执行规范 · 2026-11-26**

适用成员：A 李馨瑶、B 刘九尔、C 刘杰、D 吴零。

本文件直接规定第一版联调接口。成员按本文件开发，不再分别决定路径、字段或通信方式。设备没有对应能力时，返回规定的失败码，按退化流程处理，不私自改协议。物理能力、网络地址和实际耗时需要上机检查；协议本身不因此悬而未定。

**实现状态：当前 C 已有本地规则、去重、日志、暂停继续和只读记录页；本规范规定的 8780 网络调度接口及任务队列需要新增。文档与样例不是已上线服务。原有 8765 记录服务仍为只读。**

## 目录

1. 固定架构与各成员交付
2. 地址、配置、权限与目录
3. HTTP 路径总表
4. 公共消息、响应与编号
5. 任务领取及执行规则
6. A 语音接口
7. B 视觉与私密登记接口
8. D 策略接口
9. D 动作接口
10. C 状态、公开记录与规则
11. 两种玩法完整时序
12. 暂停、取消、重发与恢复
13. 超时、失败码与退化
14. 日志、证据与秘密信息
15. 独立开发、模拟模式与验收
16. 开发顺序与现有原型迁移
17. 快速实现清单

## 1 固定架构与各成员交付

### 1.1 通信方式

跨成员统一使用 **HTTP/1.1 + UTF-8 JSON**。C 是唯一业务调度服务；A、B、D 主动连接 C，领取命令并回传事件。采用任务拉取，不要求 C 回调成员电脑，不要求 Windows 安装 ROS。

机器人内部保留现有 ROS 相机、声音和动作接口。A/B/D 自己把平台调用适配到本规范；模型或硬件库不同不影响跨模块消息。C 不直接调用 A/B/D 的 Python 函数，也不要求其他模块导入 C 的内部类。

```text
A 语音与千问 ─┐
B 卡牌与确认 ─┼─ HTTP JSON ─ C 调度与裁判 ─ 公开记录页
D 策略与动作 ─┘                 │
                           私密记录与证据
```

### 1.2 分工与边界

| 成员 | 必须实现 | 不承担的工作 | 必交成果 |
|---|---|---|---|
| A 李馨瑶 | 领取 speech.say、speech.listen；ASR、千问/规则解析、TTS；正确回传意图和执行状态 | 不计次、不判胜负、不读登记数字、不调动作关节 | A 客户端、正常/失败样例、语义与延时测试 |
| B 刘九尔 | 领取 vision.capture、registration.confirm；制卡、识牌、多帧稳定、证据上传、私密确认界面 | 不公布登记值、不判输赢、不实现 D 的猜牌算法 | B 客户端、十张牌、映射、私密确认入口、识牌测试 |
| C 刘杰 | 8780 服务、任务队列、状态机、确认提交、去重、核验、公开记录和私密存储；统一启动/模拟调度入口 | 不代写 ASR/视觉/搜索/关节驱动，不代替模块报告真实执行成功 | C 服务、协议校验、规则测试、队列与日志、公开页 |
| D 吴零 | 领取 strategy.decide、motion.execute；候选更新、七问验证、回答策略、少量动作与反馈 | 不直接修改裁判历史、不决定已提交次数、不读取玩家秘密牌 | D 客户端、策略验证、动作适配、失败处理 |

C 负责业务顺序和任务编号，A 负责声音执行，B 负责图像和私密界面，D 负责策略和动作。台词以 C 依据确定事实生成的文本为准；A 不改“是/不是”、数字和结果。D 的动作通过 C 发出，不与 A 建立另一套通信通道。

## 2 地址、配置、权限与目录

### 2.1 固定地址规则

| 项目 | 固定规则 |
|---|---|
| C 业务服务 | `http://<C电脑局域网IPv4>:8780` |
| C 本机调用 | `http://127.0.0.1:8780` |
| 公开记录页 | C 本机 `http://127.0.0.1:8765`，保持只读 |
| API 前缀 | `/api/v1` |
| 相机默认话题 | `/camera/color/image_raw`；若该流不可用，只通过配置切到 `/chin_camera/image` |
| HTTP 客户端 | Python 标准库 urllib 或 requests 均可，消息格式必须相同 |

C 的 IP 是部署值，不是新的接口设计问题。部署时由 C 写入一份共享配置，其他成员照用。`127.0.0.1` 仅适用于服务所在电脑，机器人或队友电脑不得用它访问 C。没有真实网络信息时不得编造 IP。

业务服务在需要跨设备联调时监听 `0.0.0.0:8780`；只在本机模拟时监听 `127.0.0.1:8780`。只开放实验所需的局域网访问。首版公开页无需跨设备开放。

### 2.2 配置和凭据

共享 `config/interface.example.json`，每人复制为不入 Git 的 `config/interface.local.json`。公共配置固定包含 `base_url`、`protocol_version`、`connect_timeout_ms`、`read_timeout_ms`；各模块填写自己的 `module` 和令牌环境变量名。

A/B/D/C 各有独立随机令牌，分别从 `ROBAN_TOKEN_A`、`ROBAN_TOKEN_B`、`ROBAN_TOKEN_D`、`ROBAN_TOKEN_C` 读取。C 服务根据 Bearer token 确定身份，再核对消息 source，不能只相信客户端自报 source。

请求头统一为：

```http
Content-Type: application/json; charset=utf-8
Authorization: Bearer <本模块令牌>
X-Roban-Instance: <本进程启动时生成的32位UUID十六进制串>
```

`/health` 与公开查询不需要令牌。任务查询仅能读取自己的命令；C 可查全部。凭据不写进代码、日志、截图或 Git。私密登记和动作任务必须经身份检查；HTTP 本身不提供加密，首版只用于受控实验网络。

### 2.3 仓库目录

```text
Robot/
  docs/TEAM_INTERFACE.md          本规范，唯一入口
  contracts/protocol_v1.schema.json
  contracts/examples_v1.json
  config/interface.example.json
  modules/speech_a/               A 自己维护
  modules/vision_b/               B 自己维护
  modules/referee_c/              C 自己维护
  modules/strategy_d/             D 自己维护，内部区分策略与动作
  tests/contract/                 公共格式测试
  logs/                          不入 Git
```

先在各自模块内开发，公共格式按规范使用。现有 C 原型先保留 D 盘目录，迁入仓库时再整理模块路径，不要求队友使用 C 的虚拟环境。

## 3 HTTP 路径总表

以下路径固定，`<game_id>`、`<command_id>`、`<module>` 是路径参数。

| 方法 | 路径 | 调用方 | 用途 |
|---|---|---|---|
| GET | `/api/v1/health` | 全部 | 版本、服务实例、就绪状态 |
| GET | `/api/v1/state/public` | 全部 | 当前公开状态；无局时 phase=idle |
| GET | `/api/v1/games?limit=20` | 全部 | 最近公开对局摘要，limit 为 1～100 |
| GET | `/api/v1/games/<game_id>/public` | 全部 | 某局公开快照/结束记录 |
| POST | `/api/v1/games` | C | 新建对局；当前局未结束时拒绝 |
| POST | `/api/v1/events` | A/B/C/D | 心跳、接单、开始、结果及控制事件 |
| GET | `/api/v1/modules/<module>/commands/next?wait_ms=1000` | 对应模块/C | 领取下一任务；wait_ms 为 0～1000 |
| GET | `/api/v1/commands/<command_id>` | 任务所属模块/C | 查状态、是否要求取消、剩余时间 |
| POST | `/api/v1/evidence` | B | 上传本次识牌的私密 JPEG 证据 |
| GET | `/api/v1/evidence/<evidence_id>` | B/C | 读取私密证据，不对 A/D/公开页开放 |

不存在 `POST /state`、任意历史修改、私密数字公开查询或“直接扣次数”接口。A/B/D 不能创建新局或改胜负。

任务拉取增加固定通道参数：A/B 使用 `?lane=main&wait_ms=1000`；D 必须分别运行 `?lane=strategy&wait_ms=1000` 和 `?lane=motion&wait_ms=1000` 两个循环。lane 从 command_type 推导：strategy.decide 属于 strategy，motion.execute 属于 motion；A/B 均为 main。省略 lane 只对 A/B 默认 main，D 省略或通道不匹配返回 BAD_REQUEST。每个通道最多一项活动任务，D 两通道可以独立运行，动作不得占用策略锁。

`GET commands/next` 返回 `data.command=null` 表示暂无任务，不是失败。使用空结果继续轮询，不制造任务失败事件。一个模块实例每 250ms～1000ms 拉取一次即可，不准忙循环。

## 4 公共消息、响应与编号

### 4.1 事件信封

`POST /events` 必须恰有下面八个顶层字段，不接受额外字段。所有 ID 为 32 位小写十六进制 UUID，禁止复用同一编号表示不同操作。

```json
{
  "protocol_version": "1.0",
  "request_id": "11111111111111111111111111111111",
  "game_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_epoch": 0,
  "source": "A",
  "command_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "event_type": "task.accepted",
  "payload": {}
}
```

- `request_id`：本次事件的幂等编号。网络重发保持完整内容不变。
- `game_id`：对局编号，由 C 生成。不能把旧局结果改成新局编号。
- `input_epoch`：任务发放时的输入代次，由 C 生成。不是客户端收到消息时临时读取的最新值。
- `source`：`A/B/C/D`；必须与令牌身份一致。
- `command_id`：所回应命令的编号。心跳及 C 控制事件填 null。
- `module.heartbeat` 是唯一允许 game_id、input_epoch 同时为 null 的事件；其他事件必须绑定当前或已知历史任务/对局。
- JSON 中布尔值不能替代整数，数字不使用字符串，禁止 NaN/Infinity。

C 用 `(source, request_id)` 去重：同内容返回原处理结果，`replayed=true`；不同内容返回 `REQUEST_CONFLICT`。已确认回答不因重发再次提交。缓存至少保留至本服务进程结束；进程重启按中断局处理，不承诺旧局续玩。

### 4.2 统一响应

所有 JSON 响应都有：

```json
{
  "ok": true,
  "code": "OK",
  "message": "事件已接收",
  "replayed": false,
  "server_time": "2026-11-26T09:00:00+08:00",
  "server_instance_id": "cccccccccccccccccccccccccccccccc",
  "data": {}
}
```

`data` 随路径变化：任务领取为 `{"command": 命令或null}`；状态为 `{"state": 公开状态}`；事件回执为 `{"disposition":"applied|recorded|ignored_for_game","command_status":字符串或null}`。

health 的 data 固定为 `{"protocol_version":"1.0","service_status":"ready","server_instance_id":"32位UUID","modules":{"A":"offline","B":"offline","D":"offline"}}`，service_status 为 starting/ready/degraded，模块值为 offline/ready/busy/degraded/unknown。此时 server_instance_id 与外层相同。games 列表的 data 为 `{"games":[{"game_id":"编号","mode":"robot_hides","runtime_mode":"mock","phase":"finished","started_at":"时间","ended_at":"时间或null","outcome":"结果枚举或null"}]}`，不包含私密 payload。

`ok=true` 仅代表该 HTTP 操作被正确处理，不代表问题已经计次、声音已播出或动作已完成。已处理旧请求可返回历史响应；需要当前状态时重新 GET，不把历史响应回写成当前画面。

状态查询、空列表和空队列均为 HTTP 200；创建成功为 201；请求结构错误 400，认证失败 401，越权 403，不存在 404，阶段/编号冲突 409，超大载荷 413，限流 429，内部错误 500，暂不可用 503。业务错误仍按统一 JSON 返回。

### 4.3 创建对局

C 调用 POST `/games`，请求头增加 `Idempotency-Key: <32位UUID>`。

```json
{"protocol_version":"1.0","mode":"player_hides","runtime_mode":"mock"}
```

mode 为 `robot_hides/player_hides`；runtime_mode 为 `mock/robot`。相同幂等键及内容只能生成一局，返回 `data.state`。当前局正在进行或暂停时返回 `GAME_ACTIVE`，不能悄悄重开。

C 生成秘密数字、种子、局号，任务队列与内部轮次。机器人藏牌无需 B 就绪；玩家藏牌必须等 A/B/D 的必要能力就绪再开始真实流程。mock 模式也要明确显示为模拟，不伪装成 robot。

## 5 任务领取及执行规则

### 5.1 命令结构

```json
{
  "protocol_version":"1.0",
  "command_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "game_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_epoch":0,
  "target":"A",
  "command_type":"speech.say",
  "timeout_ms":15000,
  "payload":{"text":"请提出你的问题。","purpose":"prompt","answer_id":null,"sync_group_id":null}
}
```

命令恰含上述八个字段。各命令 payload 必须按下文完整填写；未用字段填 null，不临时添加字段。C 保留命令发放时的上下文，结果只对应该任务，不让模块自行推进下一轮。

### 5.2 生命周期

```text
queued → accepted → running → succeeded / failed / cancelled
                    └→ cancel_requested → cancelled 或实际执行结果
超时另记 expired；尚未确认停止的执行器保持 unknown，不自动解锁。
```

1. 拉到命令后先查本地处理记录。相同 command_id 不重复执行。
2. POST `task.accepted`，payload 为 `{}`。C 拒绝过期或不可运行任务时不得开始执行。
3. 执行前再次 GET 命令状态；取消或过期则回传 cancelled，不开始硬件动作。
4. POST `task.started`，payload 为 `{}`，随后执行；同一执行通道一次只运行一项任务，D 的 strategy/motion 通道独立。
5. POST `task.result`，固定三个字段：`status`、`result`、`error`。

成功：`{"status":"success","result":{本任务结果},"error":null}`。
失败：`{"status":"failed","result":null,"error":{"code":"TIMEOUT","message":"本次任务超时"}}`。取消时 status 改为 cancelled，error.code 使用 CANCELLED；result 仍为 null。

终态结果不可改写。相同命令结果以新 request_id 重复提交，C 仍不二次应用；冲突结果返回 `RESULT_CONFLICT` 并保留原记录。

### 5.3 取消与命令状态

执行期间每 250ms～500ms GET `/commands/<id>` 检查取消；该查询的 data 包含 `command`、`status`、`cancel_requested`、`remaining_ms`、`executor_state`（idle/busy/unknown）。超时后记录 expired，晚到终止回执只补记实际执行终态并释放资源，不推翻已生效的终态或推进游戏。

能取消的任务停止后才报 cancelled；不能立即停止的动作先保持执行状态，完成后报告实际结果。C 在执行器状态未知时不派同一 motion 通道的新动作。网络回执丢失不等于动作未执行，禁止盲目重做。

### 5.4 心跳与单实例

每模块进程启动生成 instance_id，每两秒发送 `module.heartbeat`。该事件 game_id、input_epoch、command_id 均为 null，payload 恰为：

```json
{"instance_id":"dddddddddddddddddddddddddddddddd","module_status":"ready","active_command_ids":[],"capabilities":["speech.say","speech.listen"],"runtime_mode":"mock"}
```

active_command_ids 为本实例正在执行的命令 ID 数组，A/B 最多 1 项，D 最多 2 项。module_status 为 `ready/busy/degraded/unknown`。加载模型期间为 degraded，不可先报 ready 再在首轮长时间加载。capabilities 只列真实可执行的本规范命令。X-Roban-Instance 与 payload.instance_id 相同。

同一角色只允许一个活动实例。第二个实例返回 `MODULE_CONFLICT`，不抢任务。超过六秒无心跳标离线；对局进入暂停，不把旧任务派给另一实例自动重演。重启后由 C 操作员核对空闲状态并发送 `control.module_reset` 解除旧绑定，payload 为 `{"module":"A或B或D","previous_instance_id":"旧编号","confirmed_idle":true}`。

## 6 A 语音接口

A 只执行以下两种命令，不直接调用游戏的 propose/confirm 内部函数。

### 6.1 speech.say

payload：`text`（1～200 字）、`purpose`（prompt/question/answer/confirmation/result/feedback）、`answer_id`（答案编号或 null）、`sync_group_id`（语音动作同步组或 null）。

成功结果固定为 `{"spoken":true}`。必须在实际播报结束后回传 success，发出播放请求不等于播报结束。播放器无法判断结束时以平台完成事件或可靠的播放返回为准；否则返回 `CAPABILITY_UNAVAILABLE`，不伪报成功。

C 先提交答案，再发 speech.say。重新播报同一答案沿用 answer_id 和原文本，但使用新 command_id。A 不改数字、真假、胜负或关键否定词。

### 6.2 speech.listen

payload 字段全部必填：

```json
{
  "allowed_intents":["question","final_submit","pause","exit","repeat_last","help"],
  "pending_id":null,
  "pending_version":null,
  "question_id":null,
  "max_listen_ms":15000
}
```

确认窗口只开放 confirm/cancel/pause/exit/help 等相应意图，pending_id 与 pending_version 由 C 填好。等待玩家回答时 allowed_intents 包含 answer，question_id 指向当前锁定问题。非确认窗口的 pending 字段为 null。

成功 result 恰含：

```json
{
  "intent":"question",
  "comparison":"gt",
  "number":5,
  "answer":null,
  "pending_id":null,
  "pending_version":null,
  "question_id":null,
  "utterance":"我想问是不是比五大",
  "parser":"qwen",
  "reason":null
}
```

| intent | comparison | number | answer | 绑定 |
|---|---|---|---|---|
| question | gt/lt/eq | 1～10 整数 | null | 非确认窗口 |
| final_submit | null | 1～10 整数 | null | 非确认窗口 |
| answer | null | null | true/false | 原样返回 question_id |
| confirm / cancel | null | null | null | 原样返回 pending_id、pending_version；有 question_id 时也回传 |
| pause / resume / exit / repeat_last / help | null | null | null | 仅当前 allowed_intents 允许时使用 |
| unsupported | null | null | null | reason 填 ambiguous/unsupported；C 追问，不扣次 |

parser 为 `rule/qwen/manual_mock`；utterance 最多 160 字，进入私密调试记录，不直接作为裁判逻辑。除表中对应项外，绑定字段为 null。unsupported 是诊断结果，允许在任一收音窗口返回，但不推进游戏；其他 intent 必须在 allowed_intents 中。无语音、ASR 失败或模型超时是任务失败，使用错误码，而不是随便生成一个意图。

支持“是七吗”和“我确定是七”的区别。多个数字、复合问题、“不大于”等未可靠实现的表达一律追问。千问输出必须做类型、范围和 allowed_intents 校验，不能给模型秘密数字或让其修改计次。

### 6.3 收音与控制

首版半双工：speech.say 成功结束后，C 才派 speech.listen；A 不在自己播报时开游戏收音。暂停时只保留 C 新派的控制收音窗口，allowed_intents 为 resume/exit/help。

语音中断动作不作为首版保证。C 操作员始终可用控制事件暂停；物理停止由 D 根据平台能力执行并反馈。

## 7 B 视觉与私密登记接口

### 7.1 标记与相机

统一 `DICT_4X4_50`，标记 ID `0～9` 分别对应数字 `1～10`。其余 ID 视为 unknown，不做取模。每张牌打印数字和对应标记，逐张核对；禁止各人采用不同映射。

相机话题通过共享配置选择。B 将 ROS 图像明确转换为 BGR 后处理。每次任务丢弃旧缓存，使用本次请求之后的新帧；至少三帧连续一致、单张有效牌、标记边长至少 25 像素才成功。重复引用同一帧不算三帧。

### 7.2 vision.capture

payload：

```json
{"purpose":"registration","camera_topic":"/camera/color/image_raw","dictionary":"DICT_4X4_50","min_consistent_frames":3,"min_marker_side_px":25,"attempt":1}
```

purpose 为 registration/reveal。字典、稳定帧数与最小边长按上述默认，后续只由共享配置统一调整。attempt 由 C 管理，B 不在一次任务内无限重试。

成功 result：

```json
{"purpose":"registration","value":7,"marker_id":6,"consistent_frames":3,"frame_seq":120,"captured_at":"2026-11-26T09:00:00+08:00","evidence_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}
```

value 必须等于 marker_id+1；evidence_id 必须属于本局本命令且已上传成功。无牌、多牌、未知标记、图像未稳定、相机不可用分别用规定失败码，不把无牌当作数字 0。

### 7.3 证据上传

POST `/evidence`，B 身份，`Idempotency-Key` 使用新的 32 位 UUID；重试沿用。请求：

```json
{"protocol_version":"1.0","game_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","command_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","input_epoch":0,"mime_type":"image/jpeg","image_base64":"JPEG字节的Base64"}
```

证据必须是实际 JPEG；解码后最多 2MiB，接口总请求体最多 4MiB。C 校验本局、任务归属、类型和大小后保存，201 返回 `data.evidence_id`、`data.sha256`。B 仅上传本次命令的一张代表证据，不上传整段视频。

GET evidence 成功返回实际 JPEG 字节及 Content-Type: image/jpeg，不套 JSON；认证或查询失败仍返回统一 JSON。C 按 evidence_id 查私密存储，不允许把路径拼接成任意文件读取。

同幂等键同内容返回原 evidence_id；同键改图冲突。证据目录和本地文件路径不作为接口值。客户端超时只能原样重试，不能反复生成重复证据。

### 7.4 registration.confirm

登记候选只交给藏牌玩家的 B 私密界面，不能由 A 公开读出数字。C 给 B：

```json
{"candidate_id":"ffffffffffffffffffffffffffffffff","candidate_version":1,"value":7,"evidence_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}
```

首版使用 B 自己的独立私密终端显示候选值和证据编号，并允许本地查看图片；由藏牌玩家输入确认或拒绝。不增加第二套对外 HTTP 业务接口，也不复用公开投屏终端。以后换成 GUI 时，对 C 的消息不变。成功 result 固定为：

```json
{"candidate_id":"ffffffffffffffffffffffffffffffff","candidate_version":1,"confirmed":true}
```

confirmed=false 表示玩家拒绝候选，C 重新采集；它不是设备错误。超时或命令被取消分别回传 failed/cancelled。B 不自行换 value 后确认，必须重新采集生成新候选。候选 ID、版本不匹配时不锁定。

揭牌在最终猜测锁定后进行。揭牌值可由 A 公开复述确认；登记确认始终只在私密界面进行。

## 8 D 策略接口

### 8.1 strategy.decide 的两种用途

**猜牌提问，purpose=guess_next：**

```json
{"purpose":"guess_next","mode":"player_hides","history":[{"question_id":"11111111111111111111111111111111","comparison":"gt","number":5,"answer":true}],"remaining_questions":6,"max_lies":1}
```

该任务严禁含 secret、登记证据、已发生假话位置或内部真假统计。D 根据公开 history 自己更新候选。成功 result 必须为以下之一：

```json
{"decision":"question","comparison":"lt","number":8,"answer":null,"lie_applied":null,"candidates":[1,2,3,4,5,6,7,8,9,10],"certainty":"not_final"}
```

```json
{"decision":"final_submit","comparison":null,"number":7,"answer":null,"lie_applied":null,"candidates":[7],"certainty":"unique"}
```

candidates 是按至多一次假话规则仍可成立的数字，升序、去重，1～10；最终猜测必须在 candidates 内。多候选仍需最终提交时 certainty=guess，不宣称唯一确定。question 的 certainty 固定 not_final；remaining_questions=0 时不能再返回 question。

候选为空返回 `NO_CONSISTENT_CANDIDATE`，C 暂停核查，不能直接判玩家作弊。七问保证由 D 的独立全路径测试证明，不能把模型生成的一段解释当成证明。

**机器人藏牌回答，purpose=answer_question：**

```json
{"purpose":"answer_question","mode":"robot_hides","secret":7,"question":{"question_id":"11111111111111111111111111111111","comparison":"gt","number":5},"question_ordinal":1,"history":[],"lie_used":false,"max_lies":1,"decision_seed":123456}
```

只有 robot_hides 的这类任务可把本方 secret 给 D。成功 result：

```json
{"decision":"answer","comparison":null,"number":null,"answer":true,"lie_applied":false,"candidates":[],"certainty":"not_final"}
```

D 用固定 decision_seed 对同局生成确定的假话计划，选择 0～7 中一个序号，0 表示不用假话。相同问题/上下文及任务重试必须返回相同建议，不能重随机。lie_used=true 时只能真实回答。

C 验证 answer 与 secret、comparison 的关系，以及 lie_applied 是否一致。建议合法后由 C 一次提交并消耗额度；D 不直接更新裁判历史。建议不合法暂停并记 `STRATEGY_INVALID`，不改秘密数字来迎合结果。

### 8.2 D 策略实现约束

建议纯函数设计，可离线输入公开历史运行；相同 command_id 缓存同一结果。搜索与动作线程分开。即使动作运行较慢，也不能让策略请求长时间占用模型或关节锁。

## 9 D 动作接口

command_type=motion.execute，payload：

```json
{"action":"nod","sync_group_id":"99999999999999999999999999999999","reason":"spoken_answer","answer_id":"88888888888888888888888888888888"}
```

action 固定为 `nod/shake/look_at_cards/reset_pose/celebrate`；基础必需为 nod、shake，其他以平台实测能力为准。未实现的动作回 `ACTION_UNSUPPORTED`，不能静默当作执行成功。非答案动作 answer_id=null；不需同步时 sync_group_id=null。reason 为 spoken_answer/observe/result/recovery。

成功 result 为 `{"action":"nod","executed":true}`。现有动作库接口由 D 适配，继承或封装原控制类，不修改共享 BodyHub 原文件。

C 以 A 的 task.started 事件作为答案动作的触发点，给 D 派相同 sync_group_id。不是精确音画同步承诺；D 负责动作节奏和执行反馈。动作仅收到答案对应的动作，不接收“这次是假话”等提示。

同一关节只允许一个活动动作。停止能力不足时不得强行假报 cancelled，实际完成后报告；状态不明时停止派后续动作，由 C 暂停等待人工核对。

## 10 C 状态、公开记录与规则

### 10.1 公开状态

公开状态包含以下固定字段，不存在的值填 null：

```json
{
  "protocol_version":"1.0",
  "game_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "mode":"player_hides",
  "runtime_mode":"mock",
  "phase":"waiting_answer",
  "paused":false,
  "resume_phase":null,
  "input_epoch":0,
  "remaining_questions":6,
  "history":[{"question_id":"11111111111111111111111111111111","comparison":"gt","number":5,"answer":true}],
  "pending":null,
  "locked_question":{"question_id":"22222222222222222222222222222222","comparison":"lt","number":8},
  "final_submission":null,
  "result":null,
  "started_at":"2026-11-26T09:00:00+08:00",
  "ended_at":null
}
```

无局时 game_id/mode/runtime_mode 等为 null，phase=idle，remaining_questions=7，history=[]。`locked_question` 是尚未完成的当前问题，不提前写进已确认 history。

pending 为 null 或 `{"pending_id":"编号","pending_version":1,"kind":"question|answer|final_submit|exit|register|reveal","comparison":null,"number":null,"answer":null}`。登记 pending.number 始终为 null。question/answer 等填对应公开字段，不包含原始识别文本和证据路径。

结束前 result=null。结束后：

```json
{"outcome":"guesser_win","reason_code":"CORRECT_GUESS","revealed_number":7,"lie_count":1,"lie_rounds":[2]}
```

outcome 为 guesser_win/hider_win/invalid/exited/interrupted；玩家猜错为 hider_win；超额假话或核验异常为 invalid，不生成普通胜负。reason_code 使用 CORRECT_GUESS/WRONG_GUESS/EXCESS_LIES/REVEAL_MISMATCH/UNVERIFIED/USER_EXIT/SERVER_INTERRUPTED。未可靠核验或退出时 revealed_number、lie_count 为 null，lie_rounds=[]。

### 10.2 状态枚举

| phase | 允许的业务输入 |
|---|---|
| idle | C 创建新局 |
| registration_capture | 等 B 识牌结果；可暂停 |
| registration_confirm | 等 B 私密确认；可暂停 |
| waiting_question | 等 A question/final_submit/control |
| waiting_question_confirm | 等 A confirm/cancel/control |
| waiting_strategy | 等 D 策略结果；可暂停 |
| waiting_answer | 等 A answer/control |
| waiting_answer_confirm | 等 A confirm/cancel/control |
| waiting_final_confirm | 等 A confirm/cancel/control |
| reveal_capture | 等 B 揭牌结果；可暂停 |
| reveal_confirm | 等 A 对公开揭牌值确认；可取消后重采集 |
| paused | 只接受恢复、退出和清理旧任务的反馈 |
| finished | 只允许查记录或 C 创建下一局 |

具体输入只能从 C 派发的任务返回，处于允许阶段也不能凭空造一个 command_id 提交。speech.say 执行期间不开放普通收音；任务状态与 phase 共同限定输入。

### 10.3 计次与提交

- robot_hides：问题确认后锁定本轮，等 D 合法回答建议，再将问答一次提交并扣一次。策略失败时不计成已完成问题，也不允许绕过锁定问题另开下一轮。
- player_hides：D 问题锁定并播报后，玩家回答确认才追加问答并扣一次。取消回答只取消该回答，原问题仍需回答。
- 正式重复提问使用新 question_id 和任务编号，正常计次；repeat_last 只重播记录，不调策略、不换答案、不扣次数。
- 最终提交只有一次，确认后锁定；七问用尽仍可最终提交。锁定后的答案不可撤回或覆盖。
- 假话额度按已提交回答计算，暂存建议、重播和任务重试不额外消耗。

## 11 两种玩法完整时序

### 11.1 机器人藏牌

1. C 创建 robot_hides，生成 1～10 秘密数字及 decision_seed，二者仅存私密区。
2. C 派 A speech.say 说明规则；播报成功后派 speech.listen。
3. A 返回 question；C 建立 pending、发复述并开绑定 pending 的确认窗口。
4. A confirm 后 C 锁定问题，发 D strategy.decide/answer_question。
5. D 建议通过核验后，C 一次提交 history、剩余次数、lie_used 和 answer_id。
6. C 发 A speech.say 播答案；A started 后 C 发 D 对应 nod/shake。声音成功后再开放下一输入窗口，动作失败单独记录。
7. 玩家 final_submit 经复述确认后锁定，C 直接比较秘密数字给出结果并播报。此玩法不要求 B 揭牌。
8. 语音重播只使用已提交文本和答案，不重新调用 D。

### 11.2 玩家藏牌

1. C 创建 player_hides，必要时发 D look_at_cards；确认动作终止后发 B vision.capture/registration。
2. B 返回候选和证据，C 发 B registration.confirm；藏牌玩家在私密界面确认后 C 锁定数字。A 只播“登记完成”，不播牌值。
3. C 发 D strategy.decide/guess_next，仅传公开历史和剩余次数。
4. D 返回 question，C 校验并锁定 question_id，发 A 播问题；播报成功后开 answer 窗口。
5. A 返回 answer，C 复述并开确认窗口；confirm 后一次追加 history、扣次。内部可计算真假，但不得向 D 泄露。
6. 重复 3～5。D 返回 final_submit 时，C 公开猜测并确认；确认后锁定最终答案。
7. C 发 B vision.capture/reveal，结果由 A 公开复述确认。确认后比较登记值与揭牌值，并核验已确认回答的假话额度。
8. 一致且假话≤1时正常判定；确认揭牌第一次不一致重新采集，第二次仍不一致记 REVEAL_MISMATCH。识牌失败不会消耗这两次“不一致”次数。
9. 假话超过一次记 EXCESS_LIES；始终不能核验则暂停或退出为 UNVERIFIED，不自动判玩家输。

## 12 暂停、取消、重发与恢复

### 12.1 C 控制事件

C 身份通过 `/events` 发以下事件，command_id=null，其他信封字段正常绑定当前局。

| event_type | payload | 行为 |
|---|---|---|
| control.pause | {} | 暂停并取消当前输入/计算窗口 |
| control.resume | {} | 释放条件满足后恢复新窗口 |
| control.exit | {"confirmed":true} | 操作员确认后退出，不计普通胜负 |
| control.replay | {"answer_id":"已提交答案编号"} | 重播原答案，不扣次 |
| control.module_reset | module、previous_instance_id、confirmed_idle | 核对设备空闲后解除旧实例绑定；不恢复旧游戏结果 |

A 识别到的 pause/resume/exit/repeat_last 由 C 在 task.result 内转换为对应流程，A 不能冒用 C 身份发控制事件。

### 12.2 代次与待确认内容

暂停、恢复、取消/替换待确认内容、关闭/重开输入窗口时，C 更新 input_epoch；恢复有待确认内容时同时更新 pending_id/version。客户端所有事件回传原命令的代次，不读取当前代次给旧任务“补票”。

取消的是未提交内容。已经提交的 history 不提供修改入口。退出确认优先挂起当前待确认内容，取消退出则恢复原内容并刷新编号，不静默丢弃待回答的问题。

### 12.3 旧结果和执行器清理

旧局号、旧窗口或取消命令的结果不能推进游戏。已知旧任务的终止回执仍允许更新任务账本，返回 `ok=true`、`code=STALE_RESULT_IGNORED`、disposition=ignored_for_game，以便释放执行资源；不恢复旧阶段或扣次。未知任务返回 404。

暂停期间 C 可以派新的“仅控制”语音窗口。resume 先检查 A/B/D 的必要能力与活动硬件任务；动作状态未知时返回 EXECUTOR_NOT_IDLE，保持暂停，不派下一动作。

已经处理的请求重发仅取回原结果；不要因为回执中有旧状态就重开收音或执行动作。模块必须依据命令账本状态决定是否执行。

### 12.4 服务或模块重启

health 的 server_instance_id 改变说明 C 重启：旧活动局按中断处理，禁止把私密日志直接当成可续局状态。A/B/D 清理旧待发送队列，不把旧命令应用到新局。

模块重启不能证明旧动作未发生。已开始但未确认终态的任务标 unknown，人工核对后再复位实例。协议通过去重避免正常重发造成重复提交，不承诺硬件故障和进程崩溃下物理动作绝对只执行一次。

## 13 超时、失败码与退化

### 13.1 固定初始参数

| 项目 | 初始值 |
|---|---|
| HTTP 连接/读取 | 2 秒 / 5 秒；长轮询等待最多 1 秒 |
| POST 网络重试 | 原请求最多共 3 次，间隔 300ms、900ms；沿用 request_id/幂等键及内容 |
| 心跳/离线 | 每 2 秒；6 秒无心跳标离线 |
| queued 等待/接单后开工 | 最多 5 秒 / 最多 3 秒，超限暂停定位 |
| speech.say | 15 秒；常用台词不超过 200 字 |
| speech.listen | 15 秒，包含等待用户说话与本次解析 |
| vision.capture | 5 秒，失败最多发 3 次独立采集命令 |
| registration.confirm | 30 秒，超时暂停，不能默认同意 |
| strategy.decide | 5 秒；应预热或预计算，不在命令里首次下载模型 |
| motion.execute | 10 秒；超时不等于已经停止 |

网络重试仅用于连接失败、超时、回执不完整及暂时的 502/503；400/401/403/404/409/413 不自动重发，先处理原因。429 遵守 Retry-After，没有该头时等一秒再按原请求重试。所有网络重试不计作新的业务提问。

命令 timeout_ms 由 C 发出，从任务 started 起计时，另有排队/开工限制。客户端以首次执行该命令的单调时钟计时，不因重复拉取命令重置计时；C 的账本判定为准，不依赖客户端日历时间一致。

A 无语音/解析失败连续三次暂停；B 采集失败三次暂停。TTS 确定失败且确认播放器空闲时最多自动重播一次；播放状态未知时暂停，禁止叠播。策略计算确定失败可取消后重试一次，仍失败暂停；同一个问题不重新随机答案。

这些是联调默认值，统一放在 C 配置。需要调参时 C 发布一次共享配置，不允许模块各自无限延长等待。

### 13.2 错误码

| 类别 | code | 含义/处理 |
|---|---|---|
| 请求 | BAD_REQUEST / UNSUPPORTED_VERSION / REQUEST_CONFLICT / RESULT_CONFLICT | 校正格式或新建真正的新操作，不反复原样撞接口 |
| 身份 | UNAUTHORIZED / FORBIDDEN / MODULE_CONFLICT | 检查本模块令牌与进程实例，不能冒用其他身份 |
| 状态 | GAME_ACTIVE / STALE_GAME / STALE_INPUT / INVALID_PHASE / PENDING_MISMATCH | 不提交；刷新流程或等待新命令 |
| 命令 | COMMAND_EXPIRED / COMMAND_CANCELLED / COMMAND_NOT_RUNNABLE / EXECUTOR_NOT_IDLE | 不启动新动作；回报真实终态 |
| A | NO_SPEECH / ASR_FAILED / MODEL_TIMEOUT / TTS_FAILED | 受限重试或暂停，不生成默认答案 |
| B | CAMERA_UNAVAILABLE / NO_CARD / MULTIPLE_CARDS / UNKNOWN_MARKER / UNSTABLE_IMAGE / EVIDENCE_FAILED | 调整或重新采集，不计问答次数 |
| D 策略 | NO_CONSISTENT_CANDIDATE / STRATEGY_TIMEOUT / STRATEGY_INVALID | 暂停核查或受限重试，不泄露私密数字修正策略 |
| D 动作 | ACTION_UNSUPPORTED / ACTION_FAILED / ACTION_TIMEOUT | 记录动作故障，核对执行器空闲后继续 |
| 资源/服务 | NOT_FOUND / PAYLOAD_TOO_LARGE / RATE_LIMITED / SERVICE_UNAVAILABLE | 分别对应 404/413/429/503；不把缺失资源当作任务成功 |
| 公共 | CAPABILITY_UNAVAILABLE / TIMEOUT / CANCELLED / INTERNAL_ERROR | 不伪报成功；按任务和硬件状态退化 |

task.result 的 error.code 使用本表对应模块码；HTTP code 用请求/状态/命令类及 OK、STALE_RESULT_IGNORED。错误消息不包含令牌、秘密牌值或私密图片内容。

## 14 日志、证据与秘密信息

公开查询只包含第十节的白名单字段。登记候选、原始相机图、原始识别文本、内部真假统计、种子和任务私密 payload 不出现在公开日志。结束后按核验结果有条件公开数字及假话位置，不提前泄露。

命令查询按角色过滤，D 在 player_hides 下只能得到公开策略输入，不能借 robot_hides 的回答任务读到玩家秘密。B 的登记页面只给藏牌玩家查看，不把截图发进小组公开群。

日志至少记录：局号、服务实例、来源、事件编号、命令编号、代次、接收/执行时间、处理状态、失败码，以及提交后的公开快照。私密与公开分别保存；证据放私密目录，通过 evidence_id 关联，不将本地路径传给其他电脑。

普通事件请求体最多 64KiB，JSON 各字段长度受约束；证据按第七节单独限额。不把 JPEG Base64、令牌和整段录音写入事件日志。自动模拟和真实机器人记录分别标记 runtime_mode。

## 15 独立开发、模拟模式与验收

### 15.1 每个人不必等整机

- A 用固定 speech.say/listen 命令测试，先返回规则解析和人工模拟意图，再接真实 ASR/千问/TTS；mock 必须标明 manual_mock。
- B 用照片或录像测试标记映射与稳定判定，用本地私密确认界面返回 true/false，再接 ROS 相机。
- D 用公开 history 离线验证提问策略，用固定秘密和种子验证回答；动作先用明确 mock 执行器，再接现有平台动作。
- C 用协议样例和假客户端验证任务队列与状态机，再接真实模块。mock 与 robot 的任务/回执不得混用。

client 必须对重复 command_id 缓存结果，禁止同一命令重复播报、采集、确认或动作。不要用输出“成功”冒充真实硬件返回。

### 15.2 必测矩阵

| 成员 | 必测内容 |
|---|---|
| A | 标准/口语问题；question 与 final_submit；confirm 与 answer；取消、无语音、歧义；旧窗口回执；播报失败与重复命令 |
| B | 十个 ID 映射；无牌、多牌、未知 ID；稳定帧；证据重发；私密确认拒绝/超时；旧采集结果；登记值不公开 |
| C | 七问与最终提交；确认与取消；请求/结果去重；拒绝越权；暂停和迟到结果；任务超时；揭牌冲突；超额假话；连续新局 |
| D | 十个数字全真及所有合法一次假话分支；零剩余次数；候选为空；固定种子重试一致；lie_used=true；动作失败及状态未知 |
| 全组 | 连续十局双向玩法；正常、假话、取消、暂停、模块断开与新局；核查日志、次数、结果和秘密隔离 |

### 15.3 验收时提交

各成员提供入口脚本、配置例子、实际能力说明、成功和失败样例、测试输出。先通过离线格式与业务测试，再在机器人上核对相机、声音和动作。模型、相机或动作实测结果可以不同，但跨模块接口不随意变形。

## 16 开发顺序与现有原型迁移

1. 按本规范固定目录、命令类型、结果格式和示例；A/B/D 先写各自命令处理函数，支持 mock。
2. C 实现 health、公开状态、创建对局、events、命令领取与状态查询，先让四个假客户端走完整轮次。
3. C 接入私密证据与 B 确认；A 接入实际输入输出；D 接入回答建议、策略和动作；最后再进行 robot 联调。
4. 现有 Python `RefereeService.handle` 的 propose/confirm 等为内部 v0.4 接口，不能把本规范的 HTTP 信封直接塞入它。C 在网络适配层校验身份和任务后再转换，并增加 waiting_strategy、播报回执等阶段。
5. 内部 remaining/history.kind 等字段在网络层分别规范为 remaining_questions/history.comparison。迁移由 C 负责，不要求其他成员兼容两个协议。
6. 现有 8765 `/api/games` 是公开记录页接口，不等于新业务 8780 的 `/api/v1/games`，不能互相替换。

本规范作为 1.0 基线。只修正描述或实现错误时可补丁更新；改变字段、事件语义或权限必须由 C 发布统一版本及迁移说明，避免每人维护一份不同的“最终接口”。这不需要重新让所有成员设计路径。

## 17 快速实现清单

**A 李馨瑶**：配置 base_url 和 A 凭据 → 心跳 → 拉 A 命令 → accepted/started → 实现两种 speech 命令 → 回传 task.result → 缓存 command_id → 测试取消和失败。

**B 刘九尔**：配置 B 凭据 → 固定字典与映射 → 拉 B 命令 → 新帧稳定识别 → 上传证据 → 私密确认界面 → 返回结果 → 测试登记与揭牌冲突。

**C 刘杰**：实现路径表 → 身份和结构校验 → 命令账本与串行状态 → 双向任务编排 → 私密隔离与核验 → 公开页及日志 → 失败/迟到/重启处理。

**D 吴零**：配置 D 凭据 → 分离策略与动作处理 → 公开历史候选与七问验证 → 固定种子回答 → 动作封装与状态反馈 → 去重、取消和超时测试。

所有人只实现自己模块的执行与适配；共享协议和整机联调按上述分工完成。部署时仍需真实填写 C 的局域网 IP、令牌和相机配置，这些是环境参数，不是未确定的接口路径。


## 附件使用说明

同包提供 `contracts/protocol_v1.schema.json` 与 `contracts/examples_v1.json`。后者含 45 份完整创建请求、命令、接单/开始/结果事件、心跳、控制和公开状态样例，均为模拟格式数据。

这些样例已通过 Schema 校验及命令归属、确认绑定、标记映射等关联检查，并验证 12 份非法变体被拒绝。该结果仅证明附带样例的格式与关联自洽，不代表 8780 服务、算法或机器人已实现。

JSON Schema 不能替代权限、阶段、固定种子、候选真实性、JPEG 解码、执行器终态和七问保证的业务测试。文档中的负载限制、任务生命周期和所有权规则由各自实现落实。
