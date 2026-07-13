import { useMemo, useState } from "react";
import { triggerOta } from "../api";
import { AuthError } from "../auth";
import type { FirmwareComponent, OtaAction } from "../types";
import { Modal } from "./DeviceManager";
import { useToasts } from "./Toasts";

// 對齊機上 ota.py 契約:install 需 update_id + component/version/url/sha256/signature 齊備;
// pause/resume/rollback 只需 update_id(rollback 可帶 component)。前端僅做 UX 預檢,
// 真正驗證仍由 fleet-svc DeviceOtaRequest(sha256 64-hex、install 必填欄位)強制。
const ACTIONS: Array<{ value: OtaAction; label: string }> = [
  { value: "install", label: "安裝(install)" },
  { value: "pause", label: "暫停(pause)" },
  { value: "resume", label: "續傳(resume)" },
  { value: "rollback", label: "回滾(rollback)" },
];

const COMPONENTS: FirmwareComponent[] = ["px4", "onboard", "gcs", "payload"];

const SHA256_RE = /^[0-9a-f]{64}$/;

type Props = {
  deviceId: string;
  serial: string;
  // 由韌體型錄觸發時預填 component/version,operator 只需補 url/sha256/signature。
  prefill?: { component?: FirmwareComponent; version?: string } | null;
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
};

// 推送 OTA 表單:選動作 + 依動作填欄位,POST /devices/{id}/ota。
export function OtaForm({ deviceId, serial, prefill, onClose, onDone, onAuthError }: Props) {
  const { push } = useToasts();
  const [action, setAction] = useState<OtaAction>("install");
  const [updateId, setUpdateId] = useState("");
  const [component, setComponent] = useState<FirmwareComponent | "">(prefill?.component ?? "");
  const [version, setVersion] = useState(prefill?.version ?? "");
  const [url, setUrl] = useState("");
  const [size, setSize] = useState("");
  const [sha256, setSha256] = useState("");
  const [signature, setSignature] = useState("");
  const [busy, setBusy] = useState(false);

  const isInstall = action === "install";
  const isRollback = action === "rollback";
  // rollback 可帶 component;install 必帶;pause/resume 無 component。
  const showComponent = isInstall || isRollback;
  const showInstallFields = isInstall;

  const shaValid = sha256 === "" || SHA256_RE.test(sha256.trim().toLowerCase());

  // 送出前的 UX 閘門:對齊後端必填規則。
  const canSubmit = useMemo(() => {
    if (busy || !updateId.trim()) return false;
    if (isInstall) {
      if (!component || !version.trim() || !url.trim() || !signature.trim()) return false;
      if (!SHA256_RE.test(sha256.trim().toLowerCase())) return false;
    }
    return true;
  }, [busy, updateId, isInstall, component, version, url, signature, sha256]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const sizeNum = size.trim() ? Number(size.trim()) : undefined;
      await triggerOta(deviceId, {
        action,
        update_id: updateId.trim(),
        // 僅在相關動作帶對應欄位,避免送出 install 才需要的空值。
        component: showComponent && component ? component : undefined,
        version: isInstall ? version.trim() : undefined,
        url: isInstall ? url.trim() : undefined,
        size: isInstall && sizeNum != null && Number.isFinite(sizeNum) ? sizeNum : undefined,
        sha256: isInstall ? sha256.trim().toLowerCase() : undefined,
        signature: isInstall ? signature.trim() : undefined,
      });
      push("info", `已對 ${serial} 發送 OTA(${action})· 進度見「告警」分頁`);
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `OTA 推送失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title={`推送 OTA · ${serial}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          動作 *
          <select value={action} onChange={(e) => setAction(e.target.value as OtaAction)}>
            {ACTIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          更新 ID(update_id)*
          <input
            value={updateId}
            onChange={(e) => setUpdateId(e.target.value)}
            required
            placeholder="例:ota-2026-07-13-001"
          />
        </label>
        {showComponent && (
          <label>
            元件{isInstall ? " *" : "(選填)"}
            <select
              value={component}
              onChange={(e) => setComponent(e.target.value as FirmwareComponent | "")}
            >
              <option value="">(未指定)</option>
              {COMPONENTS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        )}
        {showInstallFields && (
          <>
            <label>
              版本(version)*
              <input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="例:1.14.3"
              />
            </label>
            <label>
              下載網址(url)*
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…/firmware.bin"
              />
            </label>
            <label>
              大小 bytes(size,選填)
              <input
                type="number"
                min={0}
                value={size}
                onChange={(e) => setSize(e.target.value)}
                placeholder="選填"
              />
            </label>
            <label>
              SHA256 *（64 字元小寫 hex）
              <input
                value={sha256}
                onChange={(e) => setSha256(e.target.value)}
                placeholder="64 hex"
                className={sha256 && !shaValid ? "invalid" : undefined}
              />
              {sha256 && !shaValid && <small className="field-err">須為 64 字元小寫 hex</small>}
            </label>
            <label>
              簽章(signature)*
              <input
                value={signature}
                onChange={(e) => setSignature(e.target.value)}
                placeholder="離線 HSM 產生的 base64 簽章"
              />
            </label>
          </>
        )}
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="btn primary" disabled={!canSubmit}>
            推送
          </button>
        </div>
      </form>
    </Modal>
  );
}
