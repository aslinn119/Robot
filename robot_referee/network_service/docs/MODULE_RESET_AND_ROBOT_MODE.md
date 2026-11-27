# C 模块复位与无动作 robot 模式

2026-11-27 实现。此文档描述代码行为，软件测试不等于下周实机验收。

## 启动

保留现有令牌，不要重新生成。停止旧服务后，在 network_service 目录：

```bash
source runtime/team_tokens.sh
.venv/bin/python tools/run_referee_server.py --host 0.0.0.0 --enable-robot
```

不传 --enable-robot 时仅允许 mock 新局，robot 返回 503 ROBOT_MODE_DISABLED。启用后仍要逐项检查就绪条件。两种模式均不派发 motion.execute；动作接入另行验收。

## 心跳与模式要求

心跳保留原五个字段，实例号为 32 位小写 hex；上报模式为 mock/robot，capabilities 只能包含本角色的规范命令，active_command_ids 必须属于已知的本角色命令。同一实例在活动对局中修改模式或能力返回 409 MODULE_CONFIG_CHANGED，需要先结束本局或复位重连。

| 角色 | robot 新局的必要能力 | 模式要求 |
|---|---|---|
| A | speech.say、speech.listen | robot，真实播报与真实收音已准备 |
| B | vision.capture、registration.confirm | robot，真实采集与私密确认已准备 |
| D | strategy.decide | 可为 robot；也允许只声明 strategy.decide 的 mock 纯计算客户端 |

三方必须在六秒内有心跳，module_status=ready，active_command_ids 为空。busy/degraded/unknown 不放行。两种新卡牌规则都需要 B：robot_hides 开局识牌，player_hides 最终揭牌。

C 只验证上报及任务状态，不替模块判断物理设备是否真正正常。ready 应由模块确认启动和必要依赖就绪，具体成功由任务结果反馈。

## 查询绑定（仅 C）

GET `/api/v1/operator/modules`，请求头 Authorization: Bearer <C令牌>。返回 modules.A/B/D 的 instance_id、module_status、runtime_mode、capabilities、active_command_ids，以及 robot_enabled、motion_enabled。令牌、秘密牌值和证据不返回。

```bash
.venv/bin/python tools/manage_module.py list
```

## 模块复位

操作顺序：模块负责人停止旧进程 → 现场核对设备空闲 → 等旧实例至少六秒无心跳 → 查询当前公开状态与旧绑定 → C 发复位 → 新进程使用新实例号连接 → 检查就绪 → 显式恢复或新建对局。

不能仅凭 offline 自动确认设备空闲。复位不是硬件急停，也不控制 ROS 设备。

POST `/api/v1/events`，C 令牌，示例为当前没有活动局时：

```json
{
  "protocol_version":"1.0",
  "request_id":"11111111111111111111111111111111",
  "game_id":null,
  "input_epoch":null,
  "source":"C",
  "command_id":null,
  "event_type":"control.module_reset",
  "payload":{
    "module":"A",
    "previous_instance_id":"22222222222222222222222222222222",
    "confirmed_idle":true
  }
}
```

存在活动局或暂停局时，game_id/input_epoch 必须使用最新公开状态。定时器可能先暂停并更新 input_epoch，STALE_INPUT 时先重新查询状态，不盲重放旧事件。网络重试必须原样复用 request_id 和内容；更改代次属于新请求，换新 ID。

成功 HTTP 200，外层仍为统一信封：ok=true、code=OK、replayed=false；data 为：

```json
{"disposition":"applied","command_status":null}
```

相同请求重发返回 replayed=true，不重复复位。成功后，查询该角色 instance_id=null，等待新实例注册。

命令行示例（旧编号替换为查询结果）：

```bash
.venv/bin/python tools/manage_module.py reset --module A --previous-instance-id 22222222222222222222222222222222 --confirmed-idle
```

## 任务和游戏处理

- 活动局保持或进入 paused，不自动 resume，不清空已确认历史、不扣次。
- 被复位模块的 queued/accepted/running 以及 executor_state=unknown 任务记为 cancelled，保留取消请求与操作员复位审计，不伪造 success/result。
- confirmed_idle 是操作员对“执行器已空闲”的人工确认依据；不代表旧任务业务成功。
- 旧实例进入持久化拒绝名单，再发心跳或回执为 409 INSTANCE_RETIRED，不允许抢回绑定。
- 新实例不能提交被复位的旧任务，也不会领取这些旧任务。需要继续时由 C 恢复阶段生成新的任务编号和窗口。
- 其他模块仍在执行或状态未知时，恢复返回 409 EXECUTOR_NOT_IDLE；必须先得到结束回执或人工复位相应模块。
- 心跳失联会暂停活动局，不自动接管。暂停后旧播报可继续完成，迟到成功只更新旧任务，不推进游戏，也不提前打开新收音窗口。
- 复位、审计和请求缓存与日志原子写入，写入失败回滚并返回 503 JOURNAL_UNAVAILABLE。

## 主要拒绝条件

| HTTP / code | 条件 |
|---|---|
| 401 UNAUTHORIZED | 缺少/错误令牌 |
| 403 FORBIDDEN | 非 C 复位或查询管理信息 |
| 400 BAD_REQUEST | 字段缺失/多余、角色非法、UUID 非法、心跳能力不合法 |
| 409 IDLE_CONFIRMATION_REQUIRED | confirmed_idle 不是 JSON true |
| 409 MODULE_NOT_BOUND | 当前没有该角色绑定 |
| 409 INSTANCE_MISMATCH | previous_instance_id 不匹配 |
| 409 MODULE_STILL_ONLINE | 旧实例六秒内仍有心跳 |
| 409 STALE_INPUT | 活动局号或代次已变化 |
| 409 REQUEST_CONFLICT | 同请求 ID 改了内容 |
| 409 INSTANCE_RETIRED | 被复位的旧实例重新发送事件 |
| 503 ROBOT_MODE_DISABLED | 未显式启用 robot |
| 503 MODULE_OFFLINE / MODULE_NOT_READY | 必要角色离线/未就绪/仍有活动任务 |
| 503 CAPABILITY_UNAVAILABLE | 缺少必要能力 |
| 503 RUNTIME_MODE_MISMATCH | A/B 使用 mock，或 D mock 混报硬件能力 |

NO_SPEECH、TIMEOUT、TTS_FAILED、CAPABILITY_UNAVAILABLE、BAD_REQUEST、ASR_FAILED、PARSER_FAILED、INTERNAL_ERROR、CANCELLED 等失败回执保持原任务信封。C 接受合法失败/取消终态并暂停当前未失效的流程，不伪造完成；unsupported 成功意图继续按追问流程处理。首轮不增加自动无限重试。

## 验证与边界

覆盖管理权限、在线拒绝、错误旧编号、显式确认、无局复位、活动局暂停、旧任务/旧实例隔离、幂等、日志失败回滚、重启后的拒绝名单、robot 准入和两种完整软件对局。硬件依赖均为模拟回执，未控制真实设备。

服务器重启仍将旧活动局归档为 interrupted，不恢复旧执行器。进程内复位现在可单独恢复角色；不承诺跨服务器重启接续原局。运行目录只允许一个服务进程。
