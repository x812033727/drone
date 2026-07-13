import { AuthError, getToken } from "./auth";
import { config } from "./config";
import type {
  Alert,
  Device,
  DeviceCreate,
  DeviceStatusView,
  DeviceUpdate,
  DeviceFirmware,
  DeviceFirmwareSet,
  DeviceOtaRequest,
  DeviceOtaResult,
  Firmware,
  FirmwareCreate,
  Fleet,
  FleetCreate,
  Mission,
  MissionCreate,
  CommandKind,
  Org,
  OrgCreate,
  OrgUpdate,
  OrgPlan,
  Page,
  Route,
  RouteCreate,
  Subscription,
  CheckoutForm,
  TelemetryEvent,
  UsageReport,
} from "./types";

// 正式部署由 nginx 代理 /api → fleetsvc(routes/missions 前綴 → missionsvc);
// 開發由 vite proxy。base 走執行期設定(runtime config.js → VITE_API_BASE → 預設 /api/v1)。
// fleet-svc 與 mission-svc 的路徑前綴(status/devices/fleets/firmware vs routes/missions)
// 不衝突,故共用同一 base。
const API_BASE = config.apiBase;

// 統一請求輔助:附帶 Bearer、把 401/403 轉 AuthError、非 2xx 盡量帶後端錯誤訊息。
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body != null) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 || res.status === 403) throw new AuthError(String(res.status));
  if (!res.ok) throw new Error(await errorDetail(res, `${init?.method ?? "GET"} ${path}`));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// 分頁列表:回應本體是陣列,total 走 X-Total-Count 標頭(fleet-svc G12,同源反代可讀)。
// 標頭缺失(理論上不會)則以本頁筆數回退,避免 NaN。
async function requestPage<T>(path: string, init?: RequestInit): Promise<Page<T>> {
  const token = getToken();
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 || res.status === 403) throw new AuthError(String(res.status));
  if (!res.ok) throw new Error(await errorDetail(res, `${init?.method ?? "GET"} ${path}`));
  const items = (await res.json()) as T[];
  const totalHeader = res.headers.get("X-Total-Count");
  const total = totalHeader != null ? Number(totalHeader) : items.length;
  return { items, total: Number.isFinite(total) ? total : items.length };
}

// 盡量抽出 FastAPI 的 {detail: ...};失敗則回退狀態碼。
async function errorDetail(res: Response, ctx: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const d = body.detail;
    if (typeof d === "string") return d;
    if (d != null) return JSON.stringify(d);
  } catch {
    /* 非 JSON body,略過 */
  }
  return `${ctx} ${res.status}`;
}

export async function fetchStatus(): Promise<DeviceStatusView[]> {
  return request<DeviceStatusView[]>("/status");
}

// ---- fleet-svc:fleets / devices CRUD ----
export const listFleets = () => request<Fleet[]>("/fleets");
export const createFleet = (body: FleetCreate) =>
  request<Fleet>("/fleets", { method: "POST", body: JSON.stringify(body) });

export const listDevices = () => request<Device[]>("/devices");
export const createDevice = (body: DeviceCreate) =>
  request<Device>("/devices", { method: "POST", body: JSON.stringify(body) });
