# tools — Phase 0 開發工具

| 工具 | 用途 |
|------|------|
| `telemetry_monitor.py` | 連上 PX4(SITL/實機)即時列印模式、電池、位置、健康狀態——鏈路煙霧測試 |
| `ulog_report.py` | 飛行後 ULog 摘要與異常規則(振動、電壓、GPS 品質)——log-svc 的雛形 |
| `dispatch_mission.py` | 雲端側任務派遣:發 MissionPlan 到 `fleet/{id}/cmd/mission`,`--wait` 訂 progress 等到 COMPLETED/FAILED——mission-svc 的雛形(需 `pip install -e ../interfaces/proto/gen/python`;Phase 0 內網豁免見 [security.md §8](../docs/20-software/security.md)) |
| `sitl_scenarios/` | 失效保護 SITL 場景回歸(F09–F12,注入 + 斷言;用法見其 README) |
| `flight_ops/` | 執飛工具包:參數表 v1 批次寫入/核對(`--dry-run` 飛行日核對)+ 飛行後 ULog 歸檔與架次紀錄底稿(用法見其 README) |

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 先啟動 PX4 SITL(見 ../firmware/README.md),再:
python telemetry_monitor.py

# 飛行(或 SITL)結束後:
python ulog_report.py ~/PX4-Autopilot/build/px4_sitl_default/rootfs/log/<date>/<time>.ulg
```
