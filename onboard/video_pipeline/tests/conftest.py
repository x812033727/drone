"""讓 tests 不需安裝套件即可 import stamp(加入上層目錄到 sys.path)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
