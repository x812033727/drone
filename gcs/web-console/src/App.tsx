import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchStatus, subscribeStream } from "./api";
import {
  AuthError,
  clearToken,
  currentRoleLabel,
  getToken,
  hasRole,
  setToken,
} from "./auth";
import { DeviceManager } from "./components/DeviceManager";
import { FleetList } from "./components/FleetList";
import { FleetMap } from "./components/FleetMap";
import { Login } from "./components/Login";
import { MissionManager } from "./components/MissionManager";
import { TenantManager } from "./components/TenantManager";
import { UsageView } from "./components/UsageView";
import { useToasts } from "./components/Toasts";
import { handleCallback } from "./oidc";
import type { DeviceStatusView } from "./types";

const ONLINE_MS = 10_000; // 與 fleet-svc repo.ONLINE_THRESHOLD_S 對齊
const LOW_BATTERY_PCT = 20;

type Tab = "map" | "fleet" | "missions" | "usage" | "tenants";

// adminOnly 分頁僅 admin 可見(前端 UX 閘門;後端仍以 RBAC 強制 /orgs admin only)。
const TABS: Array<{ key: Tab; label: string; adminOnly?: boolean }> = [
  { key: "map", label: "地圖監控" },
  { key: "fleet", label: "機隊管理" },
  { key: "missions", label: "任務" },
  { key: "usage", label: "用量" },
  { key: "tenants", label: "租戶", adminOnly: true },
];

