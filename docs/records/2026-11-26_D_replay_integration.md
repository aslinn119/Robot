# 2026-11-26 多局策略与语音文本联调

个人工作树基于 d83762c，A 源码取自团队主线快照 63ea651（A 提交 8de4818）。环境为 Windows Anaconda Python 3.12。业务入口为 robot_strategy.team_strategy.decide(game_id, payload, previous_openings=..., style=...)；payload 遵循 TEAM_INTERFACE.md 第 8 节。网络拉取与任务账本另行对接。

连续游玩时，由调用方按时间提供同一场次已结束对局的公开快照，在开局调用 replay_profile，并在本局重试时复用同一快照结果。新场次传空列表。协议没有玩家身份字段，不从历史猜测玩家身份。每五局覆盖五种开场切分；最近三次玩家自主选择的大小比较首问用于估计偏好，样本不足两次或平票时混合。机器人藏牌的计划仍由 C 的 decision_seed 决定。

在 PYTHONPATH 加入 D 的 robot_strategy/src 后运行：
- python -m unittest discover -s robot_strategy/tests -q（17 项）
- python robot_strategy/scripts/verify_strategy.py --all-openings（582 条合法终止路径，最多七问）
- 另在 PYTHONPATH 加入 A 快照的 robot_speech/src，运行 python robot_strategy/scripts/verify_speech_strategy.py（真实文本解析、模拟裁判确认及十局同牌，双角色业务格式）。
- A 快照的 test_team_protocol.py 和 test_speech_agent.py 共 50 项通过，回环测试使用 NO_PROXY=127.0.0.1,localhost。初次沙箱测试有 8 项失败，复测同时改变了回环权限和代理设置，无法单独归因。

上述联调未连接正式 C 服务或机器人。等待 C 实例和命令样例后再验证实际队列、重复投递及 A 开始播报后的动作反馈。
## 主线交付与复测

在主线 b8cc7e6 与 D 合并后的工作树复测，D 单测 17 项、A 全套单测 368 项通过。十个首问的 582 条合法终止路径均在七问内唯一确定；A 文本解析与 D 策略通过双角色离线联调。

动作侧交付头部与全身调试入口。败局入口 lose 使用手摆示教鞠躬 bow_taught，标称 4.1 秒。八项原始现场动作日志和示教版逐帧预览的验证范围见[动作实机记录](2026-11-26_D_head_lab.md)。下一阶段由 C 派发 strategy.decide 和 motion.execute，核对重复领取、语音开始后的动作触发及实机结束反馈。
