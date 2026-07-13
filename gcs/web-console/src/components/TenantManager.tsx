import { useCallback, useEffect, useState } from "react";
import { createOrg, getOrgUsage, listOrgs, updateOrg } from "../api";
import { AuthError } from "../auth";
import type { Org, OrgPlan, OrgStatus, OrgUpdate, UsageReport } from "../types";
import { Modal } from "./DeviceManager";
import { UsageReportCard } from "./UsageView";
import { useToasts } from "./Toasts";

const PLAN_LABEL: Record<OrgPlan, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
};

const STATUS_LABEL: Record<OrgStatus, string> = {
  active: "啟用",
  suspended: "停權",
};

const PAGE_SIZE = 50;

// 租戶(orgs)管理:列出 + 分頁 + 建立/編輯 + 檢視某租戶用量。僅 admin 掛載此視圖。
export function TenantManager({ onAuthError }: { onAuthError: () => void }) {
  const { push } = useToasts();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Org | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [usageFor, setUsageFor] = useState<Org | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listOrgs({ limit: PAGE_SIZE, offset });
      setOrgs(page.items);
      setTotal(page.total);
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入租戶失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [offset, onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + orgs.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + orgs.length < total;

  return (
    <div className="manager">
      <div className="manager-head">
        <h2>租戶管理</h2>
        <div className="actions">
          <button className="btn ghost" onClick={() => void reload()}>
            重新整理
          </button>
          <button
            className="btn primary"
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
          >
            + 建立租戶
          </button>
        </div>
      </div>

      <section className="card">
        <h3>租戶({total})</h3>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : orgs.length === 0 ? (
          <div className="empty">尚無租戶。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Org ID</th>
                  <th>名稱</th>
                  <th>方案</th>
                  <th>狀態</th>
                  <th>配額(裝置 / 機隊)</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((o) => (
                  <tr key={o.org_id}>
                    <td className="mono">{o.org_id}</td>
                    <td>{o.name}</td>
                    <td>{PLAN_LABEL[o.plan]}</td>
                    <td>
                      <span className={`badge s-${o.status === "active" ? "active" : "revoked"}`}>
                        {STATUS_LABEL[o.status]}
                      </span>
                    </td>
                    <td className="mono">
                      {o.max_devices ?? "預設"} / {o.max_fleets ?? "預設"}
                    </td>
                    <td className="row-actions">
                      <button
                        className="btn ghost sm"
                        onClick={() => {
                          setEditing(o);
                          setShowForm(true);
                        }}
                      >
                        編輯
                      </button>
                      <button className="btn ghost sm" onClick={() => setUsageFor(o)}>
                        用量
                      </button>
                    </td>
                  </tr>
                ))}
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

      {showForm && (
        <OrgForm
          org={editing}
          onClose={() => setShowForm(false)}
          onDone={() => {
            setShowForm(false);
            void reload();
          }}
          onAuthError={onAuthError}
        />
      )}
      {usageFor && (
        <OrgUsageModal org={usageFor} onClose={() => setUsageFor(null)} onAuthError={onAuthError} />
      )}
    </div>
  );
}

// 建立 / 編輯租戶表單。編輯時 org_id 唯讀;max_* 留空=用 plan 預設(送 null 清除覆寫)。
function OrgForm({
  org,
  onClose,
  onDone,
  onAuthError,
}: {
  org: Org | null;
  onClose: () => void;
  onDone: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const editMode = org !== null;
  const [orgId, setOrgId] = useState(org?.org_id ?? "");
  const [name, setName] = useState(org?.name ?? "");
  const [plan, setPlan] = useState<OrgPlan>(org?.plan ?? "free");
  const [status, setStatus] = useState<OrgStatus>(org?.status ?? "active");
  const [maxDevices, setMaxDevices] = useState(org?.max_devices != null ? String(org.max_devices) : "");
  const [maxFleets, setMaxFleets] = useState(org?.max_fleets != null ? String(org.max_fleets) : "");
  const [busy, setBusy] = useState(false);

  // 空字串→null(用 plan 預設);否則轉數字。非負整數由後端再驗。
  const parseQuota = (v: string): number | null => {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? Math.trunc(n) : null;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (editMode && org) {
        const body: OrgUpdate = {
          name: name.trim(),
          plan,
          status,
          max_devices: parseQuota(maxDevices),
          max_fleets: parseQuota(maxFleets),
        };
        await updateOrg(org.org_id, body);
        push("info", `已更新租戶 ${org.org_id}`);
      } else {
        await createOrg({
          org_id: orgId.trim(),
          name: name.trim(),
          plan,
          status,
          max_devices: parseQuota(maxDevices),
          max_fleets: parseQuota(maxFleets),
        });
        push("info", `已建立租戶 ${orgId.trim()}`);
      }
      onDone();
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `${editMode ? "更新" : "建立"}失敗:${(err as Error).message}`);
      setBusy(false);
    }
  };

  return (
    <Modal title={editMode ? `編輯 ${org?.org_id}` : "建立租戶"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          Org ID *
          <input
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            required
            disabled={editMode}
            placeholder="例:acme"
          />
        </label>
        <label>
          名稱 *
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          方案
          <select value={plan} onChange={(e) => setPlan(e.target.value as OrgPlan)}>
            <option value="free">Free</option>
            <option value="pro">Pro</option>
            <option value="enterprise">Enterprise</option>
          </select>
        </label>
        <label>
          狀態
          <select value={status} onChange={(e) => setStatus(e.target.value as OrgStatus)}>
            <option value="active">啟用</option>
            <option value="suspended">停權</option>
          </select>
        </label>
        <label>
          裝置配額覆寫
          <input
            type="number"
            min={0}
            value={maxDevices}
            onChange={(e) => setMaxDevices(e.target.value)}
            placeholder="留空=用方案預設"
          />
        </label>
        <label>
          機隊配額覆寫
          <input
            type="number"
            min={0}
            value={maxFleets}
            onChange={(e) => setMaxFleets(e.target.value)}
            placeholder="留空=用方案預設"
          />
        </label>
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={busy || !name.trim() || (!editMode && !orgId.trim())}
          >
            {editMode ? "儲存" : "建立"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// 某租戶用量彙總(GET /orgs/{id}/usage)+ 該租戶方案/狀態(取自列表列)。
function OrgUsageModal({
  org,
  onClose,
  onAuthError,
}: {
  org: Org;
  onClose: () => void;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getOrgUsage(org.org_id)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch((err) => {
        if (err instanceof AuthError) onAuthError();
        else push("error", `載入用量失敗:${(err as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [org.org_id, onAuthError, push]);

  return (
    <Modal title={`${org.name} · 用量`} onClose={onClose}>
      <div className="usage-modal">
        <div className="kv">
          <span className="muted">方案</span>
          <span>{PLAN_LABEL[org.plan]}</span>
        </div>
        <div className="kv">
          <span className="muted">狀態</span>
          <span>{STATUS_LABEL[org.status]}</span>
        </div>
        {loading ? (
          <div className="empty">載入中…</div>
        ) : report ? (
          <UsageReportCard report={report} />
        ) : (
          <div className="empty">無用量資料。</div>
        )}
      </div>
    </Modal>
  );
}
