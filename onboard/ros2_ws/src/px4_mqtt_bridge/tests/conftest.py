"""讓 tests 不需安裝 ROS 2 套件即可 import px4_mqtt_bridge.codec
(加 px4_mqtt_bridge/ 套件上層目錄到 sys.path)。
只測 codec 純函式,不觸及 bridge.py(其頂層 import rclpy / px4_msgs)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
