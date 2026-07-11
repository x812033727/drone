"""時戳編解碼純函式往返測試(不需 GStreamer)。"""

import numpy as np
import pytest
from stamp import (
    BLOCK,
    STRIP_HEIGHT,
    STRIP_WIDTH,
    decode_stamp,
    encode_stamp,
)


def _frame(h=1080, w=1920, fill=90):
    return np.full((h, w), fill, dtype=np.uint8)


# ts=0 不在列:0 是全暗幀盲點的保留值,decode 一律回 None(見下方盲點測試)
@pytest.mark.parametrize(
    "ts_ms",
    [1, 255, 1_752_200_000_123, 2**63, 2**64 - 1],
)
def test_roundtrip_exact(ts_ms):
    luma = _frame()
    encode_stamp(luma, ts_ms)
    assert decode_stamp(luma) == ts_ms


def test_roundtrip_min_size_frame():
    luma = _frame(h=STRIP_HEIGHT, w=STRIP_WIDTH)
    encode_stamp(luma, 123_456_789)
    assert decode_stamp(luma) == 123_456_789


def test_robust_to_compression_noise():
    """模擬有損編碼造成的亮度偏移(±30),仍應無誤讀回。"""
    ts_ms = 1_752_200_987_654
    luma = _frame()
    encode_stamp(luma, ts_ms)
    rng = np.random.default_rng(42)
    noise = rng.integers(-30, 31, size=luma.shape, dtype=np.int16)
    noisy = np.clip(luma.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    assert decode_stamp(noisy) == ts_ms


def test_corrupted_block_returns_none():
    """單一 bit 塊被翻轉(如花屏)→ checksum 擋下,回傳 None 而非錯值。"""
    luma = _frame()
    encode_stamp(luma, 1_752_200_000_000)
    # 完整翻轉第 3 個 bit 塊
    x0 = 3 * BLOCK
    region = luma[0:STRIP_HEIGHT, x0 : x0 + BLOCK]
    luma[0:STRIP_HEIGHT, x0 : x0 + BLOCK] = np.where(region > 128, 16, 235)
    assert decode_stamp(luma) is None


def test_all_dark_frame_returns_none():
    """全暗幀(全 0)每 bit 讀成 0 → payload 全零,XOR checksum 恰好也是 0,
    會「合法」解出 ts=0(實證毒化統計的盲點)→ 必須回 None。"""
    luma = np.zeros((64, 640), dtype=np.uint8)
    assert decode_stamp(luma) is None


def test_uniform_gray_below_threshold_returns_none():
    """全灰(亮度低於門檻 125)幀同樣解出全零 payload → 必須回 None。"""
    luma = _frame(h=64, w=640, fill=90)
    assert decode_stamp(luma) is None


def test_encoded_zero_ts_decodes_to_none():
    """ts=0 是盲點保留值:即使是自己編碼的 0,decode 也拒收。"""
    luma = _frame()
    encode_stamp(luma, 0)
    assert decode_stamp(luma) is None


def test_random_frame_returns_none():
    rng = np.random.default_rng(7)
    luma = rng.integers(0, 256, size=(64, 640), dtype=np.uint8)
    # 隨機畫面幾乎必然 checksum 不符;固定 seed 確保測試穩定
    assert decode_stamp(luma) is None


def test_encode_only_touches_strip():
    luma = _frame(fill=90)
    encode_stamp(luma, 1_752_200_000_000)
    assert (luma[STRIP_HEIGHT:, :] == 90).all()
    assert (luma[:STRIP_HEIGHT, STRIP_WIDTH:] == 90).all()


@pytest.mark.parametrize(
    ("shape", "dtype"),
    [
        ((4, 1920), np.uint8),  # 高度不足
        ((1080, 500), np.uint8),  # 寬度不足
        ((1080, 1920), np.float32),  # dtype 錯誤
    ],
)
def test_invalid_plane_raises(shape, dtype):
    luma = np.zeros(shape, dtype=dtype)
    with pytest.raises(ValueError):
        encode_stamp(luma, 0)
    with pytest.raises(ValueError):
        decode_stamp(luma)


def test_out_of_range_ts_raises():
    luma = _frame()
    with pytest.raises(ValueError):
        encode_stamp(luma, -1)
    with pytest.raises(ValueError):
        encode_stamp(luma, 2**64)
