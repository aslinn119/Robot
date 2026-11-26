import cv2

# 使用 4x4 ArUco 字典
aruco_dict = cv2.aruco.Dictionary_get(
    cv2.aruco.DICT_4X4_50
)

# 生成 ID 为 0 的标记
marker = cv2.aruco.drawMarker(
    aruco_dict, 0, 500
)

# 四周增加 100 像素白色边框
marker = cv2.copyMakeBorder(
    marker,
    100, 100, 100, 100,
    cv2.BORDER_CONSTANT,
    value=255
)

# 保存新图片
cv2.imwrite("marker_0_white.png", marker)

print("新卡牌生成成功！")
print("文件：marker_0_white.png")
print("ArUco ID：0")
print("对应数字：1")
