# 机器人部署

仓库：~/team_project_ws/src/Robot_checkout。厂商工程：~/robot_ros_application。

已读取 shell 配置中的 ROS Noetic 路径；实际 Python、OpenCV/ArUco、音频与动作接口版本仍待机器人终端确认。

以下在机器人 Linux 终端执行，本轮尚未执行：

```bash
source /opt/ros/noetic/setup.bash
source ~/robot_ros_application/catkin_ws/devel/setup.bash
cd ~/team_project_ws
catkin_make
source devel/setup.bash
rospack find robot_referee
```

若厂商 setup.bash 不存在，先核对实际路径。当前没有可运行节点和整机 launch，骨架编译通过不代表游戏可运行。

更新前在仓库执行 git status，保存修改后再 git pull --ff-only。实测记录 git rev-parse HEAD 的版本。机器人向 GitHub 推送的认证尚未验证。

不要未经协调升级共用机器人的 Python、ROS 或 OpenCV；新增依赖记录版本及安装范围。
