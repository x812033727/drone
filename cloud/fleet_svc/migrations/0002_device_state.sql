-- 裝置最新即時狀態(遙測消費者 upsert;查詢時算在線)。
-- 一機一列,以 drone_id(= MQTT 主題 fleet/{drone_id}/*,對應 device.serial)為鍵。
-- 位置先存 lat/lon 雙精度;PostGIS geography 待空間查詢需求再以 migration 引入。

CREATE TABLE fleet.device_state (
    drone_id    text PRIMARY KEY,
    last_seen   timestamptz NOT NULL,
    lat_deg     double precision,
    lon_deg     double precision,
    rel_alt_m   real,
    battery_pct real,
    flight_mode text,
    armed       boolean
);
