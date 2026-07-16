"""fleet-svc / mission-svc REST 負載場景(locust)。

場景:
- ``FleetReadUser``(權重 3):viewer 讀路徑——/status 分頁、devices、fleets、alerts。
- ``DispatchUser``(權重 1):operator 全流程——route→mission→dispatch→進度輪詢。

配額 402 / 限流 429 是受測系統的**預期行為**,不計為失敗(另計 expected_4xx 統計)。

用法(對隔離棧;棧必須設 JWT_SECRET,見 mint_token.py 警語):
    JWT_SECRET=devsecret \
    FLEET_BASE=http://127.0.0.1:38091 MISSION_BASE=http://127.0.0.1:38092 \
    locust -f tools/loadgen/locustfile.py --headless -u 10 -r 2 -t 60s

前置:DispatchUser 需要 org 內有一台裝置——on_start 以 admin(org=loadtest)
token 建立(冪等:serial 撞名時查回)。
"""

from __future__ import annotations

import os
import uuid
from collections import Counter

from locust import HttpUser, between, events, task
from mint_token import mint  # tools/loadgen 同目錄(locust -f 時可 import)

FLEET_BASE = os.environ.get("FLEET_BASE", "http://127.0.0.1:38091")
MISSION_BASE = os.environ.get("MISSION_BASE", "http://127.0.0.1:38092")
ORG = os.environ.get("LOADGEN_ORG", "loadtest")

_SECRET = os.environ.get("JWT_SECRET")
if not _SECRET:
    raise SystemExit("需要 JWT_SECRET(與受測棧同值);dev 模式壓不到配額/限流/org 路徑")

EXPECTED_4XX: Counter = Counter()

# 派遣流程共用的測試機序號(DispatchUser.on_start 冪等建立)
DEVICE_SERIAL = os.environ.get("LOADGEN_DEVICE_SERIAL", "loadgen-drone-1")


def _hdr(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(_SECRET, role=role, org=ORG)}"}


def _note_expected(resp) -> bool:
    """402/429 為受測系統預期回應:標記成功並另計。回傳是否已處理。"""
    if resp.status_code in (402, 429):
        EXPECTED_4XX[resp.status_code] += 1
        resp.success()
        return True
    return False


@events.quitting.add_listener
def _report_expected(environment, **kw):
    if EXPECTED_4XX:
        print(f"[loadgen] 預期 4xx 統計(配額 402 / 限流 429):{dict(EXPECTED_4XX)}")


class FleetReadUser(HttpUser):
    """viewer 讀路徑。"""

    host = FLEET_BASE
    weight = 3
    wait_time = between(0.5, 2)

    def on_start(self):
        self.client.headers.update(_hdr("viewer"))

    @task(3)
    def status_page(self):
        with self.client.get(
            "/api/v1/status", params={"limit": 50, "offset": 0}, catch_response=True
        ) as resp:
            if not _note_expected(resp) and resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")

    @task(2)
    def devices(self):
        with self.client.get("/api/v1/devices", catch_response=True) as resp:
            if not _note_expected(resp) and resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")

    @task(1)
    def fleets(self):
        with self.client.get("/api/v1/fleets", catch_response=True) as resp:
            if not _note_expected(resp) and resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")

    @task(1)
    def alerts(self):
        with self.client.get("/api/v1/alerts", catch_response=True) as resp:
            if not _note_expected(resp) and resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")


class DispatchUser(HttpUser):
    """operator 全流程:route → mission → dispatch → 進度輪詢。

    mission-svc 端點以絕對 URL 呼叫(locust host 只能一個 base)。
    """

    host = FLEET_BASE
    weight = 1
    wait_time = between(1, 3)

    def on_start(self):
        self.op_headers = _hdr("operator")
        # 跨租戶防護要求 mission 的 drone_id 屬本 org:先以 admin(帶 org claim)
        # 冪等建立測試機。409/撞名視為已存在。
        admin = _hdr("admin")
        self.client.post(
            "/api/v1/devices",
            json={"serial": DEVICE_SERIAL, "model": "loadgen-sim"},
            headers=admin,
            name="/api/v1/devices [setup]",
        )

    @task
    def dispatch_flow(self):
        # 1) route
        with self.client.post(
            f"{MISSION_BASE}/api/v1/routes",
            json={
                "name": f"loadgen-{uuid.uuid4().hex[:8]}",
                "waypoints": [
                    {"lat_deg": 25.033, "lon_deg": 121.5654, "rel_alt_m": 30},
                    {"lat_deg": 25.034, "lon_deg": 121.5664, "rel_alt_m": 30},
                ],
            },
            headers=self.op_headers,
            catch_response=True,
            name="/api/v1/routes [create]",
        ) as resp:
            if _note_expected(resp):
                return
            if resp.status_code != 201:
                resp.failure(f"route create {resp.status_code}")
                return
            route_id = resp.json()["id"]

        # 2) mission
        with self.client.post(
            f"{MISSION_BASE}/api/v1/missions",
            json={"route_id": route_id, "drone_id": DEVICE_SERIAL},
            headers=self.op_headers,
            catch_response=True,
            name="/api/v1/missions [create]",
        ) as resp:
            if _note_expected(resp):
                return
            if resp.status_code != 201:
                resp.failure(f"mission create {resp.status_code}")
                return
            mission_pk = resp.json()["id"]

        # 3) dispatch(需 MQTT broker 在線;broker 掛掉時的行為由 chaos drill 驗)
        with self.client.post(
            f"{MISSION_BASE}/api/v1/missions/{mission_pk}/dispatch",
            headers=self.op_headers,
            catch_response=True,
            name="/api/v1/missions/{pk}/dispatch",
        ) as resp:
            if _note_expected(resp):
                return
            if resp.status_code != 200:
                resp.failure(f"dispatch {resp.status_code}")
                return

        # 4) 進度輪詢(一次;完整進度回收屬 e2e,不在負載場景重演)
        with self.client.get(
            f"{MISSION_BASE}/api/v1/missions/{mission_pk}",
            headers=self.op_headers,
            catch_response=True,
            name="/api/v1/missions/{pk} [poll]",
        ) as resp:
            if not _note_expected(resp) and resp.status_code != 200:
                resp.failure(f"poll {resp.status_code}")
