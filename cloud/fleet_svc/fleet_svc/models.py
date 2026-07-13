"""fleet-svc 的請求/回應模型(pydantic v2)。純資料 + 驗證,不碰 DB。"""

from __future__ import annotations

from datetime import date, datetime
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


class OrgPlan(str, Enum):
    """租戶方案:決定「未覆寫」時的預設配額(對應值在 limits.PLAN_QUOTAS)。"""

    free = "free"
    pro = "pro"
    enterprise = "enterprise"


class OrgStatus(str, Enum):
    """租戶狀態:suspended 的寫入被服務層擋下(admin 平台管理者豁免)。"""

    active = "active"
    suspended = "suspended"


def _non_blank(v: str, field: str) -> str:
    if not v or not v.strip():
        raise ValueError(f"{field} 不可為空")
    return v.strip()


# ---- fleet ----
class FleetCreate(BaseModel):
    """建立機隊。org_id 不在此——租戶由呼叫者 JWT claim 決定(不採信 client 傳入)。"""

    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank(v, "name")


class Fleet(BaseModel):
    id: UUID
    name: str
    org_id: str  # 租戶邊界(G11):NOT NULL,建立時取自呼叫者 claim
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
    org_id: str  # 租戶邊界(G11):NOT NULL,建立時取自呼叫者 claim
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


class DeviceStatusView(BaseModel):
    """裝置 + 最新即時狀態(機隊儀表板/地圖用)。online 於查詢時依 last_seen 新鮮度計算。"""

    device_id: UUID
    serial: str
    name: str | None = None
    fleet_id: UUID | None = None
    status: DeviceStatus
    online: bool
    last_seen: datetime | None = None
    lat_deg: float | None = None
    lon_deg: float | None = None
    rel_alt_m: float | None = None
    battery_pct: float | None = None
    flight_mode: str | None = None
    armed: bool | None = None


# ---- 租戶註冊表 / 每租戶配額(計費控制面,admin only) ----
class OrgCreate(BaseModel):
    """建立租戶。org_id 為租戶主鍵(對應 JWT `org` claim);plan 決定預設配額。

    max_devices / max_fleets 為配額「覆寫」——省略/None 表示用 plan 預設。
    """

    org_id: str
    name: str
    plan: OrgPlan = OrgPlan.free
    status: OrgStatus = OrgStatus.active
    max_devices: int | None = Field(default=None, ge=0)
    max_fleets: int | None = Field(default=None, ge=0)

    @field_validator("org_id")
    @classmethod
    def _org_id(cls, v: str) -> str:
        return _non_blank(v, "org_id")

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank(v, "name")


class OrgUpdate(BaseModel):
    """PATCH 租戶:所有欄位可選,只更新有給的(max_* 顯式給 null 可清除覆寫)。"""

    name: str | None = None
    plan: OrgPlan | None = None
    status: OrgStatus | None = None
    max_devices: int | None = Field(default=None, ge=0)
    max_fleets: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _non_blank(v, "name") if v is not None else v


class Org(BaseModel):
    """租戶註冊列。max_devices/max_fleets 為配額覆寫(None = 用 plan 預設)。"""

    org_id: str
    name: str
    plan: OrgPlan
    status: OrgStatus
    max_devices: int | None = None
    max_fleets: int | None = None
    created_at: datetime
    updated_at: datetime


# ---- 用量 / 配額(G30) ----
class UsageReport(BaseModel):
    """某租戶用量報表(GET /api/v1/usage)。

    - counters:當日(UTC)各計費指標計數(如 device_created / fleet_created)。
    - totals:歷來累計(跨所有日期)。
    - resources:當前現存資源數量(配額以此判定)。
    - limits:設定的配額上限(供前端顯示剩餘額度)。
    """

    org_id: str
    period: date
    counters: dict[str, int] = Field(default_factory=dict)
    totals: dict[str, int] = Field(default_factory=dict)
    resources: dict[str, int] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)


# ---- audit(G14) ----
class AuditEntry(BaseModel):
    """審計軌跡一筆(供 GET /api/v1/audit,admin 稽核檢視)。"""

    id: int
    at: datetime
    actor: str
    role: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: dict = Field(default_factory=dict)
    source_ip: str | None = None
