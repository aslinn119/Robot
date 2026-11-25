# 模块测试

使用标准库 unittest。覆盖比较边界、一次谎言、候选为空、问数耗尽、非法输入、回答额度、轨迹范围和返回姿态、增加幅度后的轨迹，以及模拟 ROS 的中间角反馈丢失。

仓库根目录执行：`PYTHONPATH=robot_strategy/src python3 -m unittest discover -s robot_strategy/tests -v`。

`python3 robot_strategy/scripts/verify_strategy.py` 独立遍历策略的全部可达合法回答路径。模拟 ROS 测试不代表物理到位。
