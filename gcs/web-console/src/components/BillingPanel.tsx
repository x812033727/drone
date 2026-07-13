import { useCallback, useEffect, useState } from "react";
import { checkout, getSubscription } from "../api";
import { AuthError } from "../auth";
import type { CheckoutForm, OrgPlan, Subscription } from "../types";
import { useToasts } from "./Toasts";

const PLAN_LABEL: Record<OrgPlan, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
};

// 方案階梯:只提供「升級」(往更高階)。
const PLAN_ORDER: OrgPlan[] = ["free", "pro", "enterprise"];

const STATUS_LABEL: Record<string, string> = {
  active: "啟用",
  suspended: "停權",
};

// 交易狀態中文標籤(未知直接顯示原字串)。
const TXN_STATUS_LABEL: Record<string, string> = {
  pending: "處理中",
  paid: "已付款",
  failed: "失敗",
};

const NTD = (n: number) => `NT$ ${n.toLocaleString("en-US")}`;

// 綠界標準整合:後端回 action_url + 一堆 hidden 欄位(含 CheckMacValue),
// 前端動態組一個隱藏表單並 auto-submit,把整份參數原樣 POST 給綠界結帳頁。
// 用 DOM API 逐一建 input(型別安全,不碰 innerHTML/字串拼接)。
function submitCheckoutForm(form: CheckoutForm): void {
  const el = document.createElement("form");
  el.method = "POST";
  el.action = form.action_url;
  el.style.display = "none";
  el.acceptCharset = "utf-8";
  for (const [name, value] of Object.entries(form.params)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    el.appendChild(input);
  }
  document.body.appendChild(el);
  el.submit(); // 導向綠界(同分頁);瀏覽器隨即離開本頁。
}

// 本 org 訂閱/方案畫面(讀 GET /billing/subscription)。
// operator/admin(canWrite)可見升級按鈕並發起結帳;viewer 唯讀。
export function BillingPanel({
  canWrite,
  onAuthError,
}: {
  canWrite: boolean;
  onAuthError: () => void;
}) {
  const { push } = useToasts();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyPlan, setBusyPlan] = useState<OrgPlan | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setSub(await getSubscription());
    } catch (err) {
      if (err instanceof AuthError) onAuthError();
      else push("error", `載入訂閱失敗:${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [onAuthError, push]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onUpgrade = useCallback(
    async (plan: OrgPlan) => {
      setBusyPlan(plan);
      try {
        const form = await checkout(plan);
        push(
          "info",
          form.sandbox
            ? `沙箱模式:導向綠界測試結帳頁(不會真實扣款)`
            : `導向綠界結帳頁…`,
        );
        submitCheckoutForm(form); // 導向綠界,離開本頁
      } catch (err) {
        if (err instanceof AuthError) onAuthError();
        else push("error", `結帳失敗:${(err as Error).message}`);
        setBusyPlan(null); // 導向成功則已離頁;僅失敗時需解除忙碌
      }
    },
    [onAuthError, push],
  );

  if (loading && !sub) {
    return (
      <section className="card">
        <h3>訂閱方案</h3>
        <div className="empty">載入中…</div>
      </section>
    );
  }
  if (!sub) return null;

  const currentIdx = PLAN_ORDER.indexOf(sub.plan);
  // 僅比目前方案更高階者可升級(free→pro/enterprise、pro→enterprise)。
  const upgrades = PLAN_ORDER.filter((p) => PLAN_ORDER.indexOf(p) > currentIdx);
  const txns = sub.recent_transactions;

  return (
    <section className="card billing">
      <div className="billing-head">
        <h3>訂閱方案</h3>
        {sub.sandbox && (
          <span className="badge sandbox" title="未設正式綠界憑證,結帳走沙箱不會真實扣款">
            沙箱模式
          </span>
        )}
      </div>

      <div className="kv">
        <span className="muted">方案</span>
        <span className="strong">{PLAN_LABEL[sub.plan]}</span>
        <span className={`badge s-${sub.status}`}>
          {STATUS_LABEL[sub.status] ?? sub.status}
        </span>
      </div>
      <div className="kv">
        <span className="muted">月費</span>
        <span className="mono">{sub.price > 0 ? `${NTD(sub.price)} / 月` : "免費"}</span>
      </div>

      {canWrite ? (
        upgrades.length > 0 ? (
          <div className="billing-actions">
            {upgrades.map((p) => (
              <button
                key={p}
                className="btn primary"
                disabled={busyPlan !== null}
                onClick={() => void onUpgrade(p)}
              >
                {busyPlan === p ? "導向結帳中…" : `升級至 ${PLAN_LABEL[p]}`}
              </button>
            ))}
          </div>
        ) : (
          <div className="empty">已是最高方案。</div>
        )
      ) : (
        <div className="empty">升級需 operator 以上權限。</div>
      )}

      {txns.length > 0 && (
        <div className="billing-txns">
          <h3>最近交易</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>時間</th>
                  <th>方案</th>
                  <th>金額</th>
                  <th>狀態</th>
                  <th>訂單號</th>
                </tr>
              </thead>
              <tbody>
                {txns.map((t) => (
                  <tr key={t.id}>
                    <td className="mono">{new Date(t.at).toLocaleString()}</td>
                    <td>{PLAN_LABEL[t.plan]}</td>
                    <td className="mono">{NTD(t.amount)}</td>
                    <td>
                      <span className={`badge txn-${t.status}`}>
                        {TXN_STATUS_LABEL[t.status] ?? t.status}
                      </span>
                    </td>
                    <td className="mono">{t.trade_no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
