# video_pipeline — 影像管線 POC + 端到端延遲量測方法論

> 對應規劃:[docs/20-software/companion-computer.md](../../docs/20-software/companion-computer.md) §2(video_pipeline,Phase 1)、
> [docs/20-software/architecture.md](../../docs/20-software/architecture.md)(影像走 WebRTC 上雲)

## 定位(誠實邊界,先讀這段)

本目錄是 **Phase 0 的 x86 POC**:在無 Jetson、無實體相機的環境下,把
「合成視訊源 → H.264 編碼 → 串流伺服器 → 訂閱端」的**傳輸架構**跑通,
並落地一套**毫秒級端到端延遲量測方法論**(像素內嵌時戳)。

**x86 軟編(x264)的延遲數字僅供方法論驗證與傳輸層基線,
不是 REQ-COM-03 的驗證結果。** REQ-COM-03(1080p/30fps,端到端延遲
< 250 ms 數傳 / < 500 ms 4G/5G)與 VT-COM-03(L2 端到端延遲儀測 + L4)
的正式驗證,必須在 Jetson(nvenc 硬編)+ 實體相機 + 實際數傳/4G5G 鏈路上
以**同一套量測方法論**執行——那是 Phase 1 的事。本 POC 的價值是:
到時候只換源和編碼器,量尺(時戳嵌入 + 統計腳本)直接沿用。

## 架構

```
┌──────────────────────────┐      RTSP(TCP)     ┌───────────────┐
│ sender.py                │  ─── publish ────▶  │  MediaMTX     │
│  appsrc(合成畫面+像素時戳) │                     │  v1.12.3      │
│  → videoconvert          │                     │  (單 binary)  │
│  → x264enc zerolatency   │                     └──────┬────────┘
│  → h264parse             │            RTSP :8554 ────┤(本 POC 量測腿)
│  → rtspclientsink        │            WebRTC :8889 ──┤(WHEP 信令驗證)
└──────────────────────────┘            (HLS 可開,POC 關閉)
                                                        │
                                     ┌──────────────────▼───────────┐
                                     │ measure_latency.py           │
                                     │  rtspsrc latency=0 → avdec   │
                                     │  → appsink 讀回像素時戳       │
                                     │  latency = now − stamped      │
                                     │  → p50/p90/p99/max(≥300 幀)│
                                     └──────────────────────────────┘
```

量測原理:sender 每幀在**左上角 576×8 px 時戳條**寫入當下 unix_time_ms
(72 個 8×8 二值亮度塊 = 8 bytes 時戳 + 1 byte XOR checksum,抗有損壓縮;
編解碼為純函式,見 [stamp.py](stamp.py),`tests/` 有不依賴 GStreamer 的往返測試)。
訂閱端解碼後讀回時戳,`latency = 收到解碼完成當下 − 嵌入時刻`,涵蓋
取樣→編碼→推流→伺服器轉發→拉流→解碼全程(即玻璃到玻璃再扣顯示)。

> 設計備註:規劃時原想「每 byte 一個灰階塊」,但 256 級灰階經 H.264 有損
> 壓縮必然出錯,改為每 bit 一個二值塊(容錯 ±100 luma)+ checksum 擋花屏幀。

## 快速開始(x86,Ubuntu 24.04)

```bash
# 依賴(host apt 路線;見下方「選型落地」)
sudo apt install python3-gi python3-numpy gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 gstreamer1.0-tools gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    gstreamer1.0-rtsp

./run_poc.sh          # 一鍵:MediaMTX → sender → 300 幀量測 → WHEP 檢查 → 清理
```

埠被占時:`RTSP_PORT=18554 WEBRTC_PORT=18889 API_PORT=19997 ./run_poc.sh`。
其他參數:`FRAMES/WIDTH/HEIGHT/FPS/BITRATE` 環境變數。
單元測試:repo 根 `pytest onboard/video_pipeline/`;lint:`ruff check .`。
本 POC **不納 CI**(需下載 MediaMTX + GStreamer 全家桶,價值低),
`run_poc.sh` 為本地驗證入口。

## x86 基線實測(2026-07-11)

環境:AMD EPYC 9354P(8 vCPU)、Ubuntu 24.04、GStreamer 1.24.2、
MediaMTX v1.12.3、**同機 loopback**、1080p30、x264 ultrafast+zerolatency
4 Mbps、每幀 300 樣本(另跳過前 30 幀暫態)、時鐘同機零漂移。

