"""log-svc:接收 drone-agent 上傳的 ULog → 存檔 → 背景跑 ulog_report → 摘要落庫。

Phase 0 雛形(對 docs/20-software/cloud-fleet.md 的 log-svc「ULog 自動上傳與解析」):
- POST /api/v1/logs/{drone_id}(multipart file)→ 存 /data/ulog/{drone_id}/
  {UTC 時戳}_{原檔名};BackgroundTasks 跑 tools/ulog_report.py,報告全文存
  同名 .report.txt,摘要列(report_ok + 前 500 字 + 異常規則條目 alerts)
  落 flight_logs 表(cloud-fleet.md §3 異常規則自動開單的 Phase 0 雛形:
  先落庫上看板,開維保單屬 Phase 1)。
  報告失敗(非法 ULog / 崩潰 / 逾時)不擋:report_ok=false 照落庫。
- GET /api/v1/logs/{drone_id}:該機回收清單(JSON,查詢用)。
- GET /healthz:含 DB 探活(供 compose healthcheck)。

異常規則自動開維保單、簽章、保存年限屬 Phase 1(見 cloud-fleet.md §3)。
環境變數:PG_DSN / ULOG_DIR(預設 /data/ulog)。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile

from log_svc.report import excerpt, parse_alerts, run_report

log = logging.getLogger("log_svc")

PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
ULOG_DIR = Path(os.environ.get("ULOG_DIR", "/data/ulog"))
PG_CONNECT_ATTEMPTS = 30  # 啟動時等 DB 就緒:最多 30 次、每 2 秒(同 ingest)
PG_CONNECT_RETRY_S = 2
UPLOAD_CHUNK = 1 << 20  # 上傳串流寫檔的分塊(1 MiB),大檔不佔記憶體
LIST_LIMIT = 100

INSERT_SQL = (
    "INSERT INTO flight_logs "
    "(time, drone_id, filename, size_bytes, report_ok, report_excerpt, alerts) "
    "VALUES (now(), $1, $2, $3, $4, $5, $6)"
)
LIST_SQL = (
    "SELECT time, filename, size_bytes, report_ok, alerts FROM flight_logs "
    f"WHERE drone_id = $1 ORDER BY time DESC LIMIT {LIST_LIMIT}"
)


def validate_drone_id(drone_id: str) -> None:
    """把關路徑成分:drone_id 直接當目錄名,拒絕任何路徑跳脫。"""
    if not drone_id or drone_id != Path(drone_id).name or drone_id in (".", ".."):
        raise HTTPException(status_code=400, detail=f"非法 drone_id:{drone_id!r}")


def stored_name(original: str | None, now: datetime | None = None) -> str:
    """存檔名:{UTC 時戳}_{原檔名}(原檔名僅取 basename,防路徑跳脫)。"""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    base = Path(original or "").name or "unnamed.ulg"
    return f"{ts}_{base}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    last_exc: Exception | None = None
    for attempt in range(PG_CONNECT_ATTEMPTS):
        try:
            app.state.pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
            break
        except (OSError, asyncpg.PostgresError) as e:
            last_exc = e
            log.warning("等待 DB 就緒(%d/%d):%s", attempt + 1, PG_CONNECT_ATTEMPTS, e)
            await asyncio.sleep(PG_CONNECT_RETRY_S)
    else:
        raise RuntimeError(f"DB 連線失敗(已重試 {PG_CONNECT_ATTEMPTS} 次):{last_exc}")
    log.info("log-svc 就緒:ULOG_DIR=%s", ULOG_DIR)
    yield
    await app.state.pool.close()


app = FastAPI(title="log-svc", lifespan=lifespan)


async def process_log(drone_id: str, path: Path, size_bytes: int) -> None:
    """背景任務:跑報告 → 摘要落庫。報告失敗不擋(report_ok=false 照落庫)。

    異常規則行(ulog_report「⚠ 異常提示」條目)解析後存 alerts 欄
    (無異常存 NULL,看板紅底以非空為判準)。
    """
    report_ok, text = await run_report(path)
    alerts = parse_alerts(text)
    await app.state.pool.execute(
        INSERT_SQL, drone_id, path.name, size_bytes, report_ok, excerpt(text), alerts or None
    )
    log.info(
        "已落庫 flight_logs:%s/%s(%d bytes,report_ok=%s,alerts=%d 條)",
        drone_id,
        path.name,
        size_bytes,
        report_ok,
        len(alerts.splitlines()) if alerts else 0,
    )


@app.get("/healthz")
async def healthz() -> dict:
    await app.state.pool.fetchval("SELECT 1")
    return {"status": "ok"}


@app.post("/api/v1/logs/{drone_id}", status_code=201)
async def upload_log(drone_id: str, file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    validate_drone_id(drone_id)
    dest_dir = ULOG_DIR / drone_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored_name(file.filename)

    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(UPLOAD_CHUNK):
            out.write(chunk)
            size += len(chunk)
    log.info("已收檔:%s(%d bytes),報告排入背景", dest, size)

    background_tasks.add_task(process_log, drone_id, dest, size)
    return {"drone_id": drone_id, "stored_as": dest.name, "size_bytes": size}


@app.get("/api/v1/logs/{drone_id}")
async def list_logs(drone_id: str) -> dict:
    validate_drone_id(drone_id)
    rows = await app.state.pool.fetch(LIST_SQL, drone_id)
    return {
        "drone_id": drone_id,
        "logs": [
            {
                "time": row["time"].isoformat(),
                "filename": row["filename"],
                "size_bytes": row["size_bytes"],
                "report_ok": row["report_ok"],
                "alerts": row["alerts"],
            }
            for row in rows
        ],
    }
