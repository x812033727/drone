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

// ---- fleet-svc 租戶 / 用量契約(對 cloud/fleet_svc/fleet_svc/models.py,openapi Org/UsageReport)----

export type OrgPlan = "free" | "pro" | "enterprise";
export type OrgStatus = "active" | "suspended";

// GET /api/v1/orgs、/orgs/{id}(admin only)。max_*=None 表示用 plan 預設配額。
export type Org = {
  org_id: string;
  name: string;
  plan: OrgPlan;
  status: OrgStatus;
  max_devices: number | null;
  max_fleets: number | null;
  created_at: string;
  updated_at: string;
};

// POST /api/v1/orgs。plan/status 省略時後端預設 free/active。
export type OrgCreate = {
  org_id: string;
  name: string;
  plan?: OrgPlan;
  status?: OrgStatus;
  max_devices?: number | null;
  max_fleets?: number | null;
};

// PATCH /api/v1/orgs/{id}:僅送有給的欄位;max_* 顯式給 null 可清除覆寫。
export type OrgUpdate = {
  name?: string | null;
  plan?: OrgPlan;
  status?: OrgStatus;
  max_devices?: number | null;
  max_fleets?: number | null;
};

// GET /api/v1/usage(本 org)、/orgs/{id}/usage(admin)。
// counters=當日各計費指標;totals=歷來累計;resources=現存資源數;limits=配額上限。
export type UsageReport = {
  org_id: string;
  period: string;
  counters: Record<string, number>;
  totals: Record<string, number>;
  resources: Record<string, number>;
  limits: Record<string, number>;
};

// ---- fleet-svc 訂閱金流契約(綠界 ECPay,對 openapi 的 billing schema)----

// POST /api/v1/billing/checkout 的請求本體(為本 org 指定欲付費啟用的方案;free 不可結帳)。
export type BillingCheckoutRequest = {
  plan: OrgPlan;
};

// 一筆結帳/付款交易(GET /billing/subscription 的最近交易)。
export type BillingTransaction = {
  id: number;
  org_id: string;
  plan: OrgPlan;
  amount: number;
  trade_no: string;
  status: string; // pending / paid / failed
  at: string;
};

// GET /api/v1/billing/subscription:本 org 目前方案/狀態/月費 + 最近交易。
export type Subscription = {
  org_id: string;
  plan: OrgPlan;
  status: OrgStatus;
  price: number; // 目前方案月費(TWD)
  sandbox: boolean; // 金流是否為沙箱模式(未設正式憑證)
  recent_transactions: BillingTransaction[];
};

// POST /api/v1/billing/checkout 的回應:前端據此組表單 auto-submit 導向綠界結帳頁。
// - action_url:綠界 AioCheckOut 端點(沙箱走測試環境)。
// - params:表單欄位(含 CheckMacValue),原樣 POST 給綠界。
// - sandbox:true 表示未設正式憑證,用綠界公開測試參數(不會真實扣款)。
export type CheckoutForm = {
  action_url: string;
  params: Record<string, string>;
  sandbox: boolean;
};

// 分頁列表回應:本體是陣列,total 走 X-Total-Count 標頭。
export type Page<T> = {
  items: T[];
  total: number;
};
