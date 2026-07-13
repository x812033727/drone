"""OIDC-ready 後端路徑驗證:RS256 + JWKS(本地起 JWKS 伺服器,無需外部 IdP)。

驗證 auth.py 的 JWT_JWKS_URL 分支(生產 OIDC 用;先前只測 HS256):
以本地 RSA 金鑰簽 RS256 token、本地 HTTP 供 JWKS,auth 經 JWKS 驗簽 + RBAC。
"""

import asyncio
import importlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

KID = "test-key-1"


def _gen_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _priv_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _jwks_for(key) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid=KID, use="sig", alg="RS256")
    return {"keys": [jwk]}


def _serve(jwks: dict) -> tuple[HTTPServer, str]:
    body = json.dumps(jwks).encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/jwks.json"


def _rs256(pem: bytes, role: str) -> str:
    return jwt.encode({"sub": "u", "role": role}, pem, algorithm="RS256", headers={"kid": KID})


def test_jwks_rs256_validation_and_rbac():
    key = _gen_key()
    srv, url = _serve(_jwks_for(key))
    pem = _priv_pem(key)

    prev_jwks = os.environ.get("JWT_JWKS_URL")
    prev_secret = os.environ.get("JWT_SECRET")
    os.environ["JWT_JWKS_URL"] = url
    os.environ.pop("JWT_SECRET", None)
    import fleet_svc.auth as auth

    importlib.reload(auth)
    try:
        assert auth.AUTH_ENABLED  # JWKS 設定 → 認證啟用

        def cred(token):
            return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        viewer_dep = auth.require_role("viewer")
        operator_dep = auth.require_role("operator")

        # operator token 經 JWKS 驗簽 + 通過 viewer 門檻
        claims = asyncio.run(viewer_dep(cred(_rs256(pem, "operator"))))
        assert claims["role"] == "operator"

        # viewer token 對 operator 端點 → 403
        with pytest.raises(HTTPException) as e:
            asyncio.run(operator_dep(cred(_rs256(pem, "viewer"))))
        assert e.value.status_code == 403

        # 別的金鑰簽的 token(JWKS 驗簽失敗)→ 401
        bad = _rs256(_priv_pem(_gen_key()), "operator")
        with pytest.raises(HTTPException) as e2:
            asyncio.run(viewer_dep(cred(bad)))
        assert e2.value.status_code == 401
    finally:
        srv.shutdown()
        if prev_jwks is None:
            os.environ.pop("JWT_JWKS_URL", None)
        else:
            os.environ["JWT_JWKS_URL"] = prev_jwks
        if prev_secret is not None:
            os.environ["JWT_SECRET"] = prev_secret
        importlib.reload(auth)  # 還原模組狀態
