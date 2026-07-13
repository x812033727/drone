-- fleet-svc 關聯資料 schema(裝置註冊/機隊/韌體版本)。
-- 與遙測時序表(public.telemetry 等,init.sql)同一 timescaledb 實例、不同 schema。
-- 前向 SQL migration(fleet_svc.migrate 逐檔套用,已套用者跳過;不 drop 客戶資料)。
--
-- 位置先存 lat/lon 雙精度;PostGIS geography 待有空間查詢需求(geofence/半徑搜尋)再加。

CREATE SCHEMA IF NOT EXISTS fleet;

-- 機隊(一個組織下的機群分組)
CREATE TABLE fleet.fleet (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL,
    org_id     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 裝置(機身)。serial 為出廠序號,全域唯一,是機-雲身份綁定的錨點。
CREATE TABLE fleet.device (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    serial          text NOT NULL UNIQUE,
    name            text,
    fleet_id        uuid REFERENCES fleet.fleet(id) ON DELETE SET NULL,
    model           text,
    -- provisioned=已建檔未啟用 / active=服役中 / retired=退役 / revoked=憑證吊銷
    status          text NOT NULL DEFAULT 'provisioned'
                    CHECK (status IN ('provisioned', 'active', 'retired', 'revoked')),
    cert_fingerprint text,       -- Wave4 PKI 綁定:裝置憑證指紋(SHA-256)
    cert_not_after   timestamptz, -- 憑證到期(輪換排程用)
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON fleet.device (fleet_id);
CREATE INDEX ON fleet.device (status);

-- 韌體版本目錄(component × version 唯一);sbom_ref 指向 Wave6 SBOM artifact。
CREATE TABLE fleet.firmware_version (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    component   text NOT NULL CHECK (component IN ('px4', 'onboard', 'gcs', 'payload')),
    version     text NOT NULL,
    released_at timestamptz,
    sbom_ref    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (component, version)
);

-- 裝置目前安裝的各元件韌體版本(一機一元件一列)
CREATE TABLE fleet.device_firmware (
    device_id    uuid NOT NULL REFERENCES fleet.device(id) ON DELETE CASCADE,
    component    text NOT NULL CHECK (component IN ('px4', 'onboard', 'gcs', 'payload')),
    version      text NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, component)
);
