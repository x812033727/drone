"""GStreamer pipeline 描述字串組裝(純函式,不依賴 gi,可單測)。

sender.py 依 --source 選用:
- test:appsrc 合成畫面(彩條+移動方塊+雜訊帶+像素時戳)
- v4l2:實體相機(v4l2src;解析度/幀率由相機協商,無像素時戳)
"""

from __future__ import annotations


def parse_source(spec: str) -> tuple[str, str | None]:
    """解析 --source 參數。

    "test" → ("test", None);"v4l2:/dev/videoN" → ("v4l2", "/dev/videoN")。
    其他格式 raise ValueError。
    """
    if spec == "test":
        return "test", None
    if spec.startswith("v4l2:"):
        device = spec[len("v4l2:") :]
        if not device.startswith("/dev/"):
            raise ValueError(f"v4l2 裝置路徑須以 /dev/ 開頭:{spec!r}")
        return "v4l2", device
    raise ValueError(f"不支援的 --source:{spec!r}(可用:test、v4l2:/dev/videoN)")


def build_test_pipeline_desc(
    width: int, height: int, fps: int, bitrate: int, rtsp_url: str
) -> str:
    """合成畫面路徑:appsrc(I420)→ x264 zerolatency → RTSP(TCP)。"""
    return (
        f"appsrc name=src is-live=true block=true format=time "
        f"caps=video/x-raw,format=I420,width={width},height={height},"
        f"framerate={fps}/1 "
        f"! videoconvert "
        f"! x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} "
        f"key-int-max={fps} bframes=0 "
        f"! video/x-h264,profile=constrained-baseline "
        f"! h264parse "
        f"! rtspclientsink name=sink protocols=tcp location={rtsp_url}"
    )


def build_v4l2_pipeline_desc(device: str, bitrate: int, rtsp_url: str) -> str:
    """實體相機路徑:v4l2src → x264 zerolatency → RTSP(TCP)。

    解析度/幀率由相機與 videoconvert 協商(不強制 caps);
    key-int-max=30 讓錄存端(fMP4 分段)與回放端有穩定的關鍵幀間隔。
    """
    return (
        f"v4l2src device={device} "
        f"! videoconvert "
        f"! x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} "
        f"key-int-max=30 bframes=0 "
        f"! h264parse "
        f"! rtspclientsink name=sink protocols=tcp location={rtsp_url}"
    )
