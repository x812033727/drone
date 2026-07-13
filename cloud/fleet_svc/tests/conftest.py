"""讓 tests 不需安裝 fleet_svc 套件即可 import(加入上層目錄到 sys.path)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
