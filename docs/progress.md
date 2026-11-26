# 进度

> 最近更新：2026-11-26（A 侧按 TEAM_INTERFACE v1.0 重做 A→C 链路后同步）

| 项目 | 状态 | 下一步 |
| --- | --- | --- |
| 项目方案 | 已有 | 根目录 PDF |
| 开发骨架 | 已建立 | 确认维护者和许可证 |
| 公共接口 | **v1.0 已发布**（根目录 `TEAM_INTERFACE.md`） | C 实现 8780 调度服务后四模块联调 |
| A 语音 | **离线闭环完成**：意图解析 + IAT 组装 + HTTP 命令循环，366 项测试通过 | 上机验证播报完成信号与识别出口 |
| B 视觉 | ArUco 卡牌识别已提交（`robot_cards/`） | 多帧稳定性判定、私密确认界面 |
| C 裁判 | 本地规则可用；**8780 网络调度接口与任务队列未实现**（规范自述） | health / 命令领取 / events 三个路径 + 任务队列 |
| D 策略行为 | 多局策略、七问穷举与 A 文本联调通过；见 [D 阶段成果](records/2026-11-26_D_replay_integration.md) | 对接 C 的任务队列，验证语音触发动作及重复投递 |
| 机器人编译与实测 | D 已完成部分独立动作试验；整机联调待验 | 按部署说明验证 |

## A 的进度依据

```text
python3 -m pytest -q                 # 366 passed
python3 scripts/check_c_interface.py --self-test
python3 scripts/dialogue_demo.py     # 三条场景，产出 evidence/logs/*.jsonl
```

- 协议层：`team_protocol.py`（8 字段信封、8 字段命令、10 字段收音结果）
- 传输层：`http_client.py`（令牌、实例号、重试、长轮询）
- 循环层：`command_agent.py`（accepted → started → result、命令去重、心跳）
- 命令层：`speech_commands.py`（`speech.say` / `speech.listen`）
- 离线验证：`tests/support/fake_c_server.py` 起一个真 HTTP 假 C

**未完成**：实机未跑；播报完成信号未确认（拿不到时按规范回 `CAPABILITY_UNAVAILABLE`，
不伪报成功）；与 C 的 8780 服务未联调。

进度更新附版本、命令和实际证据。阶段顺序：独立原型、模拟闭环、单向实机、双向实机、验收交付。
