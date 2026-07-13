-- 限流計數(DB-backed 固定視窗)。修 replicas>1 時舊記憶體 token bucket 的 per-process
-- 近似問題(N 副本 ≈ N×設定值):計數落單一共用 DB,故多副本部署有效限流精確、免 Redis。
-- 只前向、冪等(IF NOT EXISTS,配合 migrate 版本追蹤);不 drop 客戶資料。
--
-- 語義:一列 = 某租戶某固定視窗(window_start)內的寫入計數。
-- window_start = 視窗起點 UTC epoch 秒,對齊 60 秒(RATE_LIMIT_PER_MIN 為每分鐘上限)。
-- 累計以 INSERT ... ON CONFLICT (org_id, window_start) DO UPDATE count = count + 1
-- RETURNING count 原子遞增;超過上限即回 429。
--
-- 過期視窗列可留(不影響正確性:限流只讀當前視窗)。若需回收,可另接 CronJob
-- 定期 DELETE FROM mission.rate_limit_counter WHERE window_start < <now-緩衝>(非必要;
-- window_start 索引支援)。

CREATE TABLE IF NOT EXISTS mission.rate_limit_counter (
    org_id       text   NOT NULL,
    window_start bigint NOT NULL,
    count        bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, window_start)
);

-- 過期視窗回收(選配 CronJob)依 window_start 掃描的索引。
CREATE INDEX IF NOT EXISTS rate_limit_counter_window_idx
    ON mission.rate_limit_counter (window_start);
