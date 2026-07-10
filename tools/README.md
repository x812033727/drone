# tools — Phase 0 開發工具

| 工具 | 用途 |
|------|------|
| `telemetry_monitor.py` | 連上 PX4(SITL/實機)即時列印模式、電池、位置、健康狀態——鏈路煙霧測試 |
| `ulog_report.py` | 飛行後 ULog 摘要與異常規則(振動、電壓、GPS 品質)——log-svc 的雛形 |

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 先啟動 PX4 SITL(見 ../firmware/README.md),再:
python telemetry_monitor.py

# 飛行(或 SITL)結束後:
python ulog_report.py ~/PX4-Autopilot/build/px4_sitl_default/rootfs/log/<date>/<time>.ulg
```
