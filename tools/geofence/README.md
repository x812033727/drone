# tools/geofence — 禁航區 GeoJSON → PX4 圍欄轉換器

firmware.md §2「GeoFence 禁航區」客製項的工具面(純 Python,走主 CI)。

```bash
# 禁航區 GeoJSON → MISSION_TYPE_FENCE 項目序列(F8 的 pymavlink 上傳用)
python tools/geofence/geofence.py zones.geojson --format fence-json -o fence.json

# → QGC .plan 的 geoFence 區塊(操作人可視化)
python tools/geofence/geofence.py zones.geojson --format qgc-geofence

# 超出容量口徑(32 多邊形/128 頂點)→ exit 1;--simplify 壓頂點後重驗
python tools/geofence/geofence.py zones.geojson --simplify 1e-5
```
