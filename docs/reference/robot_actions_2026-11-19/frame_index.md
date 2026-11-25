# 静态动作数据索引

自动提取字面量；时间是源码标称值，不是实测时间。“变化关节”只比较关键帧，恒定目标也会被写入。

| 文件与行号 | 数据变量 | 格式 | 写入关节 | 关键帧变化关节 | 源码时间 |
| --- | --- | --- | --- | --- | --- |
| catkin_ws/src/actexecpackage/config/robotDanceDemo_node.py:30 | poseList | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 14,15,16 | 9000 ms |
| catkin_ws/src/leju_lib_pkg/src/lejufunc/bezier.py:125 | act_frames | bezier | 1 | 1 | 1000.0 ms |
| catkin_ws/src/leju_lib_pkg/src/lejufunc/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/leju_lib_pkg/src/motion/example/action_example.py:126 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/1.py:12 | u357u53f71_100S_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22 | 100000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/Say-yeah舞蹈案例.py:12 | dance_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22 | 69710.0 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:3 | squat | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,13,15,16,18,22 | 2000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:8 | squat_to_stand | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,13,15,16,18,22 | 3800 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:14 | shake_head | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,7,20,21,22 | 5000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:20 | head_toward_face | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,9,10,13,16,22 | 4000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:25 | touch_leg | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15,22 | 3500 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:31 | snicker | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,13,14,15,17,21,22 | 5000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:40 | bow | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,9,13,16,22 | 7000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:47 | anthropomorphic_speech | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,7,13,14,15,21,22 | 5000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:55 | hug | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,13,14,15,16,17,18,21,22 | 10000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:65 | bend_over | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,14,17,22 | 3000 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:70 | pick_up_trash | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,13,14,15,19,21,22 | 6300 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:83 | stand_on_one_foot | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,14,15,17,18 | 14000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/action/demo_frame.py:85 | dream_seeker_abbreviated_version | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18,21 | 179400.0 ms |
| catkin_ws/src/ros_actions_node/scripts/action/kickball_frame.py:2 | kick_ball_points_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18 | 4700.0 ms |
| catkin_ws/src/ros_actions_node/scripts/botec/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/botec/open_door.py:50 | press_door_1_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15 | 3000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/botec/pose_board.py:51 | board_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/botec_company/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/botec_company/pose_board_company.py:41 | board_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/check_gait/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/compete/demo_slam.py:270 | frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1000 ms |
| catkin_ws/src/ros_actions_node/scripts/compete/kick_ball.py:26 | code | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 | 6000 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:5 | left_action_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 16,17,18 | 2010.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:7 | right_action_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15 | 2200.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:9 | right_disarm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14 | 1920.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:11 | left_disarm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 16,17,18 | 2010.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:13 | take_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18 | 1480.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/colleges/scripts/frames.py:15 | squat_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1500.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:5 | hang_up_left_arm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:7 | hang_up_right_arm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:9 | left_action_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 16,17,18 | 2010.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:11 | right_action_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15 | 2200.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:13 | right_disarm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14 | 1920.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:15 | left_disarm_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 16,17,18 | 2010.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:17 | take_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18 | 1480.0 ms |
| catkin_ws/src/ros_actions_node/scripts/game/2022/caai_roban_challenge/higher_vocational_schools/scripts/frames.py:19 | squat_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 |  | 1500.0 ms |
| catkin_ws/src/ros_actions_node/scripts/roban_practice_course/scripts/practice_demo/NXIUGAI0429.py:30 | u8e22u743u4feeu6539u54e1_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18 | 5200.0 ms |
| catkin_ws/src/ros_actions_node/scripts/roban_practice_course/scripts/roban_challenge/bodyhub_action.py:145 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/roban_practice_course/scripts/roban_challenge/kick_ball_practice.py:156 | keyframes | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,12 | 5800 ms |
| catkin_ws/src/ros_actions_node/scripts/roban_practice_course/scripts/roban_challenge/kick_ball_practice.py:246 | u8e22u743u4feeu6539u54e1_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18 | 5200.0 ms |
| catkin_ws/src/ros_actions_node/scripts/下蹲.py:11 | squat_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 3,4,5,9,10,11,14,15,17,18 | 3600 ms |
| catkin_ws/src/ros_actions_node/scripts/举手.py:12 | hands_up_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13 | 6900.0 ms |
| catkin_ws/src/ros_actions_node/scripts/伸展手臂.py:12 | u4f38u5c55u624bu81c2_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,14,15,17,18 | 3000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/我的点头_列表形式.py:15 | nod_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 22 | 3700 ms |
| catkin_ws/src/ros_actions_node/scripts/摇头.py:12 | shake_head_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15,16,17,18,21 | 3900 ms |
| catkin_ws/src/ros_actions_node/scripts/摇头_修改幅度.py:12 | shake_head_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15,16,17,18,21 | 3900 ms |
| catkin_ws/src/ros_actions_node/scripts/摇头改幅度_liujie.py:12 | shake_head_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15,16,17,18,21 | 3900 ms |
| catkin_ws/src/ros_actions_node/scripts/武当太极.py:11 | tai_chi_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22 | 143200.0 ms |
| catkin_ws/src/ros_actions_node/scripts/点头.py:12 | u70b9u5934_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 22 | 2000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/点头_贝塞尔100.py:12 | u70b9u5934_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 22 | 2000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/点头_贝塞尔500.py:12 | u70b9u5934_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 22 | 2000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/鞠躬.py:12 | u97a0u8eac_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,16,17,18,20 | 4800.0 ms |
| catkin_ws/src/ros_actions_node/scripts/高职招生宣讲.py:12 | bow_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,13,16,18 | 3000.0 ms |
| catkin_ws/src/ros_actions_node/scripts/高职招生宣讲.py:16 | speech_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 48400.0 ms |
| catkin_ws/src/ros_dance_node/scripts/dance_node.py:10 | act_frames | frame_list | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,14,15,16,17,18,22 | 18200 ms |
| catkin_ws/src/ros_gesture_node/RPS_game/actions/paper.py:12 | paper_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,19 | 2000.0 ms |
| catkin_ws/src/ros_gesture_node/RPS_game/actions/rock.py:12 | rock_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13 | 2000.0 ms |
| catkin_ws/src/ros_gesture_node/RPS_game/actions/scissors.py:12 | scissors_frames | bezier | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 | 13,19 | 2000.0 ms |
