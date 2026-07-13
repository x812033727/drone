import { AuthError, getToken } from "./auth";
import type {
  Device,
  DeviceCreate,
  DeviceStatusView,
  DeviceUpdate,
  Fleet,
  FleetCreate,
  Mission,
  MissionCreate,
  CommandKind,
  Route,
  RouteCreate,
  TelemetryEvent,
} from "./types";

// 正式部署由 nginx 代理 /api → fleetsvc(routes/missions 前綴 → missionsvc);
// 開發由 vite proxy。可用 VITE_API_BASE 覆寫。fleet-svc 與 mission-svc 的路徑前綴
// (status/devices/fleets/firmware vs routes/missions)不衝突,故共用同一 base。
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

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
