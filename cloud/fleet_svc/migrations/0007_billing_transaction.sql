-- 訂閱金流(綠界 ECPay):每筆結帳/付款交易的紀錄。接續 #118 org 方案控制面 + #115 計量。
-- 只前向、冪等(IF NOT EXISTS;配合 migrate 版本追蹤);不 drop 客戶資料。
--
-- 語義:
--   trade_no  綠界 MerchantTradeNo(唯一)——結帳時產生,回調時據以對帳(冪等鍵)。
--   plan      本次結帳欲啟用的方案(pro/enterprise;free 不結帳)。
--   amount    金額(TWD 整數,綠界 TotalAmount)。
--   status    pending(已發起結帳,待付款)→ paid(綠界回調驗章成功)/ failed(付款失敗)。
--   at        建立(發起結帳)時間;updated_at 於回調更新狀態時刷新。
-- 流程:checkout 落一筆 pending;callback 驗 CheckMacValue 成功後轉 paid 並啟用 org 方案。
-- status 轉移具冪等性(已 paid 者重複回調不重複啟用),支撐綠界回調重送。

CREATE TABLE IF NOT EXISTS fleet.billing_transaction (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id     text NOT NULL,
    plan       text NOT NULL CHECK (plan IN ('free', 'pro', 'enterprise')),
    amount     integer NOT NULL,
    trade_no   text NOT NULL UNIQUE,
    status     text NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'paid', 'failed')),
    at         timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 某租戶的交易史多以時間新→舊查詢(訂閱狀態頁「最近交易」)。
CREATE INDEX IF NOT EXISTS billing_txn_org_idx ON fleet.billing_transaction (org_id, at DESC);
