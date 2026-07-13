"""PX4 訊息 → drone.v1 sensors proto 的純建構子(不依賴 rclpy / px4_msgs)。

從 bridge.py 抽出,讓這層邏輯能在一般 pytest 環境(無 ROS 2)單測:
- 只 import drone.v1(CI 有裝 drone-proto),不 import rclpy / px4_msgs / paho。
- 建構子吃 **duck-typed** 訊息物件(只讀取所需屬性,如 msg.q、msg.timestamp、
  msg.latitude_deg…),不綁定具體 ROS 型別;測試可用 SimpleNamespace 假訊息。

契約見 interfaces/proto/drone/v1/sensors.proto。四元數照 PX4 原樣(Hamilton
w/x/y/z),契約不做有損轉換;px4_timestamp_us 為 PX4 boot-time 微秒(非 epoch),
原樣保留另欄,Phase 1 時鐘對齊前勿與 wall clock 混算。
"""

from drone.v1 import sensors_pb2

# PX4 SensorGps.fix_type(uint8)→ 契約字串。
# 值對 px4_msgs/SensorGps 常數(v1.15):0/1 皆 no fix、2=2D、3=3D、
# 4=RTCM code differential、5=RTK float、6=RTK fixed、8=extrapolated。
# 以整數為鍵(不 import px4_msgs 常數),與 bridge 執行期行為一致。
_FIX_TYPE_NAMES = {
    0: "FIX_TYPE_NONE",
    1: "FIX_TYPE_NONE",
    2: "FIX_TYPE_2D",
    3: "FIX_TYPE_3D",
    4: "FIX_TYPE_RTCM_CODE_DIFFERENTIAL",
    5: "FIX_TYPE_RTK_FLOAT",
    6: "FIX_TYPE_RTK_FIXED",
    8: "FIX_TYPE_EXTRAPOLATED",
}


def fix_type_name(fix_type: int) -> str:
    """fix_type 整數 → 契約字串;未知值回退 FIX_TYPE_<n>(不丟資訊)。"""
    n = int(fix_type)
    return _FIX_TYPE_NAMES.get(n, f"FIX_TYPE_{n}")


def attitude_proto(msg, drone_id: str, wall_ms: int):
    """VehicleAttitude → SensorAttitude(四元數照原樣 Hamilton w/x/y/z)。"""
    out = sensors_pb2.SensorAttitude(
        drone_id=drone_id,
        unix_time_ms=wall_ms,
        px4_timestamp_us=int(msg.timestamp),
    )
    out.q.extend(float(v) for v in msg.q)
    return out


def gps_proto(msg, drone_id: str, wall_ms: int):
    """SensorGps → SensorGps(fix_type 轉契約字串)。"""
    return sensors_pb2.SensorGps(
        drone_id=drone_id,
        unix_time_ms=wall_ms,
        px4_timestamp_us=int(msg.timestamp),
        latitude_deg=float(msg.latitude_deg),
        longitude_deg=float(msg.longitude_deg),
        altitude_msl_m=float(msg.altitude_msl_m),
        satellites_used=int(msg.satellites_used),
        hdop=float(msg.hdop),
        vdop=float(msg.vdop),
        fix_type=fix_type_name(msg.fix_type),
    )


def local_position_proto(msg, drone_id: str, wall_ms: int):
    """VehicleLocalPosition → SensorLocalPosition。"""
    return sensors_pb2.SensorLocalPosition(
        drone_id=drone_id,
        unix_time_ms=wall_ms,
        px4_timestamp_us=int(msg.timestamp),
        x=float(msg.x),
        y=float(msg.y),
        z=float(msg.z),
        vx=float(msg.vx),
        vy=float(msg.vy),
        vz=float(msg.vz),
        heading=float(msg.heading),
    )
