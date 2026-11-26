import rospy
import cv2
import json
import os

from sensor_msgs.msg import Image
from cv_bridge import CvBridge

# 读取统一映射配置
base_dir = os.path.dirname(os.path.abspath(__file__))
mapping_path = os.path.join(base_dir, "mapping.json")

with open(mapping_path, "r") as f:
    config = json.load(f)

# 将 JSON 中的 ID 转换为整数，方便查询
id_to_number = {
    int(k): int(v)
    for k, v in config["id_to_number"].items()
}

# 初始化图像转换工具
bridge = CvBridge()

# 使用统一的 ArUco 字典
aruco_dict = cv2.aruco.Dictionary_get(
    cv2.aruco.DICT_4X4_50
)
parameters = cv2.aruco.DetectorParameters_create()

last_ids = None


def image_callback(msg):
    global last_ids

    try:
        # ROS 图像转为 OpenCV 图像
        frame = bridge.imgmsg_to_cv2(
            msg, desired_encoding="bgr8"
        )

        # 检测 ArUco
        corners, ids, rejected = cv2.aruco.detectMarkers(
            frame,
            aruco_dict,
            parameters=parameters
        )

        if ids is None:
            last_ids = None
            return

        detected_ids = sorted(set(int(x) for x in ids.flatten()))

        # 只在检测结果发生变化时输出
        if detected_ids != last_ids:
            print("\n========== 视觉识别结果 ==========")

            for marker_id in detected_ids:
                if marker_id in id_to_number:
                    number = id_to_number[marker_id]

                    print("ArUco ID:", marker_id)
                    print("对应卡牌数字:", number)
                    print("识别成功！")

            print("==================================")
            last_ids = detected_ids

    except Exception as e:
        rospy.logerr("图像处理异常: %s", str(e))


def main():
    rospy.init_node("roban_aruco_detector")

    rospy.Subscriber(
        "/camera/color/image_raw",
        Image,
        image_callback,
        queue_size=1,
        buff_size=2**24
    )

    print("Roban 视觉识别节点已启动")
    print("统一映射配置加载成功")
    print("映射数量:", len(id_to_number))
    print("等待卡牌展示...")

    rospy.spin()


if __name__ == "__main__":
    main()
