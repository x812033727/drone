-- 審計軌跡(G14):對變更操作(建立/編輯/退役 裝置與機隊、韌體)留不可否認紀錄。
-- 旁路寫入——由 fleet_svc.audit best-effort 記錄,寫入失敗不影響主操作。
-- 只前向(migrate 以版本追蹤冪等,不重複套用);查詢供稽核(GET /api/v1/audit,admin)。

CREATE TABLE fleet.audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    actor         text NOT NULL,               -- JWT subject / username;dev 模式為 'dev'
    role          text,                        -- 當下最高角色(viewer/operator/admin)
    action        text NOT NULL,               -- create / update / delete / dispatch / command ...
    resource_type text NOT NULL,               -- device / fleet / firmware / mission ...
    resource_id   text,                        -- 受影響資源識別(uuid/serial 等,以字串存)
    details       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- 補充脈絡(不含機敏)
    source_ip     text                         -- 來源 IP(可選;代理後可能為空)
);

-- 稽核檢視多以時間新→舊翻頁;另按資源查特定實體的變更史
CREATE INDEX ON fleet.audit_log (at DESC);
CREATE INDEX ON fleet.audit_log (resource_type, resource_id);
