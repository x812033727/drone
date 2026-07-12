"""codec.py 純函式單元測試:PX4(duck-typed)訊息 → sensors proto 欄位映射、
四元數原樣搬運、fix_type 各分支與未知值 fallback。不需 ROS 2 / MQTT。"""

from types import SimpleNamespace

from px4_mqtt_bridge import codec


def test_attitude_proto_maps_fields_and_quaternion():
    msg = SimpleNamespace(timestamp=123456, q=[1.0, 0.0, 0.0, 0.0])
    out = codec.attitude_proto(msg, "dev-1", 1700000000000)
    assert out.drone_id == "dev-1"
    assert out.unix_time_ms == 1700000000000
    assert out.px4_timestamp_us == 123456
    # 四元數照原樣 Hamilton (w,x,y,z),4 元素
    assert list(out.q) == [1.0, 0.0, 0.0, 0.0]


def test_attitude_proto_preserves_full_quaternion():
    msg = SimpleNamespace(timestamp=1, q=[0.5, 0.5, -0.5, 0.5])
    out = codec.attitude_proto(msg, "d", 2)
    assert len(out.q) == 4
    assert list(out.q) == [0.5, 0.5, -0.5, 0.5]


def _gps_msg(fix_type: int) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=999,
        latitude_deg=25.0,
        longitude_deg=121.5,
        altitude_msl_m=30.0,
        satellites_used=12,
        hdop=0.8,
        vdop=1.1,
        fix_type=fix_type,
    )


def test_gps_proto_maps_fields():
    out = codec.gps_proto(_gps_msg(3), "dev-1", 1700000000001)
    assert out.drone_id == "dev-1"
    assert out.px4_timestamp_us == 999
    assert abs(out.latitude_deg - 25.0) < 1e-9
    assert abs(out.longitude_deg - 121.5) < 1e-9
    assert abs(out.altitude_msl_m - 30.0) < 1e-9
    assert out.satellites_used == 12
    assert out.fix_type == "FIX_TYPE_3D"


def test_fix_type_all_known_values():
    expected = {
        0: "FIX_TYPE_NONE",
        1: "FIX_TYPE_NONE",
        2: "FIX_TYPE_2D",
        3: "FIX_TYPE_3D",
        4: "FIX_TYPE_RTCM_CODE_DIFFERENTIAL",
        5: "FIX_TYPE_RTK_FLOAT",
        6: "FIX_TYPE_RTK_FIXED",
        8: "FIX_TYPE_EXTRAPOLATED",
    }
    for n, name in expected.items():
        assert codec.fix_type_name(n) == name
        assert codec.gps_proto(_gps_msg(n), "d", 0).fix_type == name


def test_fix_type_unknown_falls_back_without_losing_value():
    # 未知/新增的 fix_type 不丟資訊,回退 FIX_TYPE_<n>
    assert codec.fix_type_name(7) == "FIX_TYPE_7"
    assert codec.fix_type_name(99) == "FIX_TYPE_99"
    assert codec.gps_proto(_gps_msg(7), "d", 0).fix_type == "FIX_TYPE_7"


def test_local_position_proto_maps_fields():
    msg = SimpleNamespace(
        timestamp=555,
        x=1.0,
        y=2.0,
        z=-3.0,
        vx=0.1,
        vy=-0.2,
        vz=0.3,
        heading=1.57,
    )
    out = codec.local_position_proto(msg, "dev-1", 1700000000002)
    assert out.px4_timestamp_us == 555
    assert abs(out.x - 1.0) < 1e-6
    assert abs(out.z + 3.0) < 1e-6
    assert abs(out.vy + 0.2) < 1e-6
    assert abs(out.heading - 1.57) < 1e-6
