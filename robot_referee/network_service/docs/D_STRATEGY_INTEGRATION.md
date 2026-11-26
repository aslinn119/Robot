# D 新版策略接入说明

当前以 GitHub main 的 D 官方统一入口 `robot_strategy.team_strategy.decide` 为准。原样快照位于 `src/vendor_d/`，具体仓库提交与三份源码 SHA256 见 `D_STRATEGY_SOURCE.json`。旧策略已备份，不修改 D 原始算法。

## 调用关系

`run_d_strategy_client.py` → `network_v1.d_strategy_adapter.decide` → `vendor_d.team_strategy.decide`。

统一调用格式：`decide(payload, game_id=command['game_id'], profile=frozen_profile)`。payload 保持 HTTP v1.0，不额外加入秘密字段。

- 猜牌：由 D 根据局号、公开历史和剩余次数决定提问；支持开场轮换和偏好。
- 藏牌：由 D 的 hide_plan 使用 decision_seed、正式问题序号和 lie_used 生成确定回答。C 不再自行生成假话计划。
- 同局上下文固定；客户端从最近 20 条对局概要中选择正常结束且合法的公开记录，调用 replay_profile。中断或无效局不参与偏好。
- 仅剩多候选且次数为零时，D 返回 certainty=guess 的显式猜测，C 不将其当作唯一确定。
- 猜牌输入不含秘密数字；新版卡牌可见性规则见 `CARD_GAME_RULES.md`。

## 验证范围

D 原始全开场脚本：10 种开场、1144 个合法节点、582 条终止路径通过，最大七问。C 集成测试使用固定局号，覆盖其 58 条合法完整对局路径。二者测试范围不同，不能把 582 条都称作 C 完整对局验证。

D 原始策略、藏牌计划、跨局偏好测试已加入共享测试目录。全部测试均为软件调用，没有执行机器人动作。

## 生效

入口仍为 `tools/run_d_strategy_client.py`，默认服务器 `http://127.0.0.1:8780`。更新文件后须停止旧 D 客户端再启动。由于 C 当前绑定模块实例且没有 reset 接口，应在旧局结束后统一重启 C/A/B/D，避免 MODULE_CONFLICT。

本轮只更新纯策略和客户端，没有调用或替换 D 的动作脚本。共享目录使用原样快照，因此不依赖机器人旧独立目录的版本。
