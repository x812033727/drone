#!/usr/bin/env python3
"""匯出各 cloud FastAPI 服務的 OpenAPI 契約到版控(G26 機器可讀 API 契約)。

各服務 runtime 由 FastAPI 產 OpenAPI,但過去未 commit 檔案 → 客戶/整合方無穩定契約。
本腳本 import 各服務的 `app` 物件、呼叫 `app.openapi()`,把結果寫成
`cloud/<svc>/openapi.json`。CI 守門(.github/workflows/openapi.yml)重跑本腳本後
`git diff --exit-code`,確保 commit 的契約與程式碼永遠同步(仿 proto codegen 守門)。

安全 import:三個服務(fleet/mission/log)的 `app = FastAPI(...)` 在模組頂層建立,
但 DB 連線只發生在 `lifespan`(啟動時才跑),import 不觸發任何 I/O;`app.openapi()`
純由路由/pydantic 模型產生 schema,不需啟動 lifespan。故本腳本可離線、無 DB 執行。
ingest 服務是純 MQTT 消費者、無 HTTP API,不在契約範圍。

用法:
    python tools/dump_openapi.py          # 寫檔
    python tools/dump_openapi.py --check  # 只驗證與現存檔一致(不寫),不一致回傳非 0

輸出為確定性(sort_keys + 固定縮排 + 尾端換行),連跑兩次 diff 為空。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

# repo 根:tools/ 的上一層
ROOT = Path(__file__).resolve().parent.parent

# 服務清單:(輸出目錄相對 repo 根, 套件 import 路徑, app 物件名)
# 套件目錄 cloud/<svc> 需進 sys.path 才能 import 內層套件(如 fleet_svc)。
SERVICES = [
    ("cloud/fleet_svc", "fleet_svc.main", "app"),
    ("cloud/mission_svc", "mission_svc.main", "app"),
    ("cloud/log_svc", "log_svc.main", "app"),
]


def _load_app(pkg_dir: str, module_path: str, attr: str):
    """把服務套件目錄加到 sys.path 前緣後 import,取出 FastAPI app 物件。"""
    src = str(ROOT / pkg_dir)
    if src not in sys.path:
        sys.path.insert(0, src)
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _dump(app) -> str:
    """產生確定性的 OpenAPI JSON 字串(尾端含換行)。"""
    schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只比對不寫檔;有服務契約與現存檔不一致則回傳非 0",
    )
    args = parser.parse_args()

    drift = []
    for pkg_dir, module_path, attr in SERVICES:
        app = _load_app(pkg_dir, module_path, attr)
        content = _dump(app)
        out = ROOT / pkg_dir / "openapi.json"
        if args.check:
            existing = out.read_text(encoding="utf-8") if out.exists() else ""
            status = "ok" if existing == content else "DRIFT"
            if existing != content:
                drift.append(str(out.relative_to(ROOT)))
            print(f"[{status}] {out.relative_to(ROOT)}")
        else:
            out.write_text(content, encoding="utf-8")
            print(f"[written] {out.relative_to(ROOT)}")

    if args.check and drift:
        print(
            "\n契約與程式碼不同步(請重跑 `python tools/dump_openapi.py` 並 commit):",
            file=sys.stderr,
        )
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
