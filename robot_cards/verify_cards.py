import cv2
import json
import os

# 读取统一映射
with open("mapping.json", "r") as f:
    config = json.load(f)

aruco_dict = cv2.aruco.Dictionary_get(
    cv2.aruco.DICT_4X4_50
)
parameters = cv2.aruco.DetectorParameters_create()

success = 0

print("开始检查十张卡牌...")
print("-" * 40)

for marker_id, number in config["id_to_number"].items():

    marker_id = int(marker_id)
    number = int(number)

    filename = "cards/card_%02d.png" % number
    image = cv2.imread(filename)

    if image is None:
        print("文件不存在:", filename)
        continue

    corners, ids, rejected = cv2.aruco.detectMarkers(
        image, aruco_dict, parameters=parameters
    )

    if ids is not None and len(ids) == 1:
        detected_id = int(ids[0][0])

        if detected_id == marker_id:
            print(
                "通过：ID %d -> 数字 %d"
                % (detected_id, number)
            )
            success += 1
        else:
            print("映射错误:", filename)
    else:
        print("识别失败:", filename)

print("-" * 40)
print("检查完成：%d/10 张通过" % success)
