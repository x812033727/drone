"""drone-agent:機載常駐服務(Phase 0 雛形)。

純 MAVSDK(不經 ROS 2)讀取 PX4 遙測,彙整為 `drone.v1.TelemetrySummary`,
以 1 Hz 經 MQTT 上報雲端。契約見 interfaces/proto/drone/v1/telemetry.proto。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
