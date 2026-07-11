# ros2_ws — ROS 2 工作空間(Phase 0 第二批)

> 規劃依據:[onboard/README.md](../README.md)、
> [docs/20-software/companion-computer.md](../../docs/20-software/companion-computer.md)

Phase 0 第二批 S8 交付:**容器化 ROS 2 環境 + PX4 uXRCE-DDS 橋接煙霧(SITL 實測通過)**。
host 不需安裝 ROS——開發與驗證全在 docker 內。Phase 1 功能 package
(obstacle_guard 等)刻意不在此批,見文末決策記錄。

## 現有內容

```
ros2_ws/
├── docker/
│   ├── Dockerfile              # ros:humble + Micro XRCE-DDS Agent(source)+ px4_msgs(release/1.15)
│   ├── Dockerfile.px4-sitl-dds # 自建 PX4 v1.15.4 SITL(SIH 免 Gazebo,含 uxrce_dds_client)
│   └── entrypoint.sh           # source ROS 2 與 workspace
├── src/
│   └── bridge_smoke/           # 最小煙霧 package:訂 /fmu/out/* 收滿 N 筆判 PASS
└── run_smoke.sh                # 一鍵煙霧(SITL + agent + listener,自動清理)
```

### 版本鎖定(勿隨意升)

| 元件 | 版本 | 理由 |
|------|------|------|
| base image | `ros:humble`(ros-base) | 目標機 Jetson/JetPack 6 = Ubuntu 22.04 + Humble;desktop 版多 2GB+ GUI 件用不到 |
| px4_msgs | `release/1.15` 分支 | **訊息定義必須與韌體一致**(SITL/實機皆 PX4 1.15.x),不一致會序列化錯位、topic 收不到或亂值 |
| Micro XRCE-DDS Agent | `v2.4.3`(source build) | apt 的 ROS 源無 ros-humble-micro-xrce-dds-agent(2026-07 實測),snap 容器內不可用;PX4 1.15 走 XRCE-DDS 2.x 協定 → 取最新 v2.x。⚠️ PX4 文件舊建議 v2.4.2 已 build 不過(superbuild 釘的 fastdds 2.12.x 分支被上游刪除,實測) |
| SITL(DDS 煙霧用) | 自建 [`Dockerfile.px4-sitl-dds`](docker/Dockerfile.px4-sitl-dds)(PX4 v1.15.4 + SIH) | ⚠️ `jonasvautherin/px4-gazebo-headless:1.15.4` **不含 uxrce_dds_client**:其基底 Ubuntu 18.04 的 cmake 3.10 使 PX4 build 靜默跳過該模組(2026-07 以 `strings px4` 實測確認,rcS 的 "if module exists" 靜默略過、無任何錯誤);1.16+ 現成 image 才有,但韌體版本與專案(1.15.4)不一致 → 自建。MAVLink 類 SITL job 不受影響,照用 gazebo-headless |

## 煙霧測試(自動化)

```bash
./run_smoke.sh
```

流程:build 兩顆 image(首次各約 10 分,之後有 docker 快取)→ 起 ROS 2 容器
(`--network host`,agent 於 UDP 8888 待命)→ 起自建 PX4 SITL(SIH 免
Gazebo;uxrce_dds_client 自動連 127.0.0.1:8888)→ 輪詢 px4 進程就緒 →
容器內跑 listener 收滿 10 筆 `/fmu/out/vehicle_status` 判 PASS → 清理全部
容器。UDP 8888/14550 被占會直接報錯退出。可調:`SMOKE_COUNT`、
`SMOKE_TIMEOUT`、`SITL_UP_TIMEOUT` 環境變數。

手動逐步驗證(原生環境、不走 docker)見
[docs/50-project/phase0/sitl-setup.md §6](../../docs/50-project/phase0/sitl-setup.md)。

CI:已納入 [.github/workflows/sitl-integration.yml](../../.github/workflows/sitl-integration.yml)
`uxrce-dds-smoke` job(nightly,直接跑 `run_smoke.sh`,與本地同一條路徑)。

### QoS 注意(踩過再看一次)

PX4 uxrce_dds_client 發佈端是 **BestEffort / TransientLocal**;訂閱端若用
rclpy 預設(Reliable)會**一筆都收不到**且無錯誤訊息。所有訂 `/fmu/out/*`
的 node 一律照 [bridge_smoke/listener.py](src/bridge_smoke/bridge_smoke/listener.py)
的 `PX4_QOS` 寫。

## 目標結構(Phase 1+)

對應 [onboard/README.md](../README.md) 規劃的五個 package:

```
ros2_ws/src/
├── bridge_smoke/       # ✅ Phase 0:uXRCE-DDS 鏈路煙霧(本批交付)
├── obstacle_guard/     # 避障:減速/剎停(Phase 1)、繞行(Phase 2)
├── precision_land/     # 視覺標靶精準降落(AprilTag)
├── mission_exec/       # 任務狀態機(現雛形在 onboard/mission_exec,之後遷入或橋接)
├── stereo_depth/       # 雙目深度(CUDA SGM)
└── local_mapper/       # ESDF 佔據圖
```

環境基準:ROS 2 Humble(Ubuntu 22.04);目標機 Jetson Orin NX / JetPack 6,
Phase 0 於 x86 + SITL 開發,同一套 code。Jetson 到貨後同一 Dockerfile
(base 換 arm64 的 ros:humble,多架構 tag 本就支援)直接沿用。

## 為什麼 Phase 0 第一批不做 ROS 2(決策記錄)

- **退出條件已被 MAVSDK 覆蓋**:第一批的退出條件是「雲端任務 → 上傳 → 執行 →
  進度回報」全鏈路打通,mission_exec 走 MAVSDK/MAVLink 即可完成,
  不依賴任何 ROS 2 元件(見 [onboard/mission_exec/](../mission_exec/))。
- **環境成本延後付**:ROS 2 Humble + px4_msgs + uXRCE-DDS agent 的安裝與
  CI 環境建置成本不小,且第一批沒有消費者;此成本已於第二批(本批)付清——
  容器化後 host 零安裝。
- **不影響架構**:uXRCE-DDS 鏈路與 MAVLink 鏈路並行不互斥,PX4 端兩者同時可用;
  第一批的成果(任務檔格式、proto 契約、SITL CI)在第二批全數沿用。

## 為什麼 bridge_smoke build 進 image 而非掛載編譯(決策記錄)

煙霧的目標是**可重現的一鍵驗證**:單一 image 自帶全部產物,本機與 CI
行為一致,無 host 路徑/UID 問題。px4_msgs 單獨一層(編譯最慢),
之後迭代自家 package 不會觸發重編。開發迭代時仍可掛載 `src/` 進容器
`colcon build`,兩者不互斥。
