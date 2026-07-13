import { useCallback, useEffect, useState } from "react";
import { listAlerts } from "../api";
import { AuthError } from "../auth";
import type { Alert } from "../types";
import { Modal } from "./DeviceManager";
import { useToasts } from "./Toasts";

const PAGE_SIZE = 50;

// kind 中文標籤(未知 kind 直接顯示原字串,前向相容後端新增類型)。
const KIND_LABEL: Record<string, string> = {
  cert: "憑證到期",
  ota: "OTA 進度",
};
export const kindLabel = (k: string) => KIND_LABEL[k] ?? k;

// badge 著色:cert=警示(琥珀)、ota=資訊(藍),其餘用預設中性色。
const kindClass = (k: string) => (k === "cert" ? "k-cert" : k === "ota" ? "k-ota" : "");

// ISO 時間 → 在地可讀字串;解析失敗則原樣顯示,避免 Invalid Date。
function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// 詳情值格式化:物件序列化為 JSON,null 顯示 —,其餘轉字串。
function fmtDetailValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// 裝置告警檢視(device_alerts):所有登入者看本 org(後端 org 隔離)。
// 讀 GET /api/v1/alerts:憑證到期(cert)/ OTA 進度(ota),分頁(X-Total-Count)+ kind 過濾。
export function AlertsView({ onAuthError }: { onAuthError: () => void }) {
  const { push } = useToasts();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [detailOf, setDetailOf] = useState<Alert | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listAlerts({ kind: kind || undefined, limit: PAGE_SIZE, offset });
      setAlerts(page.items);
      setTotal(page.total);
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入告警失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [kind, offset, onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 切換過濾器時回到第一頁(offset 變更會經 reload 依賴重載)。
  const onKindChange = (v: string) => {
    setKind(v);
    setOffset(0);
  };

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + alerts.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + alerts.length < total;

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>裝置告警</h2>
        <div className="actions">
          <label className="filter">
            類型
            <select value={kind} onChange={(e) => onKindChange(e.target.value)}>
              <option value="">全部</option>
              <option value="cert">憑證到期</option>
              <option value="ota">OTA 進度</option>
            </select>
          </label>
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
        </div>
      </div>

      <section className="card">
        <h3>告警({total})</h3>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : alerts.length === 0 ? (
          <div className="empty">{kind ? "此類型尚無告警。" : "尚無告警。"}</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>時間</th>
                  <th>裝置</th>
                  <th>類型</th>
                  <th>摘要</th>
                  <th>詳情</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a, i) => {
                  const hasDetail = Object.keys(a.detail ?? {}).length > 0;
                  return (
                    <tr key={`${a.time}|${a.drone_id}|${a.kind}|${i}`}>
                      <td className="mono">{fmtTime(a.time)}</td>
                      <td className="mono">{a.drone_id}</td>
                      <td>
                        <span className={`badge ${kindClass(a.kind)}`}>{kindLabel(a.kind)}</span>
                      </td>
                      <td>{a.summary}</td>
                      <td className="row-actions">
                        <button
                          className="btn ghost sm"
                          disabled={!hasDetail}
                          onClick={() => setDetailOf(a)}
                        >
                          詳情
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE_SIZE && (
          <div className="pager">
            <span className="muted">
              {from}–{to} / {total}
            </span>
            <button
              className="btn ghost sm"
              disabled={!hasPrev}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            >
              上一頁
            </button>
            <button
              className="btn ghost sm"
              disabled={!hasNext}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              下一頁
            </button>
          </div>
        )}
      </section>

      {detailOf && <AlertDetailModal alert={detailOf} onClose={() => setDetailOf(null)} />}
    </div>
  );
}

// 單筆告警詳情:時間/摘要 + detail 各欄位(chips)。
function AlertDetailModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const entries = Object.entries(alert.detail ?? {});
  return (
    <Modal title={`${kindLabel(alert.kind)} · ${alert.drone_id}`} onClose={onClose}>
      <div className="usage-modal">
        <div className="kv">
          <span className="muted">時間</span>
          <span className="mono">{fmtTime(alert.time)}</span>
        </div>
        <div className="kv">
          <span className="muted">摘要</span>
          <span>{alert.summary}</span>
        </div>
        <section className="card">
          <h3>詳情</h3>
          {entries.length === 0 ? (
            <div className="empty">無額外詳情。</div>
          ) : (
            <ul className="chips">
              {entries.map(([k, v]) => (
                <li key={k} className="chip">
                  {k} <span className="mono">{fmtDetailValue(v)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Modal>
  );
}
