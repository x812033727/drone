"""repo 純函式(PATCH SQL builder)單元測試(不碰 DB)。"""

from uuid import uuid4

from fleet_svc.models import DeviceStatus, DeviceUpdate
from fleet_svc.repo import build_device_patch


def test_patch_empty_update():
    clause, values = build_device_patch(DeviceUpdate())
    assert clause == ""
    assert values == []


def test_patch_single_field():
    clause, values = build_device_patch(DeviceUpdate(name="new-name"))
    assert clause == "name = $1"
    assert values == ["new-name"]


def test_patch_enum_lowered_to_value():
    clause, values = build_device_patch(DeviceUpdate(status=DeviceStatus.active))
    assert clause == "status = $1"
    assert values == ["active"]  # enum → 其字串值


def test_patch_multi_field_indexes_in_whitelist_order():
    fid = uuid4()
    clause, values = build_device_patch(
        DeviceUpdate(model="PA-1", status=DeviceStatus.retired, fleet_id=fid)
    )
    # 白名單順序 name, fleet_id, model, status(name 未給故跳過)
    assert clause == "fleet_id = $1, model = $2, status = $3"
    assert values == [fid, "PA-1", "retired"]


def test_patch_start_index_offset():
    clause, values = build_device_patch(DeviceUpdate(name="x"), start_index=5)
    assert clause == "name = $5"
    assert values == ["x"]
