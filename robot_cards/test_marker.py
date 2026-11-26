import cv2

# 读取生成的卡牌图片
image = cv2.imread("marker_0.png")

# 设置 ArUco 字典
aruco_dict = cv2.aruco.Dictionary_get(
    cv2.aruco.DICT_4X4_50
)

# 增加白色留边，方便识别
image = cv2.copyMakeBorder(
    image, 40, 40, 40, 40,
    cv2.BORDER_CONSTANT,
    value=(255, 255, 255)
)

# 设置识别参数
parameters = cv2.aruco.DetectorParameters_create()

# 识别 ArUco 标记
corners, ids, rejected = cv2.aruco.detectMarkers(
    image, aruco_dict, parameters=parameters
)

if ids is not None:
    for marker_id in ids.flatten():
        number = int(marker_id) + 1
        print("识别成功！")
        print("ArUco ID:", marker_id)
        print("对应卡牌数字:", number)
else:
    print("未检测到 ArUco 标记")
