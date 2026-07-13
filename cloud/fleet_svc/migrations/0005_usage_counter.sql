-- 用量計量(G30):每租戶計費相關操作按 (org_id, metric, 日期) 累計。
-- 供配額強制(每日量上限)與 GET /api/v1/usage 用量報表。
-- 只前向、冪等(IF NOT EXISTS 雙保險,配合 migrate 版本追蹤);不 drop 客戶資料。
--
-- 語義:一列 = 某租戶某計費指標在某 UTC 日的計數(如 device_created / fleet_created)。
-- period 以 UTC 日切齊,讓「每日量」配額與跨時區報表一致。累計以
-- INSERT ... ON CONFLICT DO UPDATE count = count + 1 原子遞增。

CREATE TABLE IF NOT EXISTS fleet.usage_counter (
    org_id  text   NOT NULL,
    metric  text   NOT NULL,
    period  date   NOT NULL DEFAULT (now() AT TIME ZONE 'utc')::date,
    count   bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, metric, period)
);

-- 依租戶彙總(GET /api/v1/usage 的 totals / 特定日查詢)常用索引。
CREATE INDEX IF NOT EXISTS usage_counter_org_idx ON fleet.usage_counter (org_id);
