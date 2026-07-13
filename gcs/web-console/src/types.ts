// fleet-svc /api/v1/status 與 /stream 的資料型別(對 cloud/fleet_svc/fleet_svc/models.py)。

export type DeviceStatusView = {
  device_id: string;
  serial: string;
  name: string | null;
  fleet_id: string | null;
  status: "provisioned" | "active" | "retired" | "revoked";
  online: boolean;
  last_seen: string | null;
  lat_deg: number | null;
  lon_deg: number | null;
  rel_alt_m: number | null;
  battery_pct: number | null;
  flight_mode: string | null;
  armed: boolean | null;
};

// SSE /stream 推送的遙測(對 fleet_svc/telemetry.py parse_telemetry)。
export type TelemetryEvent = {
  drone_id: string;
  unix_time_ms: number;
  lat_deg: number;
  lon_deg: number;
  rel_alt_m: number;
  heading_deg: number;
  ground_speed_ms: number;
  flight_mode: string;
  armed: boolean;
  battery_v: number;
  battery_pct: number;
  health_all_ok: boolean;
};

// ---- fleet-svc CRUD 契約(對 cloud/fleet_svc/fleet_svc/models.py)----

export type DeviceStatus = "provisioned" | "active" | "retired" | "revoked";

export type Fleet = {
  id: string;
  name: string;
  org_id: string | null;
  created_at: string;
};

export type FleetCreate = {
  name: string;
  org_id?: string | null;
};

export type Device = {
  id: string;
  serial: string;
  name: string | null;
  fleet_id: string | null;
  model: string | null;
  status: DeviceStatus;
  cert_fingerprint: string | null;
  cert_not_after: string | null;
  created_at: string;
};

export type DeviceCreate = {
  serial: string;
  name?: string | null;
  fleet_id?: string | null;
  model?: string | null;
};

// PATCH:僅送有給的欄位。
export type DeviceUpdate = {
  name?: string | null;
  fleet_id?: string | null;
  model?: string | null;
  status?: DeviceStatus;
};

// ---- mission-svc 契約(對 cloud/mission_svc/mission_svc/models.py)----

export type Waypoint = {
  lat_deg: number;
  lon_deg: number;
  rel_alt_m: number;
  hold_s: number;
  speed_ms: number;
};

export type Route = {
  id: string;
  name: string;
  org_id: string | null;
  waypoints: Waypoint[];
  rtl_after_last: boolean;
  created_at: string;
};

export type RouteCreate = {
  name: string;
  org_id?: string | null;
  waypoints: Waypoint[];
  rtl_after_last: boolean;
};

export type MissionStatus =
  | "created"
  | "dispatched"
  | "received"
  | "uploaded"
  | "in_progress"
  | "paused"
  | "completed"
  | "failed";

export type Mission = {
  id: string;
  mission_id: string;
  route_id: string | null;
  drone_id: string;
  status: MissionStatus;
  waypoints: Waypoint[];
  rtl_after_last: boolean;
  current_item: number | null;
  total_items: number | null;
  dispatched_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type MissionCreate = {
  route_id: string;
  drone_id: string;
};

export type CommandKind = "pause" | "resume" | "abort";
