"""MediaMTX 認證橋:純函式 + 端點無 DB 路徑(admin/401/403)。

org-device 隔離的真 PG 路徑由 compose-smoke 的 videoauth overlay 步驟驗
(需 fleet.device 表);此處只驗不碰 pool 的分支。
"""

from __future__ import annotations

import asyncio

import pytest
from fleet_svc import main as fleet_main
from fleet_svc.video_auth import (
    VideoAuthRequest,
    extract_jwt,
    publish_credentials_ok,
    stream_serial,
)

# ---- 純函式 ----

def test_publish_credentials(monkeypatch):
    monkeypatch.setenv("VIDEO_PUBLISH_USER", "pub")
    monkeypatch.setenv("VIDEO_PUBLISH_PASS", "s3cret")
    assert publish_credentials_ok("pub", "s3cret")
    assert not publish_credentials_ok("pub", "wrong")
    assert not publish_credentials_ok("", "")


def test_publish_denied_when_env_unset(monkeypatch):
    monkeypatch.delenv("VIDEO_PUBLISH_USER", raising=False)
    monkeypatch.delenv("VIDEO_PUBLISH_PASS", raising=False)
    assert not publish_credentials_ok("publisher", "dronedev-publish")


JWT_LIKE = "aaa.bbb.ccc"


def test_extract_jwt_priority_and_shapes():
    # token 欄位最優先
    assert extract_jwt(VideoAuthRequest(token=JWT_LIKE, password="x.y.z")) == JWT_LIKE
    # ?jwt= 查詢參數
    assert extract_jwt(VideoAuthRequest(query=f"jwt={JWT_LIKE}&foo=1")) == JWT_LIKE
    # Basic 的 password 位
    assert extract_jwt(VideoAuthRequest(user="whatever", password=JWT_LIKE)) == JWT_LIKE
    # Bearer 被切分後落在 user 位
    assert extract_jwt(VideoAuthRequest(user=JWT_LIKE)) == JWT_LIKE
    # 非三段式一律不取
    assert extract_jwt(VideoAuthRequest(user="pub", password="pass")) is None
    assert extract_jwt(VideoAuthRequest()) is None


def test_stream_serial():
    assert stream_serial("drone/dev-1") == "dev-1"
    assert stream_serial("drone/DEV_2") == "DEV_2"
    assert stream_serial("stream") is None
    assert stream_serial("drone/") is None
    assert stream_serial("drone/a/b") is None


# ---- 端點(無 DB 分支;直接呼叫 handler coroutine)----

def _call(body: VideoAuthRequest):
    return asyncio.run(fleet_main.video_auth_callback(body))


def test_endpoint_publish_ok(monkeypatch):
    monkeypatch.setenv("VIDEO_PUBLISH_USER", "pub")
    monkeypatch.setenv("VIDEO_PUBLISH_PASS", "s3cret")
    resp = _call(VideoAuthRequest(action="publish", user="pub", password="s3cret"))
    assert resp.status_code == 204


def test_endpoint_publish_bad_creds_401(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("VIDEO_PUBLISH_USER", "pub")
    monkeypatch.setenv("VIDEO_PUBLISH_PASS", "s3cret")
    with pytest.raises(HTTPException) as exc:
        _call(VideoAuthRequest(action="publish", user="pub", password="wrong"))
    assert exc.value.status_code == 401


def test_endpoint_read_dev_mode_allows(monkeypatch):
    monkeypatch.setattr(fleet_main, "AUTH_ENABLED", False)
    resp = _call(VideoAuthRequest(action="read", path="drone/dev-1"))
    assert resp.status_code == 204


def test_endpoint_read_missing_token_401(monkeypatch):
    monkeypatch.setattr(fleet_main, "AUTH_ENABLED", True)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _call(VideoAuthRequest(action="read", path="drone/dev-1"))
    assert exc.value.status_code == 401


def test_endpoint_read_admin_allows_any_device(monkeypatch):
    monkeypatch.setattr(fleet_main, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        fleet_main, "authorize_token",
        lambda token, min_role: {"sub": "a", "role": "admin", "org": "any"},
    )
    resp = _call(VideoAuthRequest(action="read", path="drone/dev-1", query=f"jwt={JWT_LIKE}"))
    assert resp.status_code == 204


def test_endpoint_read_bad_path_403(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(fleet_main, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        fleet_main, "authorize_token",
        lambda token, min_role: {"sub": "a", "role": "admin", "org": "any"},
    )
    with pytest.raises(HTTPException) as exc:
        _call(VideoAuthRequest(action="read", path="stream", query=f"jwt={JWT_LIKE}"))
    assert exc.value.status_code == 403


def test_endpoint_other_actions_403():
    from fastapi import HTTPException

    for action in ("playback", "api", "metrics", ""):
        with pytest.raises(HTTPException) as exc:
            _call(VideoAuthRequest(action=action))
        assert exc.value.status_code == 403
