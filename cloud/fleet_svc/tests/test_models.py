"""模型驗證的純單元測試(不碰 DB)。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fleet_svc.models import (
    Component,
    Device,
    DeviceCreate,
    DeviceStatus,
    FirmwareCreate,
    FleetCreate,
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