export function App() {
  const { push } = useToasts();
  const [devices, setDevices] = useState<Record<string, DeviceStatusView>>({});
  const [connected, setConnected] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("map");
  const [authRequired, setAuthRequired] = useState(false);
  const [authVersion, setAuthVersion] = useState(0); // 登入後 bump → 重訂閱/重載
  const [, setTick] = useState(0);

  // operator 以上才可執行寫入(建立/派遣/控制/裝置編輯);隨登入狀態重算。
  const canWrite = useMemo(() => hasRole("operator"), [authVersion]);
  const isAdmin = useMemo(() => hasRole("admin"), [authVersion]);
  const roleLabel = useMemo(() => currentRoleLabel(), [authVersion]);

  // 依角色過濾分頁(admin 專屬分頁對非 admin 隱藏)。
  const visibleTabs = useMemo(() => TABS.filter((t) => !t.adminOnly || isAdmin), [isAdmin]);

  // 登出/降權後若停在已隱藏的分頁(如租戶),退回地圖。
  useEffect(() => {
    if (!visibleTabs.some((t) => t.key === tab)) setTab("map");
  }, [visibleTabs, tab]);

  // OIDC 回呼:若本次載入帶 ?code(SSO 導回),交換 token 並登入
  useEffect(() => {
    handleCallback()
      .then((token) => {
        if (token) {
          setToken(token);
          setAuthRequired(false);
          setDevices({});
          setAuthVersion((v) => v + 1);
        }
      })
      .catch(() => setAuthRequired(true));
  }, []);

  // 權威來源:定期拉 /status(含尚未上線的已註冊機)
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchStatus()
        .then((rows) => {
          if (cancelled) return;
          setAuthRequired(false);
          setDevices((prev) => {
            const next = { ...prev };
            for (const d of rows) next[d.serial] = { ...next[d.serial], ...d };
            return next;
          });
        })
        .catch((err) => {
          if (err instanceof AuthError) setAuthRequired(true);
        });
    load();
    const t = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [authVersion]);

  // 即時層:SSE 遙測合併(比輪詢更即時)。SSE 錯誤不強制登入(靠 REST 401 驅動)。
  useEffect(() => {
    return subscribeStream((e) => {
      setConnected(true);
      setDevices((prev) => {
        const cur = prev[e.drone_id];
        return {
          ...prev,
          [e.drone_id]: {
            device_id: cur?.device_id ?? e.drone_id,
            serial: e.drone_id,
            name: cur?.name ?? null,
            fleet_id: cur?.fleet_id ?? null,
            status: cur?.status ?? "provisioned",
            online: true,
            last_seen: new Date(e.unix_time_ms).toISOString(),
            lat_deg: e.lat_deg,
            lon_deg: e.lon_deg,
            rel_alt_m: e.rel_alt_m,
            battery_pct: e.battery_pct,
            flight_mode: e.flight_mode,
            armed: e.armed,
          },
        };
      });
    });
  }, [authVersion]);

  // last_seen 老化 → 定期 re-render 讓 online 退場
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 2000);
    return () => clearInterval(t);
  }, []);

  const onLogin = useCallback((token: string) => {
    setToken(token);
    setAuthRequired(false);
    setDevices({});
    setAuthVersion((v) => v + 1);
  }, []);

  const onLogout = useCallback(() => {
    clearToken();
    setDevices({});
    setAuthRequired(true);
    setAuthVersion((v) => v + 1); // 重算 canWrite/roleLabel
  }, []);

  const onAuthError = useCallback(() => setAuthRequired(true), []);

  const list = useMemo(() => {
    const now = Date.now();
    return Object.values(devices)
      .map((d) => ({
        ...d,
        online: d.last_seen ? now - new Date(d.last_seen).getTime() < ONLINE_MS : d.online,
      }))
      .sort((a, b) => a.serial.localeCompare(b.serial));
  }, [devices]);

  // 告警:低電量(<20%)/離線 的「進入」轉移才提示(避免每次 re-render 刷屏)。
  const alertState = useRef<Map<string, { low: boolean; online: boolean }>>(new Map());
  useEffect(() => {
    for (const d of list) {
      const prev = alertState.current.get(d.serial);
      const low = d.battery_pct != null && d.battery_pct < LOW_BATTERY_PCT;
      if (low && !(prev?.low ?? false)) {
        push("warn", `${d.serial} 低電量 ${d.battery_pct?.toFixed(0)}%`, `low-${d.serial}`);
      }
      // 曾知為在線、現在離線 → 告警(初次載入即離線不提示)
      if (prev?.online === true && !d.online) {
        push("warn", `${d.serial} 已離線`, `off-${d.serial}`);
      }
      alertState.current.set(d.serial, { low, online: d.online });
    }
  }, [list, push]);

  const onlineCount = list.filter((d) => d.online).length;

  return (
    <div className="app">
      {authRequired && <Login onSubmit={onLogin} />}
      <header className="topbar">
        <h1>無人機機隊指揮中心</h1>
        <span className="stat">
          {list.length} 台 · 線上 {onlineCount}
        </span>
        <nav className="tabs">
          {visibleTabs.map((t) => (
            <button
              key={t.key}
              className={`tab ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <span className="conn">
          <span className={`dot ${connected ? "on" : "off"}`} />
          {connected ? "即時串流已連線" : "等待串流"}
        </span>
        {roleLabel && <span className="role-badge">{roleLabel}</span>}
        {getToken() && (
          <button className="logout" onClick={onLogout}>
            登出
          </button>
        )}
      </header>

      {tab === "map" && (
        <div className="main">
          <aside className="sidebar">
            <FleetList devices={list} selected={selected} onSelect={setSelected} />
          </aside>
          <div className="map">
            <FleetMap devices={list} selected={selected} onSelect={setSelected} />
          </div>
        </div>
      )}
      {tab === "fleet" && (
        <div className="view-scroll">
          <DeviceManager canWrite={canWrite} onAuthError={onAuthError} />
        </div>
      )}
      {tab === "missions" && (
        <div className="view-scroll">
          <MissionManager canWrite={canWrite} onAuthError={onAuthError} />
        </div>
      )}
      {tab === "usage" && (
        <div className="view-scroll">
          <UsageView onAuthError={onAuthError} />
        </div>
      )}
      {tab === "tenants" && isAdmin && (
        <div className="view-scroll">
          <TenantManager onAuthError={onAuthError} />
        </div>
      )}
    </div>
  );
}
