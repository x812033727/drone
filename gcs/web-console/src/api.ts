import { AuthError, getToken } from "./auth";
import type { DeviceStatusView, TelemetryEvent } from "./types";

// 正式部署由 nginx 代理 /api → fleetsvc;開發由 vite proxy。可用 VITE_API_BASE 覆寫。
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export async function fetchStatus(): Promise<DeviceStatusView[]> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}/status`, { headers });
  if (res.status === 401 || res.status === 403) throw new AuthError(String(res.status));
  if (!res.ok) throw new Error(`GET /status ${res.status}`);
  return res.json();
}

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
