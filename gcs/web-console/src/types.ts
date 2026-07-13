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
