"""讓 tests 不需 colcon/ROS 環境即可 import obstacle_guard(加入套件上層到 sys.path)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
