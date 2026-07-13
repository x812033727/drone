import { useCallback, useEffect, useMemo, useState } from "react";
import { createDevice, createFleet, listDevices, listFleets, updateDevice } from "../api";
import { AuthError } from "../auth";
import type { Device, DeviceStatus, Fleet } from "../types";
import { OtaForm } from "./OtaForm";
import { useToasts } from "./Toasts";

type Props = {
  canWrite: boolean; // operator 以上
  onAuthError: () => void;
};

const STATUS_LABEL: Record<DeviceStatus, string> = {
  provisioned: "已佈建",
  active: "服役中",
  retired: "已退役",
  revoked: "已撤銷",
};

// 裝置/機隊管理:列出 + 新增/編輯/退役 devices,新增 fleets。
export function DeviceManager({ canWrite, onAuthError }: Props) {
  const { push } = useToasts();
  const [devices, setDevices] = useState<Device[]>([]);
  const [fleets, setFleets] = useState<Fleet[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Device | null>(null);
  const [showDeviceForm, setShowDeviceForm] = useState(false);
  const [showFleetForm, setShowFleetForm] = useState(false);
  const [otaTarget, setOtaTarget] = useState<Device | null>(null); // 推送 OTA 目標

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [d, f] = await Promise.all([listDevices(), listFleets()]);
      setDevices(d);
      setFleets(f);
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入裝置/機隊失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const fleetName = useMemo(() => {
    const m = new Map(fleets.map((f) => [f.id, f.name]));
    return (id: string | null) => (id ? (m.get(id) ?? id) : "—");
  }, [fleets]);

  const retire = useCallback(
    async (d: Device) => {
      try {
        await updateDevice(d.id, { status: "retired" });
        push("info", `已退役 ${d.serial}`);
        void reload();
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else push("error", `退役失敗:${(err as Error).message}`);
      }
    },
    [onAuthError, push, reload],
  );

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>機隊管理</h2>
        <div className="actions">
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
          {canWrite && (
            <>
              <button className="btn" onClick={() => setShowFleetForm(true)}>
                + 新增機隊
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  setEditing(null);
                  setShowDeviceForm(true);
                }}
              >
                + 新增裝置
              </button>
            </>
          )}
        </div>
      </div>

      <section className="card">
        <h3>機隊({fleets.length})</h3>
        {fleets.length === 0 ? (
          <div className="empty">尚無機隊。</div>
        ) : (
          <ul className="chips">
            {fleets.map((f) => (
              <li key={f.id} className="chip">
                {f.name}
                {f.org_id ? <span className="muted"> · {f.org_id}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h3>裝置({devices.length})</h3>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : devices.length === 0 ? (
          <div className="empty">尚無裝置。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>序號</th>
                  <th>名稱</th>
                  <th>機型</th>
                  <th>機隊</th>
                  <th>狀態</th>
                  {canWrite && <th>操作</th>}
                </tr>
              </thead>
              <tbody>
                {devices.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.serial}</td>
                    <td>{d.name ?? "—"}</td>
                    <td>{d.model ?? "—"}</td>
                    <td>{fleetName(d.fleet_id)}</td>
                    <td>
                      <span className={`badge s-${d.status}`}>{STATUS_LABEL[d.status]}</span>
                    </td>
                    {canWrite && (
                      <td className="row-actions">
                        <button
                          className="btn ghost sm"
                          onClick={() => {
                            setEditing(d);
                            setShowDeviceForm(true);
                          }}
                        >
                          編輯
                        </button>
                        <button className="btn ghost sm" onClick={() => setOtaTarget(d)}>
                          推送 OTA
                        </button>
                        <button
                          className="btn ghost sm danger"
                          disabled={d.status === "retired"}
                          onClick={() => void retire(d)}
                        >
                          退役
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showFleetForm && (
        <FleetForm
          onClose={() => setShowFleetForm(false)}
          onDone={() => {
            setShowFleetForm(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
      {showDeviceForm && (
        <DeviceForm
          device={editing}
          fleets={fleets}
          onClose={() => setShowDeviceForm(false)}
          onDone={() => {
            setShowDeviceForm(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
      {otaTarget && (
        <OtaForm
          deviceId={otaTarget.id}
          serial={otaTarget.serial}
          onClose={() => setOtaTarget(null)}
          onDone={() => setOtaTarget(null)}
          onAuthError={onAuthError}
        />
      )}
    </div>
  );
}

function FleetForm({
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
  const [orgId, setOrgId] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await createFleet({ name: name.trim(), org_id: orgId.trim() || null });
      push("info", `已建立機隊 ${name.trim()}`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `建立機隊失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title="新增機隊" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          名稱 *
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          組織 ID
          <input value={orgId} onChange={(e) => setOrgId(e.target.value)} placeholder="選填" />
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

function DeviceForm({
  device,
  fleets,
  onClose,
  onDone,
  onAuthError,
}: {
  device: Device | null;
  fleets: Fleet[];
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const editMode = device !== null;
  const [serial, setSerial] = useState(device?.serial ?? "");
  const [name, setName] = useState(device?.name ?? "");
  const [model, setModel] = useState(device?.model ?? "");
  const [fleetId, setFleetId] = useState(device?.fleet_id ?? "");
  const [status, setStatus] = useState<DeviceStatus>(device?.status ?? "provisioned");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (editMode && device) {
        await updateDevice(device.id, {
          name: name.trim() || null,
          model: model.trim() || null,
          fleet_id: fleetId || null,
          status,
        });
        push("info", `已更新 ${device.serial}`);
      } else {
        await createDevice({
          serial: serial.trim(),
          name: name.trim() || null,
          model: model.trim() || null,
          fleet_id: fleetId || null,
        });
        push("info", `已建立裝置 ${serial.trim()}`);
      }
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `${editMode ? "更新" : "建立"}失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title={editMode ? `編輯 ${device?.serial}` : "新增裝置"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          序號 *
          <input
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            required
            disabled={editMode}
            placeholder="例:X500-0001"
          />
        </label>
        <label>
          名稱
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="選填" />
        </label>
        <label>
          機型
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="選填" />
        </label>
        <label>
          機隊
          <select value={fleetId} onChange={(e) => setFleetId(e.target.value)}>
            <option value="">(未指派)</option>
            {fleets.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        {editMode && (
          <label>
            狀態
            <select value={status} onChange={(e) => setStatus(e.target.value as DeviceStatus)}>
              <option value="provisioned">已佈建</option>
              <option value="active">服役中</option>
              <option value="retired">已退役</option>
              <option value="revoked">已撤銷</option>
            </select>
          </label>
        )}
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={busy || (!editMode && !serial.trim())}
          >
            {editMode ? "儲存" : "建立"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// 共用簡易 modal 外殼。
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="modal-close" onClick={onClose} aria-label="關閉">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
