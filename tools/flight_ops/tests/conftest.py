"""讓 tests 不需安裝套件即可 import flight_ops(加 tools/ 目錄到 sys.path)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
