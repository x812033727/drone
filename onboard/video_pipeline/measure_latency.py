#!/usr/bin/env python3
"""訂閱量測端:RTSP 拉流 → 解碼 → 讀回像素時戳 → 端到端延遲統計。

latency_ms = 收到並解碼完該幀的當下 - 幀內嵌的 unix_time_ms。
涵蓋:取樣→編碼→RTSP 推流→MediaMTX 轉發→拉流→解碼,即「玻璃到玻璃」
再扣掉顯示的部分。同機量測時鐘零漂移;跨機需 PTP/NTP 對時(見 README)。

注意 rtspsrc 預設 jitterbuffer latency=2000ms,量測必須顯式設 0,
否則量到的是 buffer 深度而非管線延遲。
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402
from stamp import decode_stamp  # noqa: E402


def build_pipeline(rtsp_url: str) -> Gst.Pipeline:
    desc = (
        f"rtspsrc location={rtsp_url} latency=0 protocols=tcp "
        f"! rtph264depay ! h264parse ! avdec_h264 "
        f"! videoconvert ! video/x-raw,format=GRAY8 "
        f"! appsink name=sink emit-signals=true sync=false max-buffers=4 drop=false"
    )
    return Gst.parse_launch(desc)


def percentile_stats(latencies_ms: list[float]) -> dict:
    import numpy as np

    arr = np.asarray(latencies_ms)
    return {
        "p50": round(float(np.percentile(arr, 50)), 1),
        "p90": round(float(np.percentile(arr, 90)), 1),
        "p99": round(float(np.percentile(arr, 99)), 1),
        "max": round(float(arr.max()), 1),
        "min": round(float(arr.min()), 1),
        "mean": round(float(arr.mean()), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rtsp-url", default="rtsp://127.0.0.1:8554/stream")
    parser.add_argument("--frames", type=int, default=300, help="有效樣本數(不含 warmup)")
    parser.add_argument(
        "--warmup", type=int, default=30, help="略過起始幀數(連線/等 keyframe 的暫態)"
    )
    parser.add_argument("--timeout", type=float, default=120, help="整體逾時(秒)")
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出統計到 stdout")
    args = parser.parse_args()

    import numpy as np

    Gst.init(None)
    pipeline = build_pipeline(args.rtsp_url)
    sink = pipeline.get_by_name("sink")
    loop = GLib.MainLoop()

    latencies: list[float] = []
    state = {"seen": 0, "decode_failures": 0, "error": None}

    def on_sample(sink_):
        sample = sink_.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        now_ms = time.time_ns() / 1e6
        caps = sample.get_caps().get_structure(0)
        width, height = caps.get_value("width"), caps.get_value("height")
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            stride = len(mapinfo.data) // height
            luma = np.frombuffer(mapinfo.data, dtype=np.uint8)[: stride * height]
            luma = luma.reshape(height, stride)[:, :width]
            state["seen"] += 1
            if state["seen"] <= args.warmup:
                return Gst.FlowReturn.OK
            ts_ms = decode_stamp(luma)
            if ts_ms is None:
                state["decode_failures"] += 1
                return Gst.FlowReturn.OK
            latencies.append(now_ms - ts_ms)
            if len(latencies) >= args.frames:
                loop.quit()
        finally:
            buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    sink.connect("new-sample", on_sample)

    def on_bus(_bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            state["error"] = f"{err.message} ({dbg})"
            loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            state["error"] = "上游 EOS,樣本不足"
            loop.quit()
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus)
    GLib.timeout_add(int(args.timeout * 1000), loop.quit)

    pipeline.set_state(Gst.State.PLAYING)
    print(f"[measure] 訂閱 {args.rtsp_url},目標 {args.frames} 樣本…", file=sys.stderr)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    pipeline.set_state(Gst.State.NULL)

    if state["error"]:
        print(f"[measure] pipeline 錯誤:{state['error']}", file=sys.stderr)
    if len(latencies) < args.frames:
        print(
            f"[measure] 樣本不足:{len(latencies)}/{args.frames}(逾時或串流中斷)",
            file=sys.stderr,
        )
        return 1

    result = {
        "rtsp_url": args.rtsp_url,
        "samples": len(latencies),
        "warmup_skipped": args.warmup,
        "decode_failures": state["decode_failures"],
        "latency_ms": percentile_stats(latencies),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        lat = result["latency_ms"]
        print(
            f"[measure] 樣本 {result['samples']}(decode 失敗 {result['decode_failures']})\n"
            f"[measure] 端到端延遲 ms:p50={lat['p50']} p90={lat['p90']} "
            f"p99={lat['p99']} max={lat['max']} min={lat['min']} mean={lat['mean']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
