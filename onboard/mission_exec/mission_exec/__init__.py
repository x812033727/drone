"""mission_exec — 機載任務執行器(Phase 0 雛形)。

接收 JSON 任務檔(= drone.v1.MissionPlan 的 proto3 JSON),
經 MAVSDK 上傳至 PX4 並執行,過程發布 drone.v1.MissionProgress 進度事件。
"""

__version__ = "0.1.0"
