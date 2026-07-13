"""fleet-svc 的請求/回應模型(pydantic v2)。純資料 + 驗證,不碰 DB。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DeviceStatus(str, Enum):
    provisioned = "provisioned"
    active = "active"
    retired = "retired"
    revoked = "revoked"


class Component(str, Enum):
    px4 = "px4"
    onboard = "onboard"
    gcs = "gcs"
    payload = "payload"


def _non_blank(v: str, field: str) -> str:
    if not v or not v.strip():
        raise ValueError(f"{field} 不可為空")
    return v.strip()


# ---- fleet ----
class FleetCreate(BaseModel):
    name: str
    org_id: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank(v, "name")


class Fleet(BaseModel):
    id: UUID
    name: str
    org_id: str | None = None
    created_at: datetime


# ---- device ----
class DeviceCreate(BaseModel):
    serial: str
    name: str | None = None
    fleet_id: UUID | None = None
    model: str | None = None

    @field_validator("serial")
    @classmethod
    def _serial(cls, v: str) -> str:
        return _non_blank(v, "serial")


class DeviceUpdate(BaseModel):
    """PATCH:所有欄位可選,只更新有給的。"""

    name: str | None = None
    fleet_id: UUID | None = None
    model: str | None = None
    status: DeviceStatus | None = None


class Device(BaseModel):
    id: UUID
    serial: str
    name: str | None = None
    fleet_id: UUID | None = None
    model: str | None = None
    status: DeviceStatus
    cert_fingerprint: str | None = None
    cert_not_after: datetime | None = None
    created_at: datetime


# ---- firmware ----
class FirmwareCreate(BaseModel):
    component: Component
    version: str
    released_at: datetime | None = None
    sbom_ref: str | None = None

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        return _non_blank(v, "version")


class Firmware(BaseModel):
    id: UUID
    component: Component
    version: str
    released_at: datetime | None = None
    sbom_ref: str | None = None
    created_at: datetime


class DeviceFirmwareSet(BaseModel):
    """記錄裝置某元件目前安裝的韌體版本。"""

    component: Component
    version: str = Field(min_length=1)


class DeviceFirmware(BaseModel):
    device_id: UUID
    component: Component
    version: str
    installed_at: datetime
