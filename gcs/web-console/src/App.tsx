import { useEffect, useMemo, useState } from "react";
import { fetchStatus, subscribeStream } from "./api";
import { FleetList } from "./components/FleetList";
import { FleetMap } from "./components/FleetMap";
import type { DeviceStatusView } from "./types";

const ONLINE_MS = 10_000; // 與 fleet-svc repo.ONLINE_THRESHOLD_S 對齊

export function App() {
  const [devices, setDevices] = useState<Record<string, DeviceStatusView>>({});
  const [connected, setConnected] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [, setTick] = useState(0);

  // 權威來源:定期拉 /status(含尚未上線的已註冊機)
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchStatus()
        .then((rows) => {
          if (cancelled) return;
          setDevices((prev) => {
            const next = { ...prev };
            for (const d of rows) next[d.serial] = { ...next[d.serial], ...d };
            return next;
          });
        })
        .catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  // 即時層:SSE 遙測合併(比輪詢更即時)
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
  }, []);

  // last_seen 老化 → 定期 re-render 讓 online 退場
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 2000);
    return () => clearInterval(t);
  }, []);

  const list = useMemo(() => {
    const now = Date.now();
    return Object.values(devices)
      .map((d) => ({
        ...d,
        online: d.last_seen ? now - new Date(d.last_seen).getTime() < ONLINE_MS : d.online,
      }))
      .sort((a, b) => a.serial.localeCompare(b.serial));
  }, [devices]);

  const onlineCount = list.filter((d) => d.online).length;

  return (
    <div className="app">
      <header className="topbar">
        <h1>無人機機隊指揮中心</h1>
        <span className="stat">
          {list.length} 台 · 線上 {onlineCount}
        </span>
        <span className="conn">
          <span className={`dot ${connected ? "on" : "off"}`} />
          {connected ? "即時串流已連線" : "等待串流"}
        </span>
      </header>
      <div className="main">
        <aside className="sidebar">
          <FleetList devices={list} selected={selected} onSelect={setSelected} />
        </aside>
        <div className="map">
          <FleetMap devices={list} selected={selected} onSelect={setSelected} />
        </div>
      </div>
    </div>
  );
}
