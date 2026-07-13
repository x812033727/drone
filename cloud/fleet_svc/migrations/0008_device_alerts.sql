-- 告警閉環(OTA 觸發 + 告警落地):cert 到期告警 + OTA 進度統一落 device_alerts。
--
-- ingest 訂閱 fleet/+/alerts 與 fleet/+/ota/progress 落此表;fleet-svc 以
-- GET /api/v1/alerts 供運維查詢(join fleet.device 做多租戶隔離)。
--
-- 放 public schema(非 fleet schema):ingest 無 migration runner、其落庫 SQL 一律
-- 不加 schema 前綴(同 telemetry / mission_progress……,見 compose init.sql),故此表
-- 也建在 public。compose 由 timescale/init.sql 於首次建庫建立此表;本 migration 以
-- IF NOT EXISTS 冪等補建,涵蓋 helm migrate-job / 既有庫升級 / 單元測試等無 init.sql
-- 的路徑,並可與 init.sql 共存(先建者贏,後者 no-op)。
CREATE TABLE IF NOT EXISTS device_alerts (
    time     timestamptz NOT NULL,
    drone_id text        NOT NULL,
    kind     text        NOT NULL,   -- 'cert' | 'ota'
    summary  text        NOT NULL,   -- cert:alert 名;ota:state
    detail   jsonb                    -- 其餘欄位(days_remaining / update_id / version……)
);
CREATE INDEX IF NOT EXISTS device_alerts_drone_time_idx ON device_alerts (drone_id, time DESC);
CREATE INDEX IF NOT EXISTS device_alerts_time_idx ON device_alerts (time DESC);
