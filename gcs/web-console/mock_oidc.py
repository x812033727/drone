"""最小 OIDC provider(僅供 SSO 前端流程驗證/dev,非生產)。

實作授權碼 + PKCE:GET /authorize(自動核可,導回 redirect_uri?code=&state=)、
POST /token(驗 PKCE code_verifier,回 RS256 id_token)、GET /jwks(公鑰,供 fleet-svc
JWT_JWKS_URL 驗簽)。用法:python mock_oidc.py <port> [role]
"""

import base64
import hashlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9500
ROLE = sys.argv[2] if len(sys.argv) > 2 else "operator"
KID = "mock-oidc-key"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_priv_pem = _key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_key.public_key()))
_jwk.update(kid=KID, use="sig", alg="RS256")
_JWKS = {"keys": [_jwk]}
_challenges: dict[str, str] = {}  # code → code_challenge


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


class H(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, extra={"Access-Control-Allow-Headers": "content-type"})

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/jwks":
            self._send(200, json.dumps(_JWKS).encode())
        elif u.path == "/authorize":
            q = parse_qs(u.query)
            code = "mockcode-" + _b64url(hashlib.sha256(str(time.time()).encode()).digest())[:16]
            _challenges[code] = q.get("code_challenge", [""])[0]
            redirect = q.get("redirect_uri", [""])[0]
            state = q.get("state", [""])[0]
            sep = "&" if "?" in redirect else "?"
            self._send(302, extra={"Location": f"{redirect}{sep}code={code}&state={state}"})
        else:
            self._send(404)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/token":
            return self._send(404)
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        code = form.get("code", [""])[0]
        verifier = form.get("code_verifier", [""])[0]
        expected = _challenges.pop(code, None)
        if expected is None:
            return self._send(400, b'{"error":"invalid_grant"}')
        # 驗 PKCE:base64url(sha256(verifier)) == code_challenge
        if _b64url(hashlib.sha256(verifier.encode()).digest()) != expected:
            return self._send(400, b'{"error":"invalid_grant","desc":"PKCE mismatch"}')
        now = int(time.time())
        token = jwt.encode(
            {"sub": "mock-user", "role": ROLE, "iat": now, "exp": now + 3600},
            _priv_pem, algorithm="RS256", headers={"kid": KID},
        )
        self._send(200, json.dumps({"id_token": token, "token_type": "Bearer"}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"mock OIDC on :{PORT}(role={ROLE})", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
