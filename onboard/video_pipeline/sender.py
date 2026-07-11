#!/usr/bin/env python3
"""推流端:合成畫面或 v4l2 相機 → H.264(x264 zerolatency)→ RTSP 推 MediaMTX。

預設 --source test:每幀在左上角時戳條寫入當下 unix_time_ms(見 stamp.py),
其餘畫面為彩條背景 + 移動方塊 + 每幀更新的雜訊帶(讓編碼器有真實工作量,
避免靜態畫面把編碼成本量測得過於樂觀)。

--source v4l2:/dev/videoN 改推實體相機(USB UVC 等):解析度/幀率由相機
協商,**無像素時戳**(延遲量測僅 test 源支援),推流至 --duration 或中斷。

x86 上以 x264enc 軟編,僅供方法論與傳輸層基線;Jetson 實機換
nvv4l2h264enc + 實體相機源(v4l2src/nvarguscamerasrc),見 README。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402
from pipelines import (  # noqa: E402
    build_test_pipeline_desc,
    build_v4l2_pipeline_desc,
    parse_source,
)
from stamp import encode_stamp  # noqa: E402

# BT.601 studio-range 彩條(Y, U, V)
_BARS_YUV = [
    (235, 128, 128),  # white
    (210, 16, 146),  # yellow
    (170, 166, 16),  # cyan
    (145, 54, 34),  # green
    (106, 202, 222),  # magenta
    (81, 90, 240),  # red
    (41, 240, 110),  # blue
]

NOISE_BAND_H = 128  # 每幀更新的雜訊帶高度(px)


def build_background(width: int, height: int):
    """預先鋪好 I420 彩條背景,回傳 (buffer, y_plane_view)。"""
    import numpy as np

    frame = np.empty(width * height * 3 // 2, dtype=np.uint8)
    y = frame[: width * height].reshape(height, width)
    u = frame[width * height : width * height * 5 // 4].reshape(height // 2, width // 2)
    v = frame[width * height * 5 // 4 :].reshape(height // 2, width // 2)
    bar_w = width // len(_BARS_YUV)
    for i, (yy, uu, vv) in enumerate(_BARS_YUV):
        x0, x1 = i * bar_w, width if i == len(_BARS_YUV) - 1 else (i + 1) * bar_w
        y[:, x0:x1] = yy
        u[:, x0 // 2 : x1 // 2] = uu
        v[:, x0 // 2 : x1 // 2] = vv
    return frame, y


def build_pipeline(args) -> tuple[Gst.Pipeline, Gst.Element]:
    desc = build_test_pipeline_desc(args.width, args.height, args.fps, args.bitrate, args.rtsp_url)
    pipeline = Gst.parse_launch(desc)
    return pipeline, pipeline.get_by_name("src")


def run_v4l2(args, device: str) -> int:
    """v4l2 相機推流:GLib mainloop 跑至 --duration(0 = 直到中斷)。"""
    pipeline = Gst.parse_launch(build_v4l2_pipeline_desc(device, args.bitrate, args.rtsp_url))
    loop = GLib.MainLoop()
    error: list[str] = []

    def on_bus(_bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            error.append(f"{err.message} ({dbg})")
            loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            loop.quit()
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus)

    if args.duration:

        def send_eos():
            pipeline.send_event(Gst.Event.new_eos())
            return False  # 一次性 timeout

        GLib.timeout_add(int(args.duration * 1000), send_eos)

    pipeline.set_state(Gst.State.PLAYING)
    print(f"[sender] v4l2 {device} {args.bitrate}kbps → {args.rtsp_url}", flush=True)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)

    if error:
        print(f"[sender] pipeline 錯誤:{error[0]}", file=sys.stderr)
        return 1
    print("[sender] v4l2 推流結束", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate", type=int, default=4000, help="x264enc 目標碼率(kbps)")
    parser.add_argument("--rtsp-url", default="rtsp://127.0.0.1:8554/stream")
    parser.add_argument("--duration", type=float, default=0, help="推流秒數,0 = 直到中斷")
    parser.add_argument(
        "--source",
        default="test",
        help="視訊源:test(合成畫面+像素時戳,預設)或 v4l2:/dev/videoN"
        "(實體相機;寬高幀率由相機協商,無像素時戳)",
    )
    args = parser.parse_args()

    try:
        kind, device = parse_source(args.source)
    except ValueError as e:
        parser.error(str(e))

    import numpy as np

    Gst.init(None)

    if kind == "v4l2":
        return run_v4l2(args, device)

    pipeline, appsrc = build_pipeline(args)

    loop = GLib.MainLoop()
    error: list[str] = []

    def on_bus(_bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            error.append(f"{err.message} ({dbg})")
            loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            loop.quit()
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus)
    loop_thread = threading.Thread(target=loop.run, daemon=True)
    loop_thread.start()

    pipeline.set_state(Gst.State.PLAYING)
    background, _ = build_background(args.width, args.height)
    frame_dur_ns = Gst.SECOND // args.fps
    noise_y0 = args.height - NOISE_BAND_H
    rng = np.random.default_rng()

    print(
        f"[sender] {args.width}x{args.height}@{args.fps} {args.bitrate}kbps → {args.rtsp_url}",
        flush=True,
    )
    t_start = time.monotonic()
    idx = 0
    try:
        while not error:
            if args.duration and time.monotonic() - t_start >= args.duration:
                break
            frame = background.copy()
            y = frame[: args.width * args.height].reshape(args.height, args.width)
            # 移動方塊(產生跨幀運動)
            bx = (idx * 8) % (args.width - 64)
            y[args.height // 2 : args.height // 2 + 64, bx : bx + 64] = 235
            # 雜訊帶(逼編碼器實際工作)
            y[noise_y0:, :] = rng.integers(16, 236, size=(NOISE_BAND_H, args.width), dtype=np.uint8)
            # 最後一步才蓋時戳,盡量貼近「取樣時刻」
            encode_stamp(y, time.time_ns() // 1_000_000)
            buf = Gst.Buffer.new_wrapped(frame.tobytes())
            buf.pts = idx * frame_dur_ns
            buf.duration = frame_dur_ns
            appsrc.emit("push-buffer", buf)
            idx += 1
            # 實時步調:對齊下一幀應送出的牆鐘時刻
            next_due = t_start + idx / args.fps
            delay = next_due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        appsrc.emit("end-of-stream")
        pipeline.set_state(Gst.State.NULL)
        loop.quit()

    if error:
        print(f"[sender] pipeline 錯誤:{error[0]}", file=sys.stderr)
        return 1
    print(f"[sender] 已推 {idx} 幀", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