| 輪次 | p50 | p90 | p99 | max | 解碼失敗 |
|------|-----|-----|-----|-----|---------|
| run 1 | 13.5 ms | 17.4 ms | 24.1 ms | 25.7 ms | 0/300 |
| run 2 | 13.2 ms | 18.6 ms | 29.5 ms | 46.9 ms | 0/300 |

WebRTC 腿:同一路流的 WHEP endpoint(`POST /stream/whep`)以手工 SDP offer
協商 → **HTTP 201 + 含 `m=video` H264 的 answer**(信令層可協商);
不存在路徑正確回 4xx。ICE/DTLS/媒體面播放為 Phase 1 實機項(方法論同上)。

**這些數字說明的是**:MediaMTX 轉發 + RTSP(TCP)協議棧在理想鏈路下的
基線開銷(~15 ms 上下)遠小於 250 ms 預算,量測方法論(像素時戳 300 幀
0 解碼失敗)可靠。**這些數字不能說明**:實際鏈路(數傳/4G5G 的 RTT、抖動、
丟包重傳)、相機曝光/ISP、Jetson 編碼延遲——這些是 Phase 1 實測的主體,
預算大頭在鏈路而非伺服器轉發。

## Jetson 遷移點(Phase 1)

| POC(x86) | Jetson 實機 | 備註 |
|-----------|-------------|------|
| appsrc 合成畫面 | `v4l2src` / `nvarguscamerasrc`(CSI) | 時戳改由量測治具(拍攝毫秒鐘/LED 陣列)或相機時戳注入 |
| `x264enc tune=zerolatency` | `nvv4l2h264enc`(nvenc 硬編) | 釋放 CPU;H.265 換 `nvv4l2h265enc`(規劃為 H.265) |
| `videoconvert` | `nvvidconv`(NVMM 零拷貝) | 避免 CPU 搬幀 |
| 同機 loopback | 數傳 / 4G5G 實鏈路 | **跨機量測必須 PTP/NTP 對時**,時鐘誤差直接進數字;機上已規劃 PPS/PTP |
| RTSP 訂閱量測 | WebRTC(機→雲)為主 | 方法論不變:解碼幀讀時戳;瀏覽器端可用 canvas 讀像素 |
| WHEP 信令驗證 | 完整 WebRTC 播放 + NAT 穿透 | 含 STUN/TURN、4G5G NAT 行為 |

另注意:合成畫面(彩條+雜訊帶)的編碼負載與真實相機畫面不同,
x86 軟編數字對「編碼延遲」不具代表性,只作傳輸層參考。

## 檔案

| 檔案 | 說明 |
|------|------|
| [stamp.py](stamp.py) | 像素時戳編解碼純函式(`encode_stamp`/`decode_stamp`,numpy) |
| [sender.py](sender.py) | 推流端:合成畫面+時戳 → x264 → RTSP(`--width/--height/--fps/--bitrate/--rtsp-url`) |
| [measure_latency.py](measure_latency.py) | 量測端:拉流解碼讀時戳 → 統計(`--rtsp-url --frames --json`) |
| [run_poc.sh](run_poc.sh) | 一鍵跑通 + WHEP 檢查 + 清理 |
| [docker/get_mediamtx.sh](docker/get_mediamtx.sh) | MediaMTX v1.12.3 下載(SHA-256 釘死校驗) |
| [docker/mediamtx.yml](docker/mediamtx.yml) | 最小設定:RTSP + WebRTC + API,其餘協議關閉 |
| [tests/test_stamp.py](tests/test_stamp.py) | 時戳往返/抗噪/損毀偵測測試(不需 GStreamer) |

選型落地:**host apt 路線**(Ubuntu 24.04 apt 的 PyGObject + GStreamer 1.24
即可跑,未走 docker;`docker/` 目錄僅放 MediaMTX 取得腳本與設定)。
MediaMTX v1.12.3(Apache-2.0,單 binary),
SHA-256 `450d1172bf6708cbd630eada115ccfc33453227e16750369113d1dfe34f876d8`
(linux_amd64)。量測端 `rtspsrc` 須顯式 `latency=0`
(預設 jitterbuffer 2000 ms 會把量測整個蓋掉)。
