"""像素時戳編解碼(純函式,不依賴 GStreamer,numpy 即可測)。

原理:把 unix_time_ms(uint64, big-endian)+ 1 byte XOR checksum 共 9 bytes
展開成 72 個 bit,每個 bit 佔畫面左上角一個 8×8 純色亮度塊
(1 → 亮 235,0 → 暗 16,BT.601 studio range)。

為何以 bit 為單位而非「每 byte 一個灰階塊」:有損編碼(H.264)會使亮度值
偏移數個 level,256 級灰階直接讀回必然出錯;二值塊有 ±100 以上的容錯,
經過 x264/nvenc 壓縮後仍可無誤讀回。checksum 用於偵測殘餘錯誤
(如切到 I/P 邊界的花屏幀),解不回就丟棄該幀樣本。

跨機量測時,推流端與量測端需以 PTP/NTP 對時(詳 README)。
"""

from __future__ import annotations

import struct

import numpy as np

BLOCK = 8  # 每 bit 的方塊邊長(px)
STAMP_BYTES = 9  # 8 bytes unix_time_ms + 1 byte XOR checksum
STAMP_BITS = STAMP_BYTES * 8  # 72
STRIP_WIDTH = STAMP_BITS * BLOCK  # 576 px
STRIP_HEIGHT = BLOCK  # 8 px

_LUMA_HIGH = 235
_LUMA_LOW = 16
_THRESHOLD = (_LUMA_HIGH + _LUMA_LOW) // 2


def _check_plane(luma: np.ndarray) -> None:
    if luma.ndim != 2:
        raise ValueError(f"luma 需為 2D 陣列,收到 ndim={luma.ndim}")
    if luma.dtype != np.uint8:
        raise ValueError(f"luma 需為 uint8,收到 {luma.dtype}")
    h, w = luma.shape
    if h < STRIP_HEIGHT or w < STRIP_WIDTH:
        raise ValueError(f"畫面至少需 {STRIP_WIDTH}x{STRIP_HEIGHT},收到 {w}x{h}")


def _payload(ts_ms: int) -> bytes:
    raw = struct.pack(">Q", ts_ms)
    checksum = 0
    for b in raw:
        checksum ^= b
    return raw + bytes([checksum])


def encode_stamp(luma: np.ndarray, ts_ms: int) -> None:
    """把 ts_ms 寫入 luma 平面左上角的時戳條(就地修改)。"""
    _check_plane(luma)
    if not 0 <= ts_ms < 2**64:
        raise ValueError(f"ts_ms 需在 uint64 範圍內,收到 {ts_ms}")
    payload = _payload(ts_ms)
    for i in range(STAMP_BITS):
        bit = (payload[i // 8] >> (7 - i % 8)) & 1
        x0 = i * BLOCK
        luma[0:STRIP_HEIGHT, x0 : x0 + BLOCK] = _LUMA_HIGH if bit else _LUMA_LOW


def decode_stamp(luma: np.ndarray) -> int | None:
    """讀回 luma 左上角時戳條。checksum 不符(幀損毀)回傳 None。"""
    _check_plane(luma)
    # 只取每塊中央 4×4 均值,避開壓縮/去塊效應造成的邊緣暈染
    c0 = (BLOCK - 4) // 2
    data = bytearray(STAMP_BYTES)
    for i in range(STAMP_BITS):
        x0 = i * BLOCK
        block = luma[c0 : c0 + 4, x0 + c0 : x0 + c0 + 4]
        if float(block.mean()) > _THRESHOLD:
            data[i // 8] |= 1 << (7 - i % 8)
    raw, checksum = bytes(data[:8]), data[8]
    expected = 0
    for b in raw:
        expected ^= b
    if checksum != expected:
        return None
    return struct.unpack(">Q", raw)[0]
