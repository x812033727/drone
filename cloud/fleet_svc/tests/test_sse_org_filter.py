"""SSE 即時遙測串流的多租戶隔離(G11b):非 admin 只收到本 org 裝置的遙測。"""

import asyncio
import json

from fleet_svc import main as m
from fleet_svc.auth import Principal
from fleet_svc.hub import TelemetryHub


class _Req:
    """假 Request:snapshot 送完後即回報斷線,讓串流迴圈立即結束。"""

    async def is_disconnected(self) -> bool:
        return True


def _principal(org: str, *, is_admin: bool = False) -> Principal:
    return Principal(
        claims={}, role="admin" if is_admin else "viewer", org=org, is_admin=is_admin
    )


def _collect(principal: Principal, allowed: set[str], hub: TelemetryHub) -> list[dict]:
    async def fake_org_serials(_org: str) -> set[str]:
        return allowed

    orig = m._org_serials
    m._org_serials = fake_org_serials  # type: ignore[assignment]
    try:

        async def run() -> list[dict]:
            out: list[dict] = []
            async for chunk in m._sse_events(_Req(), hub, principal):
                if chunk.startswith("data: "):
                    out.append(json.loads(chunk[len("data: ") :].strip()))
            return out

        return asyncio.run(run())
    finally:
        m._org_serials = orig  # type: ignore[assignment]


def _hub_with(*drone_ids: str) -> TelemetryHub:
    hub = TelemetryHub()
    for d in drone_ids:
        hub.publish({"drone_id": d, "battery_pct": 50})
    return hub


def test_non_admin_only_sees_own_org_devices():
    hub = _hub_with("A", "B", "C")
    got = _collect(_principal("acme"), {"A", "C"}, hub)
    ids = {d["drone_id"] for d in got}
    assert ids == {"A", "C"}  # B(他 org)不外洩


def test_admin_sees_all_devices():
    hub = _hub_with("A", "B", "C")
    # admin:allowed 不生效(is_admin=True → 內部 allowed=None)
    got = _collect(_principal("ops", is_admin=True), set(), hub)
    ids = {d["drone_id"] for d in got}
    assert ids == {"A", "B", "C"}


def test_unknown_drone_id_hidden_from_non_admin():
    hub = _hub_with("A", "UNKNOWN")
    got = _collect(_principal("acme"), {"A"}, hub)
    ids = {d["drone_id"] for d in got}
    assert ids == {"A"}  # 未映射到本 org 的 drone_id 一律不送(安全預設)
