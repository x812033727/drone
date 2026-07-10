# onboard — 機載電腦軟體(Jetson / ROS 2)

> 規劃依據:[docs/20-software/companion-computer.md](../docs/20-software/companion-computer.md)

## 結構(規劃)

```
onboard/
├── ros2_ws/src/
│   ├── obstacle_guard/     # 避障:減速/剎停(Phase 1)、繞行(Phase 2)
│   ├── precision_land/     # 視覺標靶精準降落(AprilTag)
│   ├── mission_exec/       # 任務狀態機(雲端任務 → MAVLink 轉譯、續飛)
│   ├── stereo_depth/       # 雙目深度(CUDA SGM)
│   └── local_mapper/       # ESDF 佔據圖
├── drone-agent/            # 非 ROS 常駐服務:MQTT 遙測上雲、gRPC 指令、WebRTC、OTA
└── video-pipeline/         # GStreamer/DeepStream:錄影 + 串流 + 推論分支
```

## 環境基準

- Jetson Orin NX / JetPack 6(Ubuntu 22.04)+ ROS 2 Humble
- 與 PX4 通訊:uXRCE-DDS(Ethernet);Phase 0 於 x86 + SITL 開發,同一套 code
- 安全邊界:感知模組只對 PX4 發**速度限制與 setpoint 修正**,絕不發姿態級指令;
  任一 node 崩潰 → obstacle_guard 進入保守限速模式,不影響飛行

## Phase 0 待辦

- [ ] ros2_ws 建立 + px4_ros_com bridge 跑通(SITL)
- [ ] mission_exec 雛形:接收 JSON 任務 → 上傳 MAVLink mission → 進度回報
- [ ] drone-agent 雛形:MQTT 連雲、遙測摘要 1 Hz 上報
