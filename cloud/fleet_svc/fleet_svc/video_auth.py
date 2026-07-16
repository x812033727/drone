"""MediaMTX HTTP 認證橋(authMethod: http → authHTTPAddress 指向本端點)。

MediaMTX 對每個連線動作 POST JSON(user/password/token/ip/action/path/protocol/
id/query,見 MediaMTX README「HTTP-based」),20x = 放行。本橋接策略:

- ``publish``(機上 RTSP 推流):比對 VIDEO_PUBLISH_USER / VIDEO_PUBLISH_PASS
  環境變數(constant-time),語意與 internal-users 模式等價。
- ``read``(WHEP / RTSP 訂閱):自 payload 取 fleet JWT →
  ``auth.authorize_token(token, "viewer")`` + **org-device 隔離**
  (path=drone/<serial> 的 serial 須屬 principal 的 org;admin 跨 org)。
  JWT 取用順序(v1.12.3 實測可達之管道):
  1. ``token`` 欄位(保留;http 法通常為空)
  2. ``?jwt=`` 查詢參數(payload.query;瀏覽器 EventSource/WHEP 最穩管道)
  3. ``password``(Basic user:pass 的 pass 位;user 任意)
  4. ``user``(Bearer 值被 mediamtx 以冒號切分後的 user 位)
- ``playback``/``api``/``metrics``/``pprof``:預期由 overlay 的
  ``authHTTPExclude`` 排除(loopback 內網豁免);若仍打進來,一律 403。

空帳密請求回 401(spec:RTSP 客戶端要收到 401 才會補送憑證)。
dev 模式(fleet 認證停用)read 放行,對齊全站 dev 語意。
"""

from __future__ import annotations

import hmac
import os
import re
from urllib.parse import parse_qs

from pydantic import BaseModel

_STREAM_PATH = re.compile(r"^drone/([A-Za-z0-9_-]+)$")


class VideoAuthRequest(BaseModel):
    """MediaMTX authHTTPAddress 的 POST payload(欄位皆可缺)。"""

    user: str = ""
    password: str = ""
    token: str = ""
    ip: str = ""
    action: str = ""
    path: str = ""
    protocol: str = ""
    id: str = ""
    query: str = ""


def publish_credentials_ok(user: str, password: str) -> bool:
    """publish 帳密比對(constant-time)。環境變數未設 → 一律拒(安全預設)。"""
    expect_user = os.environ.get("VIDEO_PUBLISH_USER") or ""
    expect_pass = os.environ.get("VIDEO_PUBLISH_PASS") or ""
    if not expect_user or not expect_pass:
        return False
    return hmac.compare_digest(user, expect_user) and hmac.compare_digest(
        password, expect_pass
    )


def extract_jwt(req: VideoAuthRequest) -> str | None:
    """依 docstring 順序取 JWT 候選;JWT 特徵 = 兩個點的三段式。"""
    candidates = [req.token]
    qs = parse_qs(req.query)
    candidates.extend(qs.get("jwt", []))
    candidates.append(req.password)
    candidates.append(req.user)
    for c in candidates:
        if c and c.count(".") == 2:
            return c
    return None


def stream_serial(path: str) -> str | None:
    """path=drone/<serial> 取 serial;非本命名慣例回 None。"""
    m = _STREAM_PATH.match(path)
    return m.group(1) if m else None
