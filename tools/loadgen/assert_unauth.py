#!/usr/bin/env python3
"""未帶 token 的保護端點必須回 401/403(fuzz 的確定性補強;R7)。

從 openapi.json 列舉全部 path,對每個 GET/POST 端點以無憑證打一發,
斷言回應 ∈ {401, 403}——豁免清單:healthz/metrics(內網豁免)、
/api/v1/stream(token 走 query,無 token 也回 401——仍在斷言內)、
/api/v1/billing/callback(綠界 webhook,以 CheckMacValue 驗章非 JWT)、
/api/v1/video/auth(MediaMTX 內網回呼,自身即認證器)。

用法:python assert_unauth.py --base http://127.0.0.1:8091 --openapi cloud/fleet_svc/openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

EXEMPT = {"/healthz", "/metrics", "/api/v1/billing/callback", "/api/v1/video/auth"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--openapi", required=True)
    args = parser.parse_args()

    spec = json.loads(Path(args.openapi).read_text(encoding="utf-8"))
    failures: list[str] = []
    checked = 0
    for path, methods in spec.get("paths", {}).items():
        if path in EXEMPT:
            continue
        concrete = path.replace("{", "0").replace("}", "")  # 路徑參數填佔位
        for method in methods:
            if method.upper() not in ("GET", "POST", "PUT", "DELETE"):
                continue
            url = args.base + concrete
            req = urllib.request.Request(url, method=method.upper())
            if method.upper() in ("POST", "PUT"):
                req.add_header("Content-Type", "application/json")
                req.data = b"{}"
            try:
                with urllib.request.urlopen(req, timeout=10) as r:  # nosec B310
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except OSError as e:
                failures.append(f"{method.upper()} {path}: 連線失敗 {e}")
                continue
            checked += 1
            if code not in (401, 403):
                failures.append(f"{method.upper()} {path}: 無憑證回 {code}(應 401/403)")

    if failures:
        for f in failures:
            print(f"[unauth] FAIL {f}", file=sys.stderr)
        return 1
    print(f"[unauth] PASS:{checked} 個端點無憑證一律 401/403")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
