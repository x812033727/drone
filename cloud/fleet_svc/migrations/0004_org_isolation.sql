-- 多租戶 org 隔離(G11,安全關鍵):把 org_id 從自由文字欄升為強制租戶邊界。
-- 每個 fleet/device 綁定 org_id;查詢一律依呼叫者 org 過濾(WHERE org_id = claim)。
-- 只前向、冪等(migrate 以版本追蹤 + SQL 內 IF [NOT] EXISTS 雙保險);不 drop 客戶資料。
--
-- 既有列回填為 'default' 租戶(升級前建立的資料歸屬預設 org);device 優先繼承其
-- 所屬 fleet 的 org,無 fleet 者歸 'default'。firmware 目錄為平台共用、非租戶資料,不加 org。

-- ---- fleet:org_id 由 nullable → NOT NULL(預設 'default')----
UPDATE fleet.fleet SET org_id = 'default' WHERE org_id IS NULL;
ALTER TABLE fleet.fleet ALTER COLUMN org_id SET DEFAULT 'default';
ALTER TABLE fleet.fleet ALTER COLUMN org_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS fleet_org_id_idx ON fleet.fleet (org_id);

-- ---- device:新增 org_id(裝置可無 fleet,故自帶租戶欄,不靠 fleet join)----
ALTER TABLE fleet.device ADD COLUMN IF NOT EXISTS org_id text;
-- 回填:有 fleet 者繼承 fleet.org_id,其餘 'default'
UPDATE fleet.device d
   SET org_id = COALESCE(f.org_id, 'default')
  FROM fleet.fleet f
 WHERE d.fleet_id = f.id AND d.org_id IS NULL;
UPDATE fleet.device SET org_id = 'default' WHERE org_id IS NULL;
ALTER TABLE fleet.device ALTER COLUMN org_id SET DEFAULT 'default';
ALTER TABLE fleet.device ALTER COLUMN org_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS device_org_id_idx ON fleet.device (org_id);
