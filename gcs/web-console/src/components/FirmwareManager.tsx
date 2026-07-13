import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createFirmware,
  listDeviceFirmware,
  listDevices,
  listFirmware,
  setDeviceFirmware,
} from "../api";
import { AuthError } from "../auth";
import type { Device, DeviceFirmware, Firmware, FirmwareComponent } from "../types";
import { Modal } from "./DeviceManager";
import { OtaForm } from "./OtaForm";
import { useToasts } from "./Toasts";

type Props = {
  canWrite: boolean; // operator 以上
  onAuthError: () => void;
};

const COMPONENTS: FirmwareComponent[] = ["px4", "onboard", "gcs", "payload"];

function fmtDate(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

// 韌體管理:型錄(列出 + 登錄)+ 裝置韌體指派 + 對選定裝置推送 OTA。
export function FirmwareManager({ canWrite, onAuthError }: Props) {
  const { push } = useToasts();
  const [firmware, setFirmware] = useState<Firmware[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [deviceId, setDeviceId] = useState("");
  const [deviceFw, setDeviceFw] = useState<DeviceFirmware[]>([]);
  const [fwLoading, setFwLoading] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [showOta, setShowOta] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [fw, dev] = await Promise.all([listFirmware(), listDevices()]);
      setFirmware(fw);
      setDevices(dev);
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入韌體/裝置失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const loadDeviceFw = useCallback(
    async (id: string) => {
      if (!id) {
        setDeviceFw([]);
        return;
      }
      setFwLoading(true);
      try {
        setDeviceFw(await listDeviceFirmware(id));
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else push("error", `載入裝置韌體失敗:${(err as Error).message}`);
      } finally {
        setFwLoading(false);
      }
    },
    [onAuthError, push],
  );

  useEffect(() => {
    void loadDeviceFw(deviceId);
  }, [deviceId, loadDeviceFw]);

  const selectedDevice = useMemo(
    () => devices.find((d) => d.id === deviceId) ?? null,
    [devices, deviceId],
  );

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>韌體管理</h2>
        <div className="actions">
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
          {canWrite && (
            <button className="btn primary" onClick={() => setShowCreate(true)}>
              + 登錄韌體
            </button>
          )}
        </div>
      </div>

      <section className="card">
        <h3>韌體型錄({firmware.length})</h3>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : firmware.length === 0 ? (
          <div className="empty">尚無韌體。{canWrite ? "點「登錄韌體」新增一版。" : ""}</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>元件</th>
                  <th>版本</th>
                  <th>發布時間</th>
                  <th>SBOM</th>
                  <th>登錄時間</th>
                </tr>
              </thead>
              <tbody>
                {firmware.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <span className="badge">{f.component}</span>
                    </td>
                    <td className="mono">{f.version}</td>
                    <td>{fmtDate(f.released_at)}</td>
                    <td className="mono">{f.sbom_ref ?? "—"}</td>
                    <td>{fmtDate(f.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>裝置韌體 / OTA</h3>
        <label className="inline-field">
          裝置
          <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
            <option value="">(選擇裝置)</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.serial}
                {d.name ? ` · ${d.name}` : ""}
              </option>
            ))}
          </select>
          {canWrite && selectedDevice && (
            <span className="row-actions">
              <button className="btn sm" onClick={() => setShowAssign(true)}>
                指派韌體版本
              </button>
              <button className="btn primary sm" onClick={() => setShowOta(true)}>
                推送 OTA
              </button>
            </span>
          )}
        </label>

        {!deviceId ? (
          <div className="empty">選擇裝置以檢視目前安裝韌體並推送 OTA。</div>
        ) : fwLoading ? (
          <div className="empty">載入中…</div>
        ) : deviceFw.length === 0 ? (
          <div className="empty">此裝置尚無已記錄的韌體版本。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>元件</th>
                  <th>目前版本</th>
                  <th>安裝時間</th>
                </tr>
              </thead>
              <tbody>
                {deviceFw.map((df) => (
                  <tr key={`${df.device_id}-${df.component}`}>
                    <td>
                      <span className="badge">{df.component}</span>
                    </td>
                    <td className="mono">{df.version}</td>
                    <td>{fmtDate(df.installed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showCreate && (
        <FirmwareForm
          onClose={() => setShowCreate(false)}
          onDone={() => {
            setShowCreate(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
      {showAssign && selectedDevice && (
        <AssignForm
          device={selectedDevice}
          firmware={firmware}
          onClose={() => setShowAssign(false)}
          onDone={() => {
            setShowAssign(false);
            void loadDeviceFw(deviceId);
          }}
          onAuthError={onAuthError}
        />
      )}
      {showOta && selectedDevice && (
        <OtaForm
          deviceId={selectedDevice.id}
          serial={selectedDevice.serial}
          onClose={() => setShowOta(false)}
          onDone={() => setShowOta(false)}
          onAuthError={onAuthError}
        />
      )}
    </div>
  );
}

// 登錄一版韌體到型錄(POST /firmware)。
function FirmwareForm({
  onClose,
  onDone,
  onAuthError,
}: {
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [component, setComponent] = useState<FirmwareComponent>("px4");
  const [version, setVersion] = useState("");
  const [releasedAt, setReleasedAt] = useState("");
  const [sbomRef, setSbomRef] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await createFirmware({
        component,
        version: version.trim(),
        // datetime-local 無時區,補 :00 並交後端解讀;空則不送(後端預設 null)。
        released_at: releasedAt ? new Date(releasedAt).toISOString() : null,
        sbom_ref: sbomRef.trim() || null,
      });
      push("info", `已登錄韌體 ${component} ${version.trim()}`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `登錄韌體失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title="登錄韌體" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          元件 *
          <select
            value={component}
            onChange={(e) => setComponent(e.target.value as FirmwareComponent)}
          >
            {COMPONENTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          版本 *
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            required
            placeholder="例:1.14.3"
          />
        </label>
        <label>
          發布時間
          <input
            type="datetime-local"
            value={releasedAt}
            onChange={(e) => setReleasedAt(e.target.value)}
          />
        </label>
        <label>
          SBOM 參照
          <input
            value={sbomRef}
            onChange={(e) => setSbomRef(e.target.value)}
            placeholder="選填,例:oci://…/sbom"
          />
        </label>
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn primary" disabled={busy || !version.trim()}>
            登錄
          </button>
        </div>
      </form>
    </Modal>
  );
}

// 記錄裝置某元件目前安裝的韌體版本(PUT /devices/{id}/firmware)。
function AssignForm({
  device,
  firmware,
  onClose,
  onDone,
  onAuthError,
}: {
  device: Device;
  firmware: Firmware[];
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [component, setComponent] = useState<FirmwareComponent>("px4");
  const [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false);

  // 該元件型錄中的已知版本(供快速選擇;仍可自行輸入)。
  const versions = useMemo(
    () => firmware.filter((f) => f.component === component).map((f) => f.version),
    [firmware, component],
  );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await setDeviceFirmware(device.id, { component, version: version.trim() });
      push("info", `已記錄 ${device.serial} 的 ${component} = ${version.trim()}`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `指派韌體失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title={`指派韌體 · ${device.serial}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          元件 *
          <select
            value={component}
            onChange={(e) => setComponent(e.target.value as FirmwareComponent)}
          >
            {COMPONENTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          版本 *
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            required
            list="fw-versions"
            placeholder="例:1.14.3"
          />
          <datalist id="fw-versions">
            {versions.map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        </label>
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn primary" disabled={busy || !version.trim()}>
            儲存
          </button>
        </div>
      </form>
    </Modal>
  );
}
