-- mission-svc 任務/航線 schema(對 docs/20-software/cloud-fleet.md §6 派遣契約)。
-- 與遙測時序表、fleet schema 同一 timescaledb 實例、不同 schema。
-- mission_id 為端到端追溯鍵(= MissionPlan.mission_id,機-雲共用)。

CREATE SCHEMA IF NOT EXISTS mission;

-- 航線庫(可重用;waypoints 直接存 MissionPlan.waypoints 陣列,與 proto 對齊零轉換)
CREATE TABLE mission.route (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name           text NOT NULL,
    org_id         text,
    waypoints      jsonb NOT NULL,
    rtl_after_last boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- 派遣單(FleetMission):route × 目標機 → 一次任務;mission-svc 擁生命週期狀態,
-- 由 fleet/+/mission/progress 更新(首個終態為準,冪等去重)。
-- waypoints 於建立時凍結(route 之後修改不影響已派任務)。
CREATE TABLE mission.mission (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id     text NOT NULL UNIQUE,
    route_id       uuid REFERENCES mission.route(id) ON DELETE SET NULL,
    drone_id       text NOT NULL,
    status         text NOT NULL DEFAULT 'created'
                   CHECK (status IN ('created', 'dispatched', 'received', 'uploaded',
                                     'in_progress', 'paused', 'completed', 'failed')),
    waypoints      jsonb NOT NULL,
    rtl_after_last boolean NOT NULL DEFAULT true,
    current_item   integer,
    total_items    integer,
    dispatched_at  timestamptz,
    finished_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mission.mission (drone_id, created_at DESC);
CREATE INDEX ON mission.mission (status);
