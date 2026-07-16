import { useCallback, useEffect, useRef, useState } from "react";
import {
  commandMission,
  createMission,
  createRoute,
  dispatchMission,
  listMissions,
  listRoutes,
} from "../api";
import { AuthError } from "../auth";
import type { CommandKind, Mission, MissionStatus, Route, Waypoint } from "../types";
import { Modal } from "./DeviceManager";
import { WaypointMap, type LatLon } from "./WaypointMap";
import { useToasts } from "./Toasts";

type Props = {
  canWrite: boolean; // operator 以上
  onAuthError: () => void;
};

// 任務狀態機順序(對 mission_svc/models.py MissionStatus)。paused 併入 in_progress 節點呈現。
const FLOW: MissionStatus[] = [
  "created",
  "dispatched",
  "received",
  "uploaded",
  "in_progress",
  "completed",
];

const STATUS_LABEL: Record<MissionStatus, string> = {
  created: "已建立",
  dispatched: "已派遣",
  received: "已接收",
  uploaded: "已上傳",
  in_progress: "執行中",
  paused: "已暫停",
  completed: "已完成",
  failed: "失敗",
};

const POLL_MS = 5000;

export function MissionManager({ canWrite, onAuthError }: Props) {
  const { push } = useToasts();
  const [routes, setRoutes] = useState<Route[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [showMissionForm, setShowMissionForm] = useState(false);
  const prevStatus = useRef<Map<string, MissionStatus>>(new Map());

  const reload = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [r, m] = await Promise.all([listRoutes(), listMissions()]);
        setRoutes(r);
        // 偵測 FAILED 轉移 → 告警(僅在狀態變化時,避免刷屏)
        for (const mi of m) {
          const prev = prevStatus.current.get(mi.id);
          if (mi.status === "failed" && prev && prev !== "failed") {
            push("error", `任務 ${mi.mission_id}(${mi.drone_id})失敗`, `mfail-${mi.id}`);
          }
          prevStatus.current.set(mi.id, mi.status);
        }
        setMissions(m);
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else if (!silent) push("error", `載入任務失敗:${(err as Error).message}`);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [onAuthError, push],
  );

  useEffect(() => {
    void reload();
    const t = setInterval(() => void reload(true), POLL_MS);
    return () => clearInterval(t);
  }, [reload]);

  const dispatch = useCallback(
    async (m: Mission) => {
      try {
        await dispatchMission(m.id);
        push("info", `已派遣 ${m.mission_id} → ${m.drone_id}`);
        void reload(true);
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else push("error", `派遣失敗:${(err as Error).message}`);
      }
    },
    [onAuthError, push, reload],
  );

  const command = useCallback(
    async (m: Mission, cmd: CommandKind) => {
      try {
        await commandMission(m.id, cmd);
        push("info", `已送出 ${cmd} → ${m.mission_id}`);
        void reload(true);
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else push("error", `控制指令失敗:${(err as Error).message}`);
      }
    },
    [onAuthError, push, reload],
  );

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>任務</h2>
        <div className="actions">
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
          {canWrite && (
            <>
              <button className="btn" onClick={() => setShowRouteForm(true)}>
                + 新增航線
              </button>
              <button
                className="btn primary"
                disabled={routes.length === 0}
                title={routes.length === 0 ? "先建立航線" : undefined}
                onClick={() => setShowMissionForm(true)}
              >
                + 建立任務
              </button>
            </>
          )}
        </div>
      </div>

      <section className="card">
        <h3>航線({routes.length})</h3>
        {routes.length === 0 ? (
          <div className="empty">尚無航線。建立含航點的航線後即可派生任務。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>名稱</th>
                  <th>航點數</th>
                  <th>結束 RTL</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td>{r.waypoints.length}</td>
                    <td>{r.rtl_after_last ? "是" : "否"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>任務({missions.length})</h3>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : missions.length === 0 ? (
          <div className="empty">尚無任務。</div>
        ) : (
          <div className="mission-list">
            {missions.map((m) => (
              <MissionCard
                key={m.id}
                mission={m}
                canWrite={canWrite}
                onDispatch={() => void dispatch(m)}
                onCommand={(c) => void command(m, c)}
              />
            ))}
          </div>
        )}
      </section>

      {showRouteForm && (
        <RouteForm
          onClose={() => setShowRouteForm(false)}
          onDone={() => {
            setShowRouteForm(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
      {showMissionForm && (
        <MissionForm
          routes={routes}
          onClose={() => setShowMissionForm(false)}
          onDone={() => {
            setShowMissionForm(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
    </div>
  );
}

function MissionCard({
  mission,
  canWrite,
  onDispatch,
  onCommand,
}: {
  mission: Mission;
  canWrite: boolean;
  onDispatch: () => void;
  onCommand: (c: CommandKind) => void;
}) {
  const m = mission;
  const failed = m.status === "failed";
  const activeIdx = failed ? -1 : FLOW.indexOf(m.status === "paused" ? "in_progress" : m.status);
  const progress =
    m.total_items && m.total_items > 0 && m.current_item != null
      ? `${m.current_item}/${m.total_items}`
      : null;

  return (
    <div className={`mission ${failed ? "failed" : ""}`}>
      <div className="mission-top">
        <span className="mono strong">{m.mission_id}</span>
        <span className="muted">→ {m.drone_id}</span>
        <span className={`badge m-${m.status}`}>{STATUS_LABEL[m.status]}</span>
        {progress && <span className="muted">航點 {progress}</span>}
      </div>

      <div className="steps">
        {FLOW.map((s, i) => (
          <div
            key={s}
            className={`step ${i < activeIdx ? "done" : ""} ${i === activeIdx ? "now" : ""}`}
          >
            <span className="step-dot" />
            <span className="step-label">{STATUS_LABEL[s]}</span>
          </div>
        ))}
      </div>

      {canWrite && (
        <div className="mission-actions">
          <button className="btn sm primary" disabled={m.status !== "created"} onClick={onDispatch}>
            派遣
          </button>
          <button
            className="btn sm"
            disabled={m.status !== "in_progress"}
            onClick={() => onCommand("pause")}
          >
            暫停
          </button>
          <button
            className="btn sm"
            disabled={m.status !== "paused"}
            onClick={() => onCommand("resume")}
          >
            恢復
          </button>
          <button
            className="btn sm danger"
            disabled={["created", "completed", "failed"].includes(m.status)}
            onClick={() => onCommand("abort")}
          >
            中止
          </button>
        </div>
      )}
    </div>
  );
}

function RouteForm({
  onClose,
  onDone,
  onAuthError,
}: {
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [name, setName] = useState("");
  const [rtl, setRtl] = useState(true);
  const [rows, setRows] = useState<Array<{ lat: string; lon: string; alt: string }>>([
    { lat: "", lon: "", alt: "" },
  ]);
  const [busy, setBusy] = useState(false);

  const setRow = (i: number, key: "lat" | "lon" | "alt", val: string) =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, [key]: val } : r)));
  const addRow = () => setRows((prev) => [...prev, { lat: "", lon: "", alt: "" }]);
  const delRow = (i: number) => setRows((prev) => prev.filter((_, j) => j !== i));

  // 地圖 ↔ 表單雙向同步:已填妥經緯度的列 → 地圖標記;地圖操作 → 表單列。
  const mapPoints: LatLon[] = rows
    .map((r) => ({ lat: Number(r.lat), lon: Number(r.lon) }))
    .filter(
      (p) =>
        Number.isFinite(p.lat) &&
        Number.isFinite(p.lon) &&
        p.lat >= -90 &&
        p.lat <= 90 &&
        p.lon >= -180 &&
        p.lon <= 180 &&
        !(p.lat === 0 && p.lon === 0),
    );
  const addFromMap = (p: LatLon) =>
    setRows((prev) => {
      const wp = { lat: p.lat.toFixed(6), lon: p.lon.toFixed(6), alt: "30" };
      // 若最後一列是空白列(初始或按了「新增航點」),填入它;否則附加
      const last = prev[prev.length - 1];
      if (last && last.lat.trim() === "" && last.lon.trim() === "") {
        return prev.map((r, j) => (j === prev.length - 1 ? wp : r));
      }
      return [...prev, wp];
    });
  const moveFromMap = (index: number, p: LatLon) =>
    setRows((prev) =>
      prev.map((r, j) =>
        j === index ? { ...r, lat: p.lat.toFixed(6), lon: p.lon.toFixed(6) } : r,
      ),
    );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const waypoints: Waypoint[] = [];
    for (const [i, r] of rows.entries()) {
      const lat = Number(r.lat);
      const lon = Number(r.lon);
      const alt = Number(r.alt || "0");
      if (r.lat.trim() === "" || r.lon.trim() === "" || Number.isNaN(lat) || Number.isNaN(lon)) {
        push("warn", `第 ${i + 1} 個航點的經緯度無效`);
        return;
      }
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        push("warn", `第 ${i + 1} 個航點座標超出範圍`);
        return;
      }
      waypoints.push({ lat_deg: lat, lon_deg: lon, rel_alt_m: alt, hold_s: 0, speed_ms: 0 });
    }
    if (waypoints.length === 0) {
      push("warn", "至少需要一個航點");
      return;
    }
    setBusy(true);
    try {
      await createRoute({ name: name.trim(), waypoints, rtl_after_last: rtl });
      push("info", `已建立航線 ${name.trim()}`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `建立航線失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title="新增航線" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          名稱 *
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <div className="wp-head">
          <span>航點(緯度 / 經度 / 相對高度 m)——點地圖加點、拖曳移動</span>
        </div>
        <WaypointMap points={mapPoints} onAdd={addFromMap} onMove={moveFromMap} />
        <div className="wp-rows">
          {rows.map((r, i) => (
            <div className="wp-row" key={i}>
              <span className="wp-idx">{i + 1}</span>
              <input
                inputMode="decimal"
                placeholder="lat"
                value={r.lat}
                onChange={(e) => setRow(i, "lat", e.target.value)}
              />
              <input
                inputMode="decimal"
                placeholder="lon"
                value={r.lon}
                onChange={(e) => setRow(i, "lon", e.target.value)}
              />
              <input
                inputMode="decimal"
                placeholder="alt"
                value={r.alt}
                onChange={(e) => setRow(i, "alt", e.target.value)}
              />
              <button
                type="button"
                className="btn ghost sm"
                disabled={rows.length === 1}
                onClick={() => delRow(i)}
                aria-label="刪除航點"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="btn ghost sm" onClick={addRow}>
          + 新增航點
        </button>
        <label className="check">
          <input type="checkbox" checked={rtl} onChange={(e) => setRtl(e.target.checked)} />
          結束後自動返航(RTL)
        </label>
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn primary" disabled={busy || !name.trim()}>
            建立
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MissionForm({
  routes,
  onClose,
  onDone,
  onAuthError,
}: {
  routes: Route[];
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [routeId, setRouteId] = useState(routes[0]?.id ?? "");
  const [droneId, setDroneId] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await createMission({ route_id: routeId, drone_id: droneId.trim() });
      push("info", `已建立任務 → ${droneId.trim()}`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `建立任務失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title="建立任務" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          航線 *
          <select value={routeId} onChange={(e) => setRouteId(e.target.value)} required>
            {routes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}({r.waypoints.length} 航點)
              </option>
            ))}
          </select>
        </label>
        <label>
          目標機序號 *
          <input
            value={droneId}
            onChange={(e) => setDroneId(e.target.value)}
            required
            placeholder="例:X500-0001"
          />
        </label>
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={busy || !routeId || !droneId.trim()}
          >
            建立
          </button>
        </div>
      </form>
    </Modal>
  );
}
