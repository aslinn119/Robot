import cv2
import json
import os

# 读取统一映射配置
with open("mapping.json", "r") as f:
    config = json.load(f)

# 获取 ArUco 字典
aruco_dict = cv2.aruco.Dictionary_get(
    cv2.aruco.DICT_4X4_50
)

# 创建输出文件夹
os.makedirs("cards", exist_ok=True)

# 根据映射关系生成十张卡牌
for marker_id, number in config["id_to_number"].items():

    marker_id = int(marker_id)

    # 生成 ArUco 标记
    marker = cv2.aruco.drawMarker(
        aruco_dict, marker_id, 500
    )

    # 添加白色留边
    marker = cv2.copyMakeBorder(
        marker,
        80, 80, 80, 80,
        cv2.BORDER_CONSTANT,
        value=255
    )

    # 创建白色卡牌画布
    card = 255 * __import__("numpy").ones(
        (850, 820), dtype="uint8"
    )

    # 将标记放在卡牌上方
    card[30:690, 80:740] = marker

    # 添加数字标签
    cv2.putText(
        card,
        "Number: " + str(number),
        (220, 790),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        0,
        3
    )

    # 保存图片
    filename = "cards/card_%02d.png" % number
    cv2.imwrite(filename, card)

    print(
        "生成成功：ID %d -> 数字 %d"
        % (marker_id, number)
    )

print("\n十张卡牌全部生成完成！")
