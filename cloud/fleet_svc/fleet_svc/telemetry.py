"""遙測 payload(proto3 JSON)→ dict 的純函式,供消費者 upsert + SSE 共用。

沿用 cloud/ingest/decode 的 wire 慣例:proto3 JSON,int64 為字串,用 json_format.Parse。
"""

from __future__ import annotations

from typing import Any

from drone.v1 import telemetry_pb2
from google.protobuf import json_format


def parse_telemetry(payload: bytes | str) -> dict[str, Any]:
    """fleet/{id}/telemetry 的 JSON payload → 扁平 dict(給 device_state 與 SSE 用)。"""
    msg = json_format.Parse(payload, telemetry_pb2.TelemetrySummary())
    return {
        "drone_id": msg.drone_id,
        "unix_time_ms": msg.unix_time_ms,
        "lat_deg": msg.lat_deg,
        "lon_deg": msg.lon_deg,
        "rel_alt_m": msg.rel_alt_m,
        "heading_deg": msg.heading_deg,
        "ground_speed_ms": msg.ground_speed_ms,
        "flight_mode": msg.flight_mode,
        "armed": msg.armed,
        "battery_v": msg.battery_v,
        "battery_pct": msg.battery_pct,
        "health_all_ok": msg.health_all_ok,
    }
