#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source /opt/ros/noetic/setup.bash || exit 1
source /home/lemon/robot_ros_application/catkin_ws/devel/setup.bash || exit 1
set -o pipefail
mkdir -p lab_records || exit 1
log=$(mktemp lab_records/session-XXXXXX.log) || exit 1
echo "记录文件 $PWD/$log"
for item in head:center head:nod head:shake game:nod game:shake game:think game:win game:lose; do
    action=${item#*:}
    script=head_action
    if [[ $item == game:* ]]; then script=game_gesture; fi
    echo "下一项 $item。空闲时会进入 ready 姿态；game 会驱动全身，请确认站稳、有人保护、已协调控制权及停止方式。"
    read -r -p "输入 y 执行，s 跳过，其他键结束：" choice || exit 1
    echo "$item $choice" >> "$log"
    [[ $choice == s ]] && continue
    [[ $choice == y ]] || exit 0
    if [[ $item == head:* ]]; then
        prefix=/MediumSize/BodyHub
        owner=$(timeout 5 rosservice call "$prefix/GetMasterID" get) || exit 1
        status=$(timeout 5 rosservice call "$prefix/GetStatus" get) || exit 1
        printf '%s\n' "$owner" "$status" | tee -a "$log"
        if [[ $owner == 'data: 0' && $status == $'data: "preReady"\nposeQueueSize: 0\njointQueueSize: 0' ]]; then
            echo "空闲，申请控制 ID 2 并进入 ready 姿态" | tee -a "$log"
            timeout 5 rosservice call "$prefix/StateJump" 2 setStatus | tee -a "$log" || exit 1
            for attempt in {1..10}; do
                owner=$(timeout 3 rosservice call "$prefix/GetMasterID" get) || exit 1
                status=$(timeout 3 rosservice call "$prefix/GetStatus" get) || exit 1
                [[ $owner == 'data: 2' && $status == $'data: "ready"\nposeQueueSize: 0\njointQueueSize: 0' ]] && break
                sleep 0.2
            done
            printf '%s\n' "$owner" "$status" | tee -a "$log"
        fi
    fi
    timeout --signal=INT --kill-after=5 30 python3 -u "robot_strategy/scripts/$script.py" "$action" --run 2>&1 | tee -a "$log"
    code=$?
    echo "exit_code=$code" >> "$log"
    read -r -p "确认已停稳，记录方向、幅度、结束姿态或异常：" observation || exit 1
    echo "$item 现场观察 $observation" >> "$log"
    if (( code != 0 )); then echo "本轮停止，请保留记录。"; exit "$code"; fi
done
echo "本轮结束。记录文件 $PWD/$log"
