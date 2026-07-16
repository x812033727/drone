#!/usr/bin/env python3
"""SSE 訂閱者蜂群:對 fleet-svc /api/v1/stream 開 M 條長連線,三型混布。

- normal:正常讀(逐行消費)
- slow:連上後刻意不讀(觸發 TCP backpressure + hub drop-oldest)
- abort:讀幾秒後粗暴斷線(RST 路徑,驗 generator 收尾)

零額外依賴:raw asyncio socket 手寫 HTTP/1.1 GET(SSE 是純文字串流)。
結束斷言:/metrics 的 fleet_sse_subscribers 回到基線(無訂閱者洩漏)。

用法(對隔離棧;需 JWT_SECRET 同值鑄 token):
    JWT_SECRET=devsecret python tools/loadgen/sse_swarm.py \
        --host 127.0.0.1 --port 38091 --clients 100 --slow 20 --abort 20 --seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mint_token import mint  # noqa: E402


def _gauge(host: str, port: int, name: str) -> float | None:
    try:
        # URL 為本工具自組的固定 http scheme(host/port 來自 CLI 參數),
        # 非外部輸入;B310 針對 file:/ 自訂 scheme 的風險不適用。
        with urllib.request.urlopen(  # nosec B310
            f"http://{host}:{port}/metrics", timeout=5
        ) as r:
            for line in r.read().decode().splitlines():
                if line.startswith(name + " "):
                    return float(line.split()[1])
    except OSError:
        return None
    return None


async def _sse_client(
    host: str, port: int, token: str, mode: str, seconds: float, stats: dict
) -> None:
    try:
        reader, writer = await asyncio.open_connection(host, port)
        req = (
            f"GET /api/v1/stream?token={token} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\nAccept: text/event-stream\r\n\r\n"
        )
        writer.write(req.encode())
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout=10)
        if b"200" not in status_line:
            stats["connect_fail"] += 1
            writer.close()
            return
        stats["connected"] += 1

        deadline = asyncio.get_event_loop().time() + seconds
        if mode == "slow":
            # 刻意不讀:掛著到期(server 端佇列會滿 → drop-oldest)
            await asyncio.sleep(seconds)
        else:
            abort_at = deadline - seconds * 0.7 if mode == "abort" else deadline
            while asyncio.get_event_loop().time() < abort_at:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                if line.startswith(b"data:"):
                    stats["events"] += 1
        if mode == "abort":
            # 粗暴斷線:不送 FIN 前的優雅收尾,直接 abort(RST)
            writer.transport.abort()
            stats["aborted"] += 1
        else:
            writer.close()
    except (OSError, asyncio.TimeoutError):
        stats["errors"] += 1


async def run(args) -> int:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        print("需要 JWT_SECRET(與受測棧同值)", file=sys.stderr)
        return 2
    token = mint(secret, role="viewer", org=args.org, ttl_s=int(args.seconds) + 600)

    base = _gauge(args.host, args.port, "fleet_sse_subscribers")
    print(f"[swarm] 基線 fleet_sse_subscribers={base}")

    stats = {"connected": 0, "connect_fail": 0, "events": 0, "aborted": 0, "errors": 0}
    normal = args.clients - args.slow - args.abort
    modes = ["normal"] * normal + ["slow"] * args.slow + ["abort"] * args.abort
    await asyncio.gather(
        *(_sse_client(args.host, args.port, token, m, args.seconds, stats) for m in modes)
    )

    # 全部斷線後給 server 一點收尾時間(is_disconnected 輪詢 + keepalive 週期)
    await asyncio.sleep(args.settle)
    final = _gauge(args.host, args.port, "fleet_sse_subscribers")
    print(f"[swarm] stats={stats} final_gauge={final}")

    if final is None or base is None:
        print("[swarm] 無法讀 /metrics gauge(fleet-svc 未起或版本無此指標)", file=sys.stderr)
        return 2
    if final > base:
        print(f"[swarm] FAIL:訂閱者洩漏(基線 {base} → 結束 {final})", file=sys.stderr)
        return 1
    if stats["connected"] < args.clients * 0.95:
        print(f"[swarm] FAIL:連線成功率過低 {stats['connected']}/{args.clients}", file=sys.stderr)
        return 1
    print("[swarm] PASS:全型態斷線後訂閱者歸零、連線成功率達標")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=38091)
    parser.add_argument("--org", default="loadtest")
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--slow", type=int, default=20, help="慢讀(不消費)客戶端數")
    parser.add_argument("--abort", type=int, default=20, help="粗暴斷線客戶端數")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--settle", type=float, default=20.0, help="斷線後收尾等待秒數")
    args = parser.parse_args()
    if args.slow + args.abort > args.clients:
        parser.error("--slow + --abort 不可超過 --clients")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
