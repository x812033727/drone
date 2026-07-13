"""dispatch_ota CLI:payload 組裝對齊 onboard ota.py(parse_ota_command round-trip)。

conftest 已把 tools/ 加入 path(import dispatch_ota);本檔另把 onboard/drone_agent 加入
path 以 import 機上 parse_ota_command,對「CLI 組出的 payload 機上能否解析」做硬證。
機上 ota.py 依賴(aiomqtt/cryptography)於全域 pytest 環境(ci.yml lint-test)皆具備;
缺依賴時 importorskip 跳過(不誤紅)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from dispatch_ota import build_ota_payload

_ONBOARD = Path(__file__).resolve().parents[2] / "onboard" / "drone_agent"
sys.path.insert(0, str(_ONBOARD))
parse_ota_command = pytest.importorskip("drone_agent.ota").parse_ota_command

SHA = "a" * 64


def _payload_json(**kw) -> str:
    return json.dumps(build_ota_payload(**kw))


def test_install_roundtrips_through_onboard_parse():
    cmd = parse_ota_command(
        _payload_json(
            action="install",
            update_id="ota-1",
            component="onboard",
            version="1.4.0",
            url="https://mirror/onboard-1.4.0.tgz",
            sha256=SHA,
            signature="c2ln",
            size=42,
        )
    )
    assert cmd.action == "install"
    assert cmd.update_id == "ota-1"
    assert cmd.component == "onboard"
    assert cmd.version == "1.4.0"
    assert cmd.sha256 == SHA
    assert cmd.signature == "c2ln"
    assert cmd.size == 42


def test_control_commands_roundtrip():
    for action in ("pause", "resume", "rollback"):
        cmd = parse_ota_command(_payload_json(action=action, update_id="u9"))
        assert cmd.action == action and cmd.update_id == "u9"


def test_rollback_with_component_roundtrips():
    cmd = parse_ota_command(_payload_json(action="rollback", update_id="u9", component="onboard"))
    assert cmd.action == "rollback" and cmd.component == "onboard"


def test_sha256_uppercase_normalized():
    payload = build_ota_payload(
        action="install", update_id="u1", component="onboard", version="1.0.0",
        url="https://m/x.tgz", sha256="A" * 64, signature="c2ln",
    )
    assert payload["sha256"] == "a" * 64


# ---- 參數/欄位錯誤:build_ota_payload 拒收 ----
def test_install_missing_fields_raises():
    with pytest.raises(ValueError):
        build_ota_payload(action="install", update_id="u1")


def test_bad_action_raises():
    with pytest.raises(ValueError):
        build_ota_payload(action="reboot", update_id="u1")


def test_bad_sha256_raises():
    with pytest.raises(ValueError):
        build_ota_payload(
            action="install", update_id="u1", component="onboard", version="1.0.0",
            url="https://m/x.tgz", sha256="xyz", signature="c2ln",
        )


def test_empty_update_id_raises():
    with pytest.raises(ValueError):
        build_ota_payload(action="pause", update_id="")
