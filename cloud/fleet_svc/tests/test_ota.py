"""OTA 觸發(雲端發起端):payload 組裝對齊 ota.py + 端點多租戶 + 發布接線。

1. build_ota_command_json:欄位嚴格對齊 onboard ota.py parse_ota_command
   (install 全欄位 / 控制指令只 action+update_id / rollback 帶 component)。
2. round-trip:把組出的 JSON 餵給 ota.py parse_ota_command,證明機上可解析(對齊硬證)。
3. 模型驗證:install 缺欄位 / sha256 格式錯 → 422(ValidationError)。
4. 端點:POST /devices/{id}/ota 發布 cmd/ota;跨 org 回 404 且不發布(多租戶)。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from fleet_svc import auth, main
from fleet_svc.models import Component, DeviceOtaRequest, OtaAction
from fleet_svc.ota import build_ota_command_json
from pydantic import ValidationError

SHA = "a" * 64


def _install_req(**kw) -> DeviceOtaRequest:
    base = dict(
        action=OtaAction.install,
        update_id="ota-1",
        component=Component.onboard,
        version="1.4.0",
        url="https://mirror.example/onboard-1.4.0.tar.gz",
        sha256=SHA,
        signature="c2ln",  # base64
    )
    base.update(kw)
    return DeviceOtaRequest(**base)


# ---- 1. builder 欄位對齊 ----
def test_build_install_has_all_ota_fields():
    payload = json.loads(build_ota_command_json(_install_req(size=123)))
    assert payload["action"] == "install"
    assert payload["update_id"] == "ota-1"
    assert payload["component"] == "onboard"
    assert payload["version"] == "1.4.0"
    assert payload["url"].endswith(".tar.gz")
    assert payload["sha256"] == SHA
    assert payload["signature"] == "c2ln"
    assert payload["size"] == 123


def test_build_install_omits_size_when_absent():
    payload = json.loads(build_ota_command_json(_install_req()))
    assert "size" not in payload  # size 選填,未給不帶(對齊 ota.py 選填語意)


def test_build_control_command_minimal():
    for action in ("pause", "resume"):
        payload = json.loads(
            build_ota_command_json(DeviceOtaRequest(action=OtaAction(action), update_id="u9"))
        )
        assert payload == {"action": action, "update_id": "u9"}


def test_build_rollback_carries_component():
    payload = json.loads(
        build_ota_command_json(
            DeviceOtaRequest(action=OtaAction.rollback, update_id="u9", component=Component.onboard)
        )
    )
    assert payload == {"action": "rollback", "update_id": "u9", "component": "onboard"}


def test_sha256_uppercase_normalized_to_lower():
    payload = json.loads(build_ota_command_json(_install_req(sha256="A" * 64)))
    assert payload["sha256"] == "a" * 64


# ---- 2. round-trip 對齊硬證:機上 ota.py 能解析組出的 payload ----
def test_roundtrip_parses_in_onboard_ota():
    # 把 onboard/drone_agent 加入 path 後 import parse_ota_command(依賴 aiomqtt/cryptography,
    # fleet_svc 環境皆具備);缺依賴則跳過(scoped 環境保險)。
    onboard = Path(__file__).resolve().parents[3] / "onboard" / "drone_agent"
    sys.path.insert(0, str(onboard))
    parse = pytest.importorskip("drone_agent.ota").parse_ota_command
    cmd = parse(build_ota_command_json(_install_req(size=999)))
    assert cmd.action == "install"
    assert cmd.update_id == "ota-1"
    assert cmd.component == "onboard"
    assert cmd.version == "1.4.0"
    assert cmd.sha256 == SHA
    assert cmd.signature == "c2ln"
    assert cmd.size == 999
    # 控制指令亦可解析
    ctrl = parse(
        build_ota_command_json(DeviceOtaRequest(action=OtaAction.rollback, update_id="u9"))
    )
    assert ctrl.action == "rollback" and ctrl.update_id == "u9"


# ---- 3. 模型驗證 ----
def test_install_missing_fields_rejected():
    with pytest.raises(ValidationError):
        DeviceOtaRequest(action=OtaAction.install, update_id="u1")  # 缺套件欄位


def test_bad_sha256_rejected():
    with pytest.raises(ValidationError):
        _install_req(sha256="xyz")  # 非 64-hex


# ---- 4. 端點層 ----
def _device_row(org: str):
    return {
        "id": uuid4(), "serial": "SN-1", "name": None, "fleet_id": None, "org_id": org,
        "model": None, "status": "active", "cert_fingerprint": None,
        "cert_not_after": None, "created_at": datetime.now(timezone.utc),
    }


class _MemConn:
    def __init__(self, device: dict | None) -> None:
        self.device = device

    async def fetchval(self, sql, *args):
        # DB-backed 限流原子遞增:回小計數(遠低於預設 6000/分上限)→ 不誤觸 429。
        if "rate_limit_counter" in sql:
            return 1
        return 0

    async def fetchrow(self, sql, *args):
        if "FROM fleet.org" in sql:
            return None  # org 未註冊 → _guard_write 放行
        if "FROM fleet.device WHERE id = $1" in sql:
            if self.device is None or self.device["id"] != args[0]:
                return None
            if "org_id = $2" in sql and self.device["org_id"] != args[1]:
                return None
            return self.device
        return None

    async def execute(self, sql, *args):
        return "INSERT 0 1"


class _MemPool:
    def __init__(self, conn: _MemConn) -> None:
        self._conn = conn

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *a):
                return False

        return _Acq()


SECRET = "test-secret-key-ota-endpoint-0123456789"


@pytest.fixture
def published(monkeypatch):
    calls: list[tuple] = []

    async def _fake(host, port, serial, cmd_json):
        calls.append((host, port, serial, cmd_json))

    monkeypatch.setattr(main.ota, "publish_ota_command", _fake)
    return calls


def _body() -> dict:
    return {
        "action": "install", "update_id": "ota-1", "component": "onboard",
        "version": "1.4.0", "url": "https://m/onboard-1.4.0.tgz",
        "sha256": SHA, "signature": "c2ln",
    }


def test_ota_endpoint_dev_mode_publishes(monkeypatch, published):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)  # dev = admin
    dev = _device_row("orgA")
    main.app.state.pool = _MemPool(_MemConn(dev))
    c = TestClient(main.app)
    r = c.post(f"/api/v1/devices/{dev['id']}/ota", json=_body())
    assert r.status_code == 200
    out = r.json()
    assert out["serial"] == "SN-1"
    assert out["topic"] == "fleet/SN-1/cmd/ota"
    assert out["update_id"] == "ota-1"
    # 已發布,且 payload 對齊 cmd/ota
    assert len(published) == 1
    _, _, serial, cmd_json = published[0]
    assert serial == "SN-1"
    assert json.loads(cmd_json)["sha256"] == SHA


def test_ota_endpoint_cross_org_404_no_publish(monkeypatch, published):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    dev = _device_row("orgA")
    main.app.state.pool = _MemPool(_MemConn(dev))
    c = TestClient(main.app)
    token = jwt.encode(
        {"sub": "op-orgB", "role": "operator", "org": "orgB"}, SECRET, algorithm="HS256"
    )
    r = c.post(
        f"/api/v1/devices/{dev['id']}/ota",
        json=_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    assert published == []  # 跨 org:不得發布
