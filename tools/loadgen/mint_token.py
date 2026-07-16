#!/usr/bin/env python3
"""負載測試用 HS256 token 鑄造。

⚠️ 前提:負載對象棧必須設 `JWT_SECRET`(dev 模式 = 無認證 = 一律 admin,
配額/限流/org 過濾全豁免,壓不到 402/429/多租戶路徑——見 drone_common.auth)。
claim 慣例對齊 cloud/common/drone_common/auth.py:`role` 字串 + `org` 字串。

用法(也可被 locustfile / sse_swarm import):
    JWT_SECRET=devsecret python mint_token.py --role operator --org loadtest
"""

from __future__ import annotations

import argparse
import os
import time

import jwt

DEFAULT_TTL_S = 3600


def mint(
    secret: str,
    role: str = "viewer",
    org: str = "loadtest",
    sub: str = "loadgen",
    ttl_s: int = DEFAULT_TTL_S,
) -> str:
    """鑄一顆 HS256 token(claim 慣例:role + org,見模組 docstring)。"""
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "role": role, "org": org, "iat": now, "exp": now + ttl_s},
        secret,
        algorithm="HS256",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default="viewer", choices=["viewer", "operator", "admin"])
    parser.add_argument("--org", default="loadtest")
    parser.add_argument("--sub", default="loadgen")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_S)
    args = parser.parse_args()

    secret = os.environ.get("JWT_SECRET")
    if not secret:
        parser.error("需要 JWT_SECRET 環境變數(與受測棧同值)")
    print(mint(secret, role=args.role, org=args.org, sub=args.sub, ttl_s=args.ttl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
