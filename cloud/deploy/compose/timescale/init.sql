-- Phase 0 遙測落庫 schema。單一 init.sql,砍掉重建;migration 工具屬 Phase 1。
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 對 interfaces/proto/drone/v1/telemetry.proto 的 TelemetrySummary
CREATE TABLE telemetry (
    time            timestamptz NOT NULL,
    drone_id        text        NOT NULL,
    lat_deg         double precision,
    lon_deg         double precision,
    rel_alt_m       real,
    heading_deg     real,
    ground_speed_ms real,
    flight_mode     text,
    armed           boolean,
    battery_v       real,
    battery_pct     real,
    health_all_ok   boolean,
    -- v0.3.0 新增:GPS 品質與垂直速度
    satellites        integer,
    gps_fix_type      text,
    hdop              real,
    vertical_speed_ms real
);
SELECT create_hypertable('telemetry', 'time');
CREATE INDEX ON telemetry (drone_id, time DESC);

-- 對 interfaces/proto/drone/v1/mission.proto 的 MissionProgress
CREATE TABLE mission_progress (
    time         timestamptz NOT NULL,
    mission_id   text        NOT NULL,
    drone_id     text        NOT NULL,
    current_item integer,
    total_items  integer,
    state        text
);
CREATE INDEX ON mission_progress (drone_id, time DESC);

-- 對 interfaces/proto/drone/v1/events.proto 的 FlightEvent(v0.3.0)
-- 主題 fleet/{drone_id}/events 為 QoS 1 at-least-once,重複投遞落庫多列無害
CREATE TABLE flight_events (
    time     timestamptz NOT NULL,
    drone_id text        NOT NULL,
    event    text
);
CREATE INDEX ON flight_events (drone_id, time DESC);

-- log-svc 的 ULog 回收摘要(S20;一般表,量小不需 hypertable)
-- 檔案本體在 named volume ulog-archive(/data/ulog/{drone_id}/),
-- 報告全文在同名 .report.txt;此表只留看板/查詢用摘要
CREATE TABLE flight_logs (
    time           timestamptz NOT NULL DEFAULT now(),
    drone_id       text        NOT NULL,
    filename       text        NOT NULL,
    size_bytes     bigint      NOT NULL,
    report_ok      boolean     NOT NULL,   -- ulog_report 是否產出可用報告(失敗照落庫)
    report_excerpt text                    -- 報告前 500 字(全文在 .report.txt)
);
CREATE INDEX ON flight_logs (drone_id, time DESC);
