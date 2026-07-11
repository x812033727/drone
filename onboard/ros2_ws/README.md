# ros2_ws — ROS 2 工作空間(佔位,Phase 0 第二批)

> 規劃依據:[onboard/README.md](../README.md)、
> [docs/20-software/companion-computer.md](../../docs/20-software/companion-computer.md)

此目錄目前只有本說明檔。ROS 2 工作空間屬 Phase 0 **第二批**交付,
第一批(mission_exec + SITL 整合測試)刻意不引入 ROS 2,決策記錄見文末。

## 目標結構

對應 [onboard/README.md](../README.md) 規劃的五個 package:

```
ros2_ws/src/
├── obstacle_guard/     # 避障:減速/剎停(Phase 1)、繞行(Phase 2)
├── precision_land/     # 視覺標靶精準降落(AprilTag)
├── mission_exec/       # 任務狀態機(現雛形在 onboard/mission_exec,之後遷入或橋接)
├── stereo_depth/       # 雙目深度(CUDA SGM)
└── local_mapper/       # ESDF 佔據圖
```

環境基準:ROS 2 Humble(Ubuntu 22.04);目標機 Jetson Orin NX / JetPack 6,
Phase 0 於 x86 + SITL 開發,同一套 code。

## Phase 0 手動煙霧步驟(uXRCE-DDS 鏈路)

第二批動工前,先手動驗證 PX4 ↔ ROS 2 的 uXRCE-DDS 鏈路能通。
詳細環境安裝見 docs/50-project/phase0/sitl-setup.md §6(該檔於另一 PR 交付,
合入後由此連結:[../../docs/50-project/phase0/sitl-setup.md](../../docs/50-project/phase0/sitl-setup.md))。

1. **起 SITL**(PX4 1.15 SITL 內建 uXRCE-DDS client,開機即嘗試連 agent 的 UDP 8888):

   ```bash
   # --network host:容器內 client 連 127.0.0.1:8888 時直達 host 上的 agent
   docker run --rm -it --network host jonasvautherin/px4-gazebo-headless:1.15.4
   ```

2. **起 Micro XRCE-DDS Agent**(host 端):

   ```bash
   MicroXRCEAgent udp4 -p 8888
   ```

   看到 `session established` 類訊息即代表 PX4 client 已連上。

3. **裝 ROS 2 Humble + px4_msgs 後驗證 topic**:

   ```bash
   source /opt/ros/humble/setup.bash
   ros2 topic list | grep /fmu/          # 應看到 /fmu/out/* 一批 topic
   ros2 topic echo /fmu/out/vehicle_status
   ```

   `vehicle_status` 有資料流出 = uXRCE-DDS 鏈路全通,可開始建 package。

注意:與 MAVLink(mission_exec 走的 14540)不同,uXRCE-DDS 是容器內 client
**主動連出**到 agent 的 8888;上述用 `--network host` 是最省事的打通方式,
若沿用 bridge 網路則需讓 client 指向 docker gateway IP(image 需支援參數注入)。

## 為什麼 Phase 0 第一批不做 ROS 2(決策記錄)

- **退出條件已被 MAVSDK 覆蓋**:第一批的退出條件是「雲端任務 → 上傳 → 執行 →
  進度回報」全鏈路打通,mission_exec 走 MAVSDK/MAVLink 即可完成,
  不依賴任何 ROS 2 元件(見 [onboard/mission_exec/](../mission_exec/))。
- **環境成本延後付**:ROS 2 Humble + px4_msgs + uXRCE-DDS agent 的安裝與
  CI 環境建置成本不小,且第一批沒有消費者;等第二批的感知/避障 package
  (真正需要 DDS topic 的模組)動工時再付這筆成本。
- **不影響架構**:uXRCE-DDS 鏈路與 MAVLink 鏈路並行不互斥,PX4 端兩者同時可用;
  第一批的成果(任務檔格式、proto 契約、SITL CI)在第二批全數沿用。
