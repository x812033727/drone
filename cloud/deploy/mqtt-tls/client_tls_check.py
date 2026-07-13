"""驗證 aiomqtt client 走 mTLS(= cloud/ingest 及 fleet/mission-svc 消費者用的路徑)。

引數:host port ca backend_cert backend_key dev_cert dev_key
斷言:backend 憑證(aiomqtt TLSParameters,同 ingest._tls_from_env)連 mTLS broker、
訂 fleet/+/telemetry、收到 dev-1 以 TLS 發布的自己遙測 → 客戶端 mTLS 端到端通。
"""

import asyncio
import sys

import aiomqtt

HOST, PORT, CA, BK_C, BK_K, D1_C, D1_K = (
    sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
)


async def _await_payload(bk: aiomqtt.Client, payload: str) -> bool:
    async for msg in bk.messages:
        if bytes(msg.payload).decode() == payload:
            return True
    return False


async def main() -> None:
    backend_tls = aiomqtt.TLSParameters(ca_certs=CA, certfile=BK_C, keyfile=BK_K)
    device_tls = aiomqtt.TLSParameters(ca_certs=CA, certfile=D1_C, keyfile=D1_K)
    payload = '{"droneId":"dev-1","battery_pct":88}'

    async with aiomqtt.Client(HOST, PORT, identifier="ingest-like", tls_params=backend_tls) as bk:
        await bk.subscribe("fleet/+/telemetry", qos=1)
        await asyncio.sleep(0.3)
        async with aiomqtt.Client(HOST, PORT, identifier="dev-1", tls_params=device_tls) as d1:
            await d1.publish("fleet/dev-1/telemetry", payload, qos=1)
        # asyncio.wait_for:Python 3.10 相容(asyncio.timeout 屬 3.11+)
        if not await asyncio.wait_for(_await_payload(bk, payload), timeout=5):
            raise SystemExit("✗ 未收到 dev-1 遙測")

    print("✓ aiomqtt backend(mTLS)收到 dev-1(mTLS)遙測")
    print("\nRESULT: PASS — 客戶端 mTLS 路徑(aiomqtt + 憑證)端到端通")


asyncio.run(main())
