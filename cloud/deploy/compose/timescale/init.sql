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

-- 對 interfaces/proto/drone/v1/device.proto 的 DeviceHeartbeat(v0.5.0)
-- 主題 fleet/{drone_id}/heartbeat,預設 30 s,QoS 1;agent 存活即發(獨立於飛行遙測),
-- 供看板「最後上線/軟韌體版本」欄。boot_time 為 agent 開機時刻(epoch)。
CREATE TABLE device_heartbeat (
    time             timestamptz NOT NULL,
    drone_id         text        NOT NULL,
    agent_version    text,
    firmware_version text,
    boot_time        timestamptz,
    uptime_s         bigint
);
CREATE INDEX ON device_heartbeat (drone_id, time DESC);

-- 對 interfaces/proto/drone/v1/sensors.proto 的高頻感測器流(v0.4.0,S22)
-- 主題 fleet/{drone_id}/sensors/*,5 Hz 預設,QoS 0 容失;
-- px4_timestamp_us 是 PX4 boot-time 起算微秒(非 epoch),原樣保留供機內時序分析
CREATE TABLE sensor_attitude (
    time             timestamptz NOT NULL,
    drone_id         text        NOT NULL,
    px4_timestamp_us bigint,
    -- 四元數,Hamilton 慣例 (w, x, y, z),FRD 機體系 → NED 地理系
    q_w real,
    q_x real,
    q_y real,
    q_z real
);
SELECT create_hypertable('sensor_attitude', 'time');
CREATE INDEX ON sensor_attitude (drone_id, time DESC);

CREATE TABLE sensor_gps (
    time             timestamptz NOT NULL,
    drone_id         text        NOT NULL,
    px4_timestamp_us bigint,
    latitude_deg     double precision,
    longitude_deg    double precision,
    altitude_msl_m   real,
    satellites_used  integer,
    hdop             real,
    vdop             real,
    fix_type         text
);
SELECT create_hypertable('sensor_gps', 'time');
CREATE INDEX ON sensor_gps (drone_id, time DESC);

CREATE TABLE sensor_local_position (
    time             timestamptz NOT NULL,
    drone_id         text        NOT NULL,
    px4_timestamp_us bigint,
    -- NED 地理系:x 北 / y 東 / z 下(負值 = 起始點上方);heading 弧度 -PI..+PI
    x       real,
    y       real,
    z       real,
    vx      real,
    vy      real,
    vz      real,
    heading real
);
SELECT create_hypertable('sensor_local_position', 'time');
CREATE INDEX ON sensor_local_position (drone_id, time DESC);

-- log-svc 的 ULog 回收摘要(S20;一般表,量小不需 hypertable)
-- 檔案本體在 named volume ulog-archive(/data/ulog/{drone_id}/),
-- 報告全文在同名 .report.txt;此表只留看板/查詢用摘要
CREATE TABLE flight_logs (
    time           timestamptz NOT NULL DEFAULT now(),
    drone_id       text        NOT NULL,
    filename       text        NOT NULL,
    size_bytes     bigint      NOT NULL,
    report_ok      boolean     NOT NULL,   -- ulog_report 是否產出可用報告(失敗照落庫)
    report_excerpt text,                   -- 報告前 500 字(全文在 .report.txt)
    alerts         text                    -- 異常規則條目(「⚠ 異常提示」逐條換行相接;無異常 NULL)
);
CREATE INDEX ON flight_logs (drone_id, time DESC);

-- 告警閉環(ingest 訂閱 fleet/+/alerts 與 fleet/+/ota/progress → 此表)。
-- 兩類 proto 契約外的純 JSON 告警統一落此表,kind 區分:
--   kind='cert':裝置憑證將到期(cert_monitor.py 的 expiry_alert_json)。
--   kind='ota' :OTA 進度/終態(ota.py 的 progress_dict;summary=state)。
-- drone_id 一律取自主題(fleet/{drone_id}/...);OTA 進度 payload 本身不含 drone_id。
-- summary = 該告警主旨(cert:alert 名;ota:state);detail = 其餘欄位(jsonb)。
-- fleet-svc 以 GET /api/v1/alerts 供運維查詢(join fleet.device 做多租戶隔離)。
-- 量小(天/事件級,非高頻),Phase 0 一般表即可,不設 hypertable/保留政策。
CREATE TABLE device_alerts (
    time     timestamptz NOT NULL,
    drone_id text        NOT NULL,
    kind     text        NOT NULL,   -- 'cert' | 'ota'
    summary  text        NOT NULL,   -- cert:alert 名;ota:state
    detail   jsonb                    -- 其餘欄位(days_remaining / update_id / version……)
);
CREATE INDEX ON device_alerts (drone_id, time DESC);
CREATE INDEX ON device_alerts (time DESC);

-- ============================================================================
-- 資料保留 / 壓縮政策(G20)—— 只對高頻遙測/感測器 hypertable。
--
-- 本檔僅於「首次建庫」(空資料目錄)由 docker-entrypoint-initdb.d 執行一次;
-- 政策函式一律帶 if_not_exists => true,重跑亦不報錯(冪等)。
--
-- 保留 90 天(RETENTION_DAYS):超過 90 天的 chunk 由背景 job 自動 drop。
-- 壓縮 7 天後(COMPRESS_AFTER):較舊 chunk 轉列存壓縮省空間,查詢仍透明可讀。
-- 兩者皆為背景排程,不影響近期(剛落庫)資料——不會刪/壓當下寫入的列,
-- 故不影響 cloud-smoke 的落庫斷言。天數為 Phase 0 合理預設,正式部署可依合約調整。
--
-- 非 hypertable 的表(mission_progress / flight_events / device_heartbeat / flight_logs)
-- 量小,Phase 0 暫不設保留;日後量大再轉 hypertable 並比照設政策。
-- ============================================================================

-- telemetry(1 Hz 摘要)
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'drone_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => true);
SELECT add_retention_policy('telemetry', INTERVAL '90 days', if_not_exists => true);

-- sensor_attitude(高頻,5 Hz)
ALTER TABLE sensor_attitude SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'drone_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('sensor_attitude', INTERVAL '7 days', if_not_exists => true);
SELECT add_retention_policy('sensor_attitude', INTERVAL '90 days', if_not_exists => true);

-- sensor_gps(高頻,5 Hz)
ALTER TABLE sensor_gps SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'drone_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('sensor_gps', INTERVAL '7 days', if_not_exists => true);
SELECT add_retention_policy('sensor_gps', INTERVAL '90 days', if_not_exists => true);

-- sensor_local_position(高頻,5 Hz)
ALTER TABLE sensor_local_position SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'drone_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('sensor_local_position', INTERVAL '7 days', if_not_exists => true);
SELECT add_retention_policy('sensor_local_position', INTERVAL '90 days', if_not_exists => true);
