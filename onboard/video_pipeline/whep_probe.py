#!/usr/bin/env python3
"""aiortc headless WHEP 探針(V6):證明 WebRTC 媒體面全鏈路,非只信令。

以 aiortc 對 MediaMTX WHEP 端點協商 → 完成 ICE/DTLS/SRTP → 收 H.264 幀 →
解 I420 亮度平面 → stamp.decode_stamp 讀回像素時戳。收到 N 幀有效時戳即 PASS。
這是無瀏覽器下能做到最誠實的驗證:信令 201(V1/V4)只證協商可建,本探針證
「畫面真的流過來且可解」。

⚠️ ICE:mediamtx 通告的 host candidate 是容器內埠——需 webrtcAdditionalHosts
包含探針可達的 host(CI/本機用 127.0.0.1);跨機/NAT 需 TURN(Phase 1)。

用法(需 pip install aiortc av numpy;--source test 的 simcam 在推流):
    python whep_probe.py --whep http://127.0.0.1:8889/drone/sim-1/whep \\
        --user reader --password dronedev-read --frames 5 --timeout 40
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import sys

import aiohttp
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from stamp import decode_stamp


async def _negotiate(session, whep_url, headers, pc) -> None:
    pc.addTransceiver("video", direction="recvonly")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    async with session.post(
        whep_url, data=pc.localDescription.sdp,
        headers={"Content-Type": "application/sdp", **headers},
    ) as resp:
        if resp.status != 201:
            raise RuntimeError(f"WHEP 信令失敗 HTTP {resp.status}")
        answer = await resp.text()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer, type="answer"))


async def run(args) -> int:
    headers = {}
    if args.user:
        cred = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
        headers["Authorization"] = f"Basic {cred}"

    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    got_stamps: list[int] = []
    done = asyncio.Event()

    @pc.on("track")
    def on_track(track):  # noqa: ANN001
        async def consume():
            import numpy as np

            while len(got_stamps) < args.frames:
                try:
                    frame = await asyncio.wait_for(track.recv(), timeout=args.timeout)
                except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                    break
                # av.VideoFrame → I420 亮度平面(plane 0)
                y = frame.to_ndarray(format="yuv420p")[: frame.height, : frame.width]
                ts = decode_stamp(np.ascontiguousarray(y, dtype=np.uint8))
                if ts is not None:
                    got_stamps.append(ts)
            done.set()

        asyncio.ensure_future(consume())

    async with aiohttp.ClientSession() as session:
        try:
            await _negotiate(session, args.whep, headers, pc)
            await asyncio.wait_for(done.wait(), timeout=args.timeout)
        finally:
            await pc.close()

    if len(got_stamps) >= args.frames:
        print(f"[whep-probe] PASS:收到 {len(got_stamps)} 幀有效像素時戳(媒體面全鏈路)")
        print(f"[whep-probe] 樣本 ts_ms: {got_stamps[:args.frames]}")
        return 0
    print(f"[whep-probe] FAIL:僅解出 {len(got_stamps)}/{args.frames} 幀時戳", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whep", required=True)
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    raise SystemExit(main())
