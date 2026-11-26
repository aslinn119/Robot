# D 策略与 C 裁判调用说明

本次调用 D 已交付的真实纯 Python 策略函数，未调用机器人动作。

## 源码来源与保留方式

机器人挂载路径：
`Z:\team_project_d\alice_stage1_20261119\robot_strategy\src\robot_strategy\strategy.py`

原样快照：`src/vendor_d/strategy.py`。源文件与快照 SHA256 均为：
`22E93ACE76CFDCB1E5741E9F9305843D7FDB05F0C1E24567870E276D6C2419B8`。

D 目录内 README 仍写着骨架，但 strategy.py 已实际实现函数。此说明以读到并执行的源码为准；没有覆盖或修改机器人上的 D 文件。

## 接口适配

适配文件：`src/network_v1/d_strategy_adapter.py`，入口：

```python
from network_v1.d_strategy_adapter import decide
result = decide(command['payload'])
```

| 网络协议 | D 已实现的函数字段 |
|---|---|
| history[].comparison | history[].kind |
| remaining_questions | suggest(history, remaining) 的 remaining |
| 合法候选 candidates | 排序后的 s0 + s1 |
| decision=question | status=question 的 proposal |
| decision=final_submit | status=certain、proposal.kind=submit |
| answer、lie_applied | answer_suggestion 返回的 answer、uses_lie |

D 对“下一问”的搜索算法保持原样。适配器不读取 C 私密登记值，只将该任务允许的公开历史交给 suggest。

D 的藏牌回答函数接收 use_lie 开关，尚未直接接收协议的 decision_seed。适配器以固定 seed 选择 0～7 的计划序号，再调用 D 的 answer_suggestion；这是适配层补充的确定性计划。假话额度仍由 C 核验、确认后记账，不由适配器扣减。

D 返回 inconsistent 或 insufficient 时，适配器抛出 StrategyUnavailable，不编造候选或猜测。接入长期运行的 D 网络客户端时，应将其转为明确的失败回执，供 C 暂停处理。

## 自动调用方式

```powershell
cd D:\RobanGuessCard_C_Liujie
.\.venv\Scripts\python.exe tools\run_d_integration.py
```

测试会：

1. 枚举 D 策略树的全部 56 条合法路径。
2. 每条路径实际通过 C 的登记、私密确认、D 提问、回答确认、最终猜测及揭牌流程。
3. 检查最终猜中、最多七问、假话次数不超过一次。
4. 验证藏牌回答在固定种子下重试一致，且不会使用第二次假话。
5. 验证信息不足时不会编造成功结果。

其中 A、B、JPEG 图片仍是软件测试夹具；真正被调用的是 D 的策略函数和 C 的裁判逻辑。不是语音识别、实际识牌或动作的硬件验收。报告自动保存到 logs/d_integration_*.txt。

## 后续联调边界

当前完成的是本地函数适配及自动对局验证，还没有启动 D 常驻的 HTTP 任务拉取客户端。该客户端需要把 strategy.decide 的 payload 传给 decide，再回传规范任务结果。motion.execute 仍由 D 的机器人动作端单独负责，不能用策略测试结果代替动作完成回执。
