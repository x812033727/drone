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
    health_all_ok   boolean
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
