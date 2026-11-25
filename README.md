# Roban 多轮猜牌机器人

课程小组项目。规则与阶段验收以根目录项目方案 PDF 为准。

## 当前状态

已建立六个 catkin 包骨架。D 分支已添加离线策略、验证程序及头部动作示例，具体实测边界见 [D 模块说明](robot_strategy/README.md)；尚未完成 ROS 消息、整机启动或 catkin 编译验收。目录存在不代表模块完成。

| 包 | 负责人 | 职责 |
| --- | --- | --- |
| robot_speech | A | 句式解析、语音输入、确认与播报反馈 |
| robot_cards | B | 卡牌识别、登记揭牌证据、私密确认 |
| robot_referee | C | 状态机、计次、去重、秘密隔离与结果核验 |
| robot_strategy | D | 候选推理、回答策略、已有动作适配 |
| robot_interfaces | 全组 | 接口冻结后添加消息与服务 |
| robot_bringup | 全组 | 整机启动与配置 |

业务包的 src/包名/ 存核心 Python 逻辑，scripts/ 存 ROS 入口，tests/ 存独立测试。设备依赖放在适配层，核心逻辑尽量离线运行。

先阅读 [协作说明](docs/development.md)、[接口草案](docs/interfaces.md)、[部署说明](docs/deployment.md)。进度见 [进度表](docs/progress.md)。
