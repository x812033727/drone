# 50-4-4 SITL 環境建置指南

> rev 1 · 2026-07。[firmware/README.md](../../../firmware/README.md) 的 4 行快速開始之完整版:安裝、與實機差異、失效保護場景注入、疑難排解。Phase 0 規則:**任務與失效保護類架次先在 SITL 過一遍才排實機**(對 flight-test-plan.md 的 F05–F12,該檔屬 D2 批次)。

## 1. 環境需求

- Ubuntu 22.04(x86_64)原生為準;WSL2 可用但 Gazebo GUI 效能差、埠轉發需自理,只建議跑 `HEADLESS=1`
- 建議規格:4 核以上 CPU、16 GB RAM、獨顯非必要(headless 不需要)
- Python 3.10(系統預設)、git、能連 GitHub

## 2. 安裝 PX4 v1.15.4 + Gazebo

```bash
git clone --recursive -b v1.15.4 https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
bash ./Tools/setup/ubuntu.sh        # 安裝工具鏈與模擬器依賴(含 gz)
# 重開 shell 後:
make px4_sitl gz_x500               # 首次編譯 10–30 min(裝 ccache 可大幅加速二次編譯)
```

成功標準:Gazebo 視窗出現 x500 機體(headless 則看終端),pxh shell 出現 `Ready for takeoff!`。

常見安裝錯誤:

| 症狀 | 處置 |
|------|------|
| submodule 缺件、編譯報找不到目標 | `make submodulesclean` 或重新 `git submodule update --init --recursive` |
| gz 版本衝突(裝過 ros-gz/ignition) | PX4 v1.15 配 **Gazebo Harmonic**;清掉舊版 `ignition-*`/`gz-garden` 套件後重跑 ubuntu.sh |
| `gz_x500` 啟動卡在等待模擬器 | 先 `gz sim -v4` 單獨確認 gz 可啟動;顯卡驅動問題改 `HEADLESS=1` |
| 編譯 OOM | `make -j2 px4_sitl gz_x500` 限制平行度 |

## 3. gz_x500 模型 vs. 開發機(X500 V2 實機)

gz_x500 的質量、慣量、動力參數與實機**不同**,且無 RTK/數傳/4G 模型。結論:**SITL 用來驗證任務邏輯與失效保護行為,不用來調參**——PID/濾波參數以實機台架與試飛為準(見 build-and-first-flight.md,D2 批次)。

## 4. 連線驗證

- QGC:啟動即自動連上(SITL 對 GCS 埠 **udp:14550** 廣播)
- 本 repo 工具(offboard API 埠 **udp:14540**):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r tools/requirements.txt
python tools/telemetry_monitor.py        # 預設連 udp:14540,應看到模式/電池/位置流
```

- 起飛煙霧測試(pxh shell):`commander takeoff`,升至預設高度後 `commander land`

## 5. 失效保護場景注入(對 F09–F12)

PX4 的 `failure` 注入命令需先開參數 **`SYS_FAILURE_EN=1`**(僅模擬器接受;實機禁用)。在 pxh shell:

| 場景 | 注入方法 | 預期行為(參數基線見 build-and-first-flight.md §3) |
|------|----------|------|
| RC 失聯 | `failure rc off`(恢復 `failure rc ok`) | `COM_RC_LOSS_T` 後觸發 `NAV_RCL_ACT=2` → RTL |
| GPS 劣化/失效 | `failure gps off` | EKF 告警、依定位品質觸發降級(Hold/RTL/降落) |
| 低電量分級 | `param set SIM_BAT_DRAIN 60`(60 s 內放完,依序穿越三門檻) | Low 警告 → Critical RTL → Emergency 降落 |
| GeoFence | QGC 畫 200 m 圍欄上傳,任務故意放界外航點 | 到界觸發 `GF_ACTION` 不穿越 |
| 馬達失效(僅研究用) | `failure motor1 off` | 四軸不可控——驗證的是「會發生什麼」,非通過項 |

腳本:`tools/sitl_scenarios`(F09–F12 可重跑場景 + nightly CI `failsafe-scenarios` job;注入法與本表寫法的實測差異見該目錄 README)。

每個場景跑完用 `tools/ulog_report.py` 讀 SITL log(路徑 `build/px4_sitl_default/rootfs/log/<date>/`)確認觸發時間軸與行為。場景腳本(shell 串 pxh 命令)隨任務檔一起版控,實機架次引用同名場景。

## 6. uXRCE-DDS 煙霧測試(簡版)

SITL 內建 `uxrce_dds_client`(自動連 localhost:8888)。只需另開終端:

```bash
sudo snap install micro-xrce-dds-agent --edge   # 或依官方以 binary/原始碼安裝
MicroXRCEAgent udp4 -p 8888                     # 看到 client 連入即通
```

有 ROS 2 Humble 環境者可再 `ros2 topic echo /fmu/out/vehicle_status` 驗證資料流;容器化的一鍵自動煙霧(host 免裝 ROS)見 [onboard/ros2_ws/](../../../onboard/ros2_ws/) 的 `run_smoke.sh`。

⚠️ 本節適用**原生自建** SITL(§2 流程,現代 cmake 會編入 client)。docker 的 `jonasvautherin/px4-gazebo-headless:1.15.4` **不含 uxrce_dds_client**(舊基底 cmake 3.10 令 PX4 靜默跳過該模組,2026-07 實測),對它跑本節必失敗——容器化煙霧請走 ros2_ws 自建的 SITL image。

## 7. FAQ

- **埠速查**:14550=GCS(QGC)、14540=offboard API(MAVSDK/本 repo 工具)、8888=uXRCE-DDS agent
- **多機模擬**:`PX4_SYS_AUTOSTART=4001 PX4_SIM_MODEL=gz_x500 ./build/px4_sitl_default/bin/px4 -i 1` 起第二實例(埠自動 +1:14541/14551…),雙機流程(F16)可先在此排演
- **headless**:`HEADLESS=1 make px4_sitl gz_x500`(CI 與遠端開發用)
- **模擬加速**:`PX4_SIM_SPEED_FACTOR=4` 供回歸腳本縮時;人工操作驗證用 1×
- **DDS domain 打架**:多人同網段開 SITL 時設 `ROS_DOMAIN_ID` 區隔
- **log 太多**:SITL log 會快速累積,定期清 `build/px4_sitl_default/rootfs/log/`
