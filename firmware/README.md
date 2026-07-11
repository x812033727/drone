# firmware — 飛控韌體(PX4 客製)

> 規劃依據:[docs/20-software/firmware.md](../docs/20-software/firmware.md)

## 結構(規劃)

```
firmware/
├── px4/                # PX4 fork(git submodule,鎖定 stable tag)
├── boards/fc-h7/       # 自研板 FC-H7 板級支援(rev A 啟動後從 px4_fmu-v6x fork)
├── airframes/          # PA-1 / PB-1 機型參數包(版本化,與韌體版綁定)
└── patches/            # 對 upstream 的自訂 patch(控制在 20 個 commit 內)
```

## Phase 0 快速開始(SITL)

自研板尚未存在,Phase 0 直接用 upstream PX4 + Gazebo 模擬:

```bash
git clone --recursive -b v1.15.4 https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
make px4_sitl gz_x500        # x500 模型即 Phase 0 開發機構型
```

SITL 啟動後預設在 `udp:14540` 提供 MAVLink(offboard 埠),可用本 repo 的
[`tools/telemetry_monitor.py`](../tools/telemetry_monitor.py) 驗證連線。
完整環境建置、失效保護場景注入與疑難排解見
[docs/50-project/phase0/sitl-setup.md](../docs/50-project/phase0/sitl-setup.md)。

## 開發原則

- 只在 `boards/`、`airframes/`、`patches/` 增量;不直接改 upstream 核心(EKF2/控制器)
- 每 6–12 個月 rebase 一次 upstream stable
- 失效保護場景(失聯/低電/GPS 拒止/GeoFence)全部寫成 SITL 回歸腳本,進 CI
