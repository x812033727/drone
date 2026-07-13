"""mission-svc 請求/回應模型(pydantic v2)。純資料 + 驗證。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Waypoint(BaseModel):
    """對 interfaces/proto/drone/v1/mission.proto 的 Waypoint。"""

    lat_deg: float
    lon_deg: float
    rel_alt_m: float = 0.0
    hold_s: float = 0.0
    speed_ms: float = 0.0

    @field_validator("lat_deg")
    @classmethod
    def _lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"lat_deg 超界:{v}")
        return v

    @field_validator("lon_deg")
    @classmethod
    def _lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"lon_deg 超界:{v}")
        return v


class RouteCreate(BaseModel):
    """建立航線。org_id 不在此——租戶由呼叫者 JWT claim 決定(不採信 client 傳入)。"""

    name: str
    waypoints: list[Waypoint] = Field(min_length=1)
    rtl_after_last: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name 不可為空")
        return v.strip()


class Route(BaseModel):
    id: UUID
    name: str
    org_id: str  # 租戶邊界(G11):NOT NULL,建立時取自呼叫者 claim
    waypoints: list[Waypoint]
    rtl_after_last: bool
    created_at: datetime


class MissionStatus(str, Enum):
    created = "created"
    dispatched = "dispatched"
    received = "received"
    uploaded = "uploaded"
    in_progress = "in_progress"
    paused = "paused"
    completed = "completed"
    failed = "failed"


class MissionCreate(BaseModel):
    """由 route + 目標機建立任務(凍結 route 當下的航點)。"""

    route_id: UUID
    drone_id: str

    @field_validator("drone_id")
    @classmethod
    def _drone(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("drone_id 不可為空")
        return v.strip()


class Mission(BaseModel):
    id: UUID
    mission_id: str
    route_id: UUID | None = None
    org_id: str  # 租戶邊界(G11):NOT NULL,建立時取自呼叫者 claim
    drone_id: str
    status: MissionStatus
    waypoints: list[Waypoint]
    rtl_after_last: bool
    current_item: int | None = None
    total_items: int | None = None
    dispatched_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class CommandKind(str, Enum):
    pause = "pause"
    resume = "resume"
    abort = "abort"


class MissionCommandRequest(BaseModel):
    command: CommandKind


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