export const updateDevice = (id: string, body: DeviceUpdate) =>
  request<Device>(`/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteDevice = (id: string) =>
  request<void>(`/devices/${id}`, { method: "DELETE" });

// ---- fleet-svc:韌體型錄 + 裝置韌體指派 + OTA 觸發 ----
// 型錄 CRUD(operator+ 建立;所有登入者可列),裝置韌體以 PUT 覆寫記錄,OTA 以 POST 發起。
export const listFirmware = () => request<Firmware[]>("/firmware");
export const createFirmware = (body: FirmwareCreate) =>
  request<Firmware>("/firmware", { method: "POST", body: JSON.stringify(body) });
export const listDeviceFirmware = (id: string) =>
  request<DeviceFirmware[]>(`/devices/${id}/firmware`);
export const setDeviceFirmware = (id: string, body: DeviceFirmwareSet) =>
  request<DeviceFirmware>(`/devices/${id}/firmware`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
// 觸發 OTA:發布 cmd/ota 到目標機;回應確認主題(進度看 /alerts kind=ota)。
export const triggerOta = (id: string, body: DeviceOtaRequest) =>
  request<DeviceOtaResult>(`/devices/${id}/ota`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---- mission-svc:routes / missions CRUD + 派遣 + 控制 ----
export const listRoutes = () => request<Route[]>("/routes");
export const createRoute = (body: RouteCreate) =>
  request<Route>("/routes", { method: "POST", body: JSON.stringify(body) });

export const listMissions = () => request<Mission[]>("/missions");
export const createMission = (body: MissionCreate) =>
  request<Mission>("/missions", { method: "POST", body: JSON.stringify(body) });
export const dispatchMission = (pk: string) =>
  request<Mission>(`/missions/${pk}/dispatch`, { method: "POST" });
export const commandMission = (pk: string, command: CommandKind) =>
  request<Mission>(`/missions/${pk}/command`, {
    method: "POST",
    body: JSON.stringify({ command }),
  });

// ---- fleet-svc:orgs(租戶控制面,admin only)+ usage ----
export const listOrgs = (opts: { status?: string; limit?: number; offset?: number } = {}) => {
  const q = new URLSearchParams();
  if (opts.status) q.set("status", opts.status);
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.offset != null) q.set("offset", String(opts.offset));
  const qs = q.toString();
  return requestPage<Org>(`/orgs${qs ? `?${qs}` : ""}`);
};
export const getOrg = (orgId: string) => request<Org>(`/orgs/${encodeURIComponent(orgId)}`);
export const createOrg = (body: OrgCreate) =>
  request<Org>("/orgs", { method: "POST", body: JSON.stringify(body) });
export const updateOrg = (orgId: string, body: OrgUpdate) =>
  request<Org>(`/orgs/${encodeURIComponent(orgId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
export const getOrgUsage = (orgId: string) =>
  request<UsageReport>(`/orgs/${encodeURIComponent(orgId)}/usage`);

// 本 org 用量(所有登入者);admin 可加 ?org= 查他 org(此處不用,admin 走 /orgs/{id}/usage)。
export const getUsage = () => request<UsageReport>("/usage");

// ---- fleet-svc:裝置告警(device_alerts;所有登入者看本 org,後端已 org 隔離)----
// 分頁走 X-Total-Count(同 orgs);kind 過濾 cert(憑證到期)/ ota(OTA 進度)。
export const listAlerts = (
  opts: { kind?: string; limit?: number; offset?: number } = {},
) => {
  const q = new URLSearchParams();
  if (opts.kind) q.set("kind", opts.kind);
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.offset != null) q.set("offset", String(opts.offset));
  const qs = q.toString();
  return requestPage<Alert>(`/alerts${qs ? `?${qs}` : ""}`);
};

// ---- fleet-svc:訂閱金流(綠界 ECPay)----
// 本 org 目前訂閱狀態/最近交易(所有登入者可讀,對齊後端 VIEWER)。
export const getSubscription = () => request<Subscription>("/billing/subscription");
// 為本 org 發起指定方案的結帳(operator/admin,對齊後端 OPERATOR)→ 回綠界表單參數。
export const checkout = (plan: OrgPlan) =>
  request<CheckoutForm>("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });

// 訂閱 SSE 即時遙測;EventSource 無法帶 header,故 token 走查詢參數。
// 回傳取消函式。斷線由 EventSource 自動重連。
export function subscribeStream(
  onEvent: (e: TelemetryEvent) => void,
  onError?: () => void,
): () => void {
  const token = getToken();
  const url = token
    ? `${API_BASE}/stream?token=${encodeURIComponent(token)}`
    : `${API_BASE}/stream`;
  const es = new EventSource(url);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as TelemetryEvent);
    } catch {
      /* keepalive 註解行或壞資料,略過 */
    }
  };
  es.onerror = () => onError?.();
  return () => es.close();
}
