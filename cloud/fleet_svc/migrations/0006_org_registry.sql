-- 租戶(org)註冊表 + 每租戶配額(計費控制面)。讓 #113 多租戶隔離 + #115 用量/配額
-- 真正可運營:平台可建立/列出租戶、設每租戶方案(plan)與配額覆寫,配額檢查優先讀本表。
-- 只前向、冪等(IF NOT EXISTS + ON CONFLICT DO NOTHING;配合 migrate 版本追蹤);不 drop 客戶資料。
--
-- 語義:
--   plan   方案(free/pro/enterprise)——決定「未覆寫」時的預設配額(對應表在 limits.py)。
--   status active/suspended——suspended 租戶的寫入被服務層擋下(admin 平台管理者豁免)。
--   max_devices / max_fleets 每租戶配額「覆寫」(NULL = 用 plan 預設;非 NULL = 硬覆寫)。
--     服務層解析順序:覆寫欄 → plan 預設 → env 全域預設(org 不在註冊表時)。

CREATE TABLE IF NOT EXISTS fleet.org (
    org_id      text PRIMARY KEY,
    name        text NOT NULL,
    plan        text NOT NULL DEFAULT 'free'
                CHECK (plan IN ('free', 'pro', 'enterprise')),
    status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended')),
    max_devices integer,       -- 配額覆寫(NULL = 用 plan 預設)
    max_fleets  integer,       -- 配額覆寫(NULL = 用 plan 預設)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS org_status_idx ON fleet.org (status);

-- 回填:既有 fleet/device 的 distinct org_id + 'default'(#113 前資料歸屬預設租戶)。
-- 既有租戶於計費上線前已存在 → grandfather 為 enterprise(額度寬鬆,不改變既有配額行為;
-- 新註冊租戶才走 plan 預設 free)。name 暫用 org_id,admin 之後可 PATCH 更名。
INSERT INTO fleet.org (org_id, name, plan)
SELECT s.org_id, s.org_id, 'enterprise'
FROM (
    SELECT DISTINCT org_id FROM fleet.fleet
    UNION
    SELECT DISTINCT org_id FROM fleet.device
    UNION
    SELECT 'default'
) s
WHERE s.org_id IS NOT NULL
ON CONFLICT (org_id) DO NOTHING;
