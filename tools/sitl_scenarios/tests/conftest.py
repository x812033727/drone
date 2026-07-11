"""讓 tests 不需安裝套件即可 import sitl_scenarios(加 tools/ 目錄到 sys.path)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
