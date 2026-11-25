cmake_minimum_required(VERSION 3.0.2)
project(robot_strategy)
find_package(catkin REQUIRED)
catkin_python_setup()
catkin_package()
catkin_install_python(PROGRAMS
  scripts/head_action.py
  scripts/game_gesture.py
  scripts/strategy_demo.py
  scripts/verify_strategy.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
