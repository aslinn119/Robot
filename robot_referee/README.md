# 游戏裁判（C 刘杰）

已实现 HTTP v1.0 软件模拟服务。统一入口与运行方法见 [network_service/README.md](network_service/README.md)。

可调用程序：`network_service/tools/run_referee_server.py`；D 策略客户端：`network_service/tools/run_d_strategy_client.py`。

正式 HTTP 规范：[HTTP_INTERFACE_V1.md](network_service/docs/HTTP_INTERFACE_V1.md)。原 ROS 包骨架保留，暂不需要 catkin 构建本服务。
