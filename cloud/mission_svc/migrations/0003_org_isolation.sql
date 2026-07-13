-- 多租戶 org 隔離(G11,安全關鍵):把 org_id 從自由文字欄升為強制租戶邊界。
-- 每個 route/mission 綁定 org_id;查詢一律依呼叫者 org 過濾(WHERE org_id = claim)。
-- 只前向、冪等(migrate 以版本追蹤 + SQL 內 IF [NOT] EXISTS 雙保險);不 drop 客戶資料。
--
-- 既有列回填為 'default' 租戶;mission 優先繼承其來源 route 的 org,無 route 者歸 'default'。

-- ---- route:org_id 由 nullable → NOT NULL(預設 'default')----
UPDATE mission.route SET org_id = 'default' WHERE org_id IS NULL;
ALTER TABLE mission.route ALTER COLUMN org_id SET DEFAULT 'default';
ALTER TABLE mission.route ALTER COLUMN org_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS route_org_id_idx ON mission.route (org_id);

-- ---- mission:新增 org_id(建立時凍結呼叫者 org,與凍結航點同一時點)----
ALTER TABLE mission.mission ADD COLUMN IF NOT EXISTS org_id text;
-- 回填:有 route 者繼承 route.org_id,其餘 'default'
UPDATE mission.mission m
   SET org_id = COALESCE(r.org_id, 'default')
  FROM mission.route r
 WHERE m.route_id = r.id AND m.org_id IS NULL;
UPDATE mission.mission SET org_id = 'default' WHERE org_id IS NULL;
ALTER TABLE mission.mission ALTER COLUMN org_id SET DEFAULT 'default';
ALTER TABLE mission.mission ALTER COLUMN org_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS mission_org_id_idx ON mission.mission (org_id);
