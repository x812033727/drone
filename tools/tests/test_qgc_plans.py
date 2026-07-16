"""gcs/qgc-profiles/plans/ 任務範本結構驗證(QGC .plan JSON)。

守的是「操作人載入不炸 + 基本安全口徑」:PX4 韌體型別、多旋翼、起飛→…→RTL
收尾、座標在台灣範圍、高度在 GF_MAX_VER_DIST(100 m,dev-machine-v1.params)內。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PLANS_DIR = Path(__file__).resolve().parents[2] / "gcs" / "qgc-profiles" / "plans"
PLAN_FILES = sorted(PLANS_DIR.glob("*.plan"))

MAV_CMD_TAKEOFF = 22
MAV_CMD_RTL = 20
FIRMWARE_PX4 = 12
VEHICLE_MULTIROTOR = 2
GF_MAX_VER_DIST = 100.0  # 與 dev-machine-v1.params GF_MAX_VER_DIST 對齊


def test_templates_exist():
    assert PLAN_FILES, f"{PLANS_DIR} 下無 .plan 範本"


@pytest.mark.parametrize("plan_file", PLAN_FILES, ids=lambda p: p.name)
def test_plan_structure(plan_file: Path):
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    assert plan["fileType"] == "Plan"
    mission = plan["mission"]
    assert mission["firmwareType"] == FIRMWARE_PX4
    assert mission["vehicleType"] == VEHICLE_MULTIROTOR

    items = mission["items"]
    assert items, "mission.items 不可為空"
    assert items[0]["command"] == MAV_CMD_TAKEOFF, "首項應為起飛"
    assert items[-1]["command"] == MAV_CMD_RTL, "末項應為 RTL(安全收尾)"

    home = mission["plannedHomePosition"]
    assert 21.5 <= home[0] <= 25.5 and 119.5 <= home[1] <= 122.5, "home 應在台灣範圍"

    for item in items:
        assert item["type"] == "SimpleItem"
        lat, lon, alt = item["params"][4], item["params"][5], item["params"][6]
        if item["command"] == MAV_CMD_RTL:
            continue
        assert 21.5 <= lat <= 25.5 and 119.5 <= lon <= 122.5, f"航點超出台灣範圍:{item}"
        assert 0 < alt <= GF_MAX_VER_DIST, f"高度超出圍欄口徑:{item}"


@pytest.mark.parametrize("plan_file", PLAN_FILES, ids=lambda p: p.name)
def test_dojump_ids_sequential(plan_file: Path):
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    ids = [item["doJumpId"] for item in plan["mission"]["items"]]
    assert ids == list(range(1, len(ids) + 1)), "doJumpId 應為 1..N 連號"
