import { useCallback, useEffect, useState } from "react";
import { getUsage } from "../api";
import { AuthError } from "../auth";
import type { UsageReport } from "../types";
import { BillingPanel } from "./BillingPanel";
import { useToasts } from "./Toasts";

// 計費指標中文標籤(未知 key 直接顯示原字串)。
const METRIC_LABEL: Record<string, string> = {
  device_created: "裝置建立",
  fleet_created: "機隊建立",
  devices: "現存裝置",
  fleets: "現存機隊",
};

const metricLabel = (k: string) => METRIC_LABEL[k] ?? k;

// limits 的 max_<res> 對應 resources 的 <res>。
const QUOTA_PAIRS: Array<{ limitKey: string; resourceKey: string; label: string }> = [
  { limitKey: "max_devices", resourceKey: "devices", label: "裝置" },
  { limitKey: "max_fleets", resourceKey: "fleets", label: "機隊" },
];

// 一條配額用量長條(現存 / 上限)。上限 <=0 視為未設限。
function QuotaBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const unlimited = !Number.isFinite(limit) || limit <= 0;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100));
  const over = !unlimited && used >= limit;
  const near = !unlimited && pct >= 80;
  return (
    <div className="quota">
      <div className="quota-head">
        <span>{label}</span>
        <span className="mono">
          {used}
          {unlimited ? " / 無上限" : ` / ${limit}`}
          {!unlimited && <span className="muted"> ({pct}%)</span>}
        </span>
      </div>
      <div className="meter">
        <div
          className={`meter-fill${over ? " over" : near ? " near" : ""}`}
          style={{ width: unlimited ? "0%" : `${pct}%` }}
        />
      </div>
    </div>
  );
}

// 純渲染:把一份 UsageReport 呈現為配額長條 + 計數表(admin 檢視他 org / 本 org 共用)。
export function UsageReportCard({ report }: { report: UsageReport }) {
  const counterKeys = Object.keys(report.counters).sort();
  const totalKeys = Object.keys(report.totals).sort();
  return (
    <>
      <section className="card">
        <h3>配額用量</h3>
        <div className="quotas">
          {QUOTA_PAIRS.map((p) => (
            <QuotaBar
              key={p.limitKey}
              label={p.label}
              used={report.resources[p.resourceKey] ?? 0}
              limit={report.limits[p.limitKey] ?? 0}
            />
          ))}
        </div>
      </section>

      <section className="card">
        <h3>本期計數(UTC {report.period})</h3>
        {counterKeys.length === 0 ? (
          <div className="empty">本期尚無計費事件。</div>
        ) : (
          <ul className="chips">
            {counterKeys.map((k) => (
              <li key={k} className="chip">
                {metricLabel(k)} <span className="mono">{report.counters[k]}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h3>歷來累計</h3>
        {totalKeys.length === 0 ? (
          <div className="empty">尚無累計。</div>
        ) : (
          <ul className="chips">
            {totalKeys.map((k) => (
              <li key={k} className="chip">
                {metricLabel(k)} <span className="mono">{report.totals[k]}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

// 本 org 用量/方案畫面(所有登入者)。讀 GET /api/v1/usage;
// 訂閱方案/升級結帳由 BillingPanel 承載(canWrite=operator 以上可升級)。
export function UsageView({
  canWrite,
  onAuthError,
}: {
  canWrite: boolean;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await getUsage());
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入用量失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>用量與配額</h2>
        <div className="actions">
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
        </div>
      </div>

      <BillingPanel canWrite={canWrite} onAuthError={onAuthError} />

      {loading && !report ? (
        <div className="empty">載入中…</div>
      ) : !report ? (
        <div className="empty">無用量資料。</div>
      ) : (
        <>
          <section className="card">
            <h3>租戶</h3>
            <div className="kv">
              <span className="muted">Org</span>
              <span className="mono">{report.org_id}</span>
            </div>
          </section>
          <UsageReportCard report={report} />
        </>
      )}
    </div>
  );
}
