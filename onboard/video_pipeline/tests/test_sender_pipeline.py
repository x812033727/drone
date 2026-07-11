"""pipeline 描述字串組裝與 --source 解析的純函式測試(不需 GStreamer)。"""

import pytest
from pipelines import (
    build_test_pipeline_desc,
    build_v4l2_pipeline_desc,
    parse_source,
)


def test_parse_source_test():
    assert parse_source("test") == ("test", None)


def test_parse_source_v4l2():
    assert parse_source("v4l2:/dev/video0") == ("v4l2", "/dev/video0")
    assert parse_source("v4l2:/dev/video12") == ("v4l2", "/dev/video12")


@pytest.mark.parametrize(
    "bad",
    ["", "TEST", "v4l2", "v4l2:", "v4l2:video0", "v4l2:dev/video0", "rtsp://x", "file:/dev/video0"],
)
def test_parse_source_rejects_bad_spec(bad):
    with pytest.raises(ValueError):
        parse_source(bad)


def test_build_test_pipeline_desc():
    desc = build_test_pipeline_desc(1280, 720, 25, 3000, "rtsp://127.0.0.1:8554/stream")
    # 源與 caps
    assert desc.startswith("appsrc name=src is-live=true block=true format=time ")
    assert "format=I420,width=1280,height=720,framerate=25/1" in desc
    # 編碼參數:zerolatency、碼率、GOP 對齊 fps、無 B 幀
    assert "x264enc tune=zerolatency speed-preset=ultrafast bitrate=3000" in desc
    assert "key-int-max=25" in desc
    assert "bframes=0" in desc
    assert "profile=constrained-baseline" in desc
    # 推流端:TCP + 目的地
    assert desc.endswith(
        "rtspclientsink name=sink protocols=tcp location=rtsp://127.0.0.1:8554/stream"
    )


def test_build_v4l2_pipeline_desc():
    desc = build_v4l2_pipeline_desc("/dev/video0", 4000, "rtsp://127.0.0.1:8554/stream")
    assert desc.startswith("v4l2src device=/dev/video0 ")
    assert "! videoconvert " in desc
    assert "x264enc tune=zerolatency speed-preset=ultrafast bitrate=4000" in desc
    # 錄存端(fMP4 分段)需要穩定關鍵幀間隔
    assert "key-int-max=30" in desc
    assert "bframes=0" in desc
    assert "! h264parse " in desc
    assert desc.endswith(
        "rtspclientsink name=sink protocols=tcp location=rtsp://127.0.0.1:8554/stream"
    )
    # v4l2 不強制 caps(解析度/幀率由相機協商)
    assert "video/x-raw" not in desc


def test_pipeline_descs_are_single_line():
    """Gst.parse_launch 吃單行描述:確保組裝結果無換行汙染。"""
    for desc in (
        build_test_pipeline_desc(1920, 1080, 30, 4000, "rtsp://h:1/s"),
        build_v4l2_pipeline_desc("/dev/video1", 2000, "rtsp://h:1/s"),
    ):
        assert "\n" not in desc
