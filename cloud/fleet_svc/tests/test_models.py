"""模型驗證的純單元測試(不碰 DB)。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fleet_svc.models import (
    INT4_MAX,
    Component,
    Device,
    DeviceCreate,
    DeviceStatus,
    FirmwareCreate,
    FleetCreate,
    OrgCreate,
    OrgUpdate,
)
from pydantic import ValidationError


def test_device_create_valid():
    d = DeviceCreate(serial="  SN-001  ", name="dev-1")
    assert d.serial == "SN-001"  # 去頭尾空白


def test_device_create_blank_serial_rejected():
    with pytest.raises(ValidationError):
        DeviceCreate(serial="   ")


def test_fleet_create_blank_name_rejected():
    with pytest.raises(ValidationError):
        FleetCreate(name="")


def test_firmware_component_enum():
    fw = FirmwareCreate(component="px4", version="1.15.4")
    assert fw.component is Component.px4


def test_firmware_bad_component_rejected():
    with pytest.raises(ValidationError):
        FirmwareCreate(component="bogus", version="1.0")


def test_firmware_blank_version_rejected():
    with pytest.raises(ValidationError):
        FirmwareCreate(component="px4", version="  ")


def test_device_row_mapping_from_dict():
    """模擬 asyncpg.Record(dict)→ Device 映射(欄位名與 DB 對齊)。"""
    row = {
        "id": uuid4(),
        "serial": "SN-9",
        "name": None,
        "fleet_id": None,
        "org_id": "acme",
        "model": "PA-1",
        "status": "active",
        "cert_fingerprint": None,
        "cert_not_after": None,
        "created_at": datetime.now(timezone.utc),
    }
    d = Device.model_validate(row)
    assert d.status is DeviceStatus.active
    assert d.model == "PA-1"
    assert d.org_id == "acme"


# ---- api-fuzz 500 findings 迴歸(surrogate 文字 / int4 溢位配額)----
# 這批輸入原本 pydantic 收得下,一路傳到 asyncpg 綁定 text/integer 欄位才炸
# (UnicodeEncodeError / OverflowError → DataError → 500)。改在驗證層擋成 422。

_SURROGATE = "A\ud800B"  # lone surrogate:合法 Python str 但不可 UTF-8 編碼


def test_device_create_rejects_surrogate_serial():
    with pytest.raises(ValidationError):
        DeviceCreate(serial=_SURROGATE)


def test_device_create_rejects_surrogate_optional_field():
    # 選填字串欄位也要擋(_WriteModel 的 model_validator 掃全部字串欄位)
    with pytest.raises(ValidationError):
        DeviceCreate(serial="SN-ok", name=_SURROGATE)


def test_org_create_rejects_surrogate_text():
    for field in ("org_id", "name"):
        payload = {"org_id": "o", "name": "n", field: _SURROGATE}
        with pytest.raises(ValidationError):
            OrgCreate(**payload)


def test_device_create_accepts_valid_unicode():
    d = DeviceCreate(serial="SN-1", name="你好-å-🚁")
    assert d.name == "你好-å-🚁"


def test_org_create_quota_int4_upper_bound():
    for field in ("max_devices", "max_fleets"):
        with pytest.raises(ValidationError):
            OrgCreate(**{"org_id": "o", "name": "n", field: INT4_MAX + 1})
        # 邊界值(int4 max)恰好可接受
        ok = OrgCreate(**{"org_id": "o", "name": "n", field: INT4_MAX})
        assert getattr(ok, field) == INT4_MAX


def test_org_update_quota_int4_upper_bound():
    with pytest.raises(ValidationError):
        OrgUpdate(max_devices=INT4_MAX + 1)
    assert OrgUpdate(max_fleets=INT4_MAX).max_fleets == INT4_MAX
