#!/usr/bin/env bash
# S21 影像錄存回放煙霧測試(本地/CI 共用):
#   起 mediamtx → ffmpeg 推 10 秒測試流 → 回放 /list 有時段 → /get 下載片段
#   → ffprobe 驗 h264 且時長 ≥ 8 s → down -v 清理。
# 需要:docker compose plugin、ffmpeg/ffprobe、curl、python3。
# 本地跑請用隔離埠與獨特 project 名(CLAUDE.md 鐵則 8),例:
#   RTSP_PORT=38554 PLAYBACK_PORT=39996 MTX_API_PORT=39997 \
#     COMPOSE_PROJECT=vsmoke-$$ ./video_smoke.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RTSP_PORT="${RTSP_PORT:-8554}"
PLAYBACK_PORT="${PLAYBACK_PORT:-9996}"
MTX_API_PORT="${MTX_API_PORT:-9997}"
PROJECT="${COMPOSE_PROJECT:-video-smoke}"
WORK="$(mktemp -d)"

# MediaMTX 認證憑證:須與 docker-compose.yml mediamtx.environment 的預設一致
# (兩邊都用同一組環境變數;compose 以 ${VAR:-default} 兜底,這裡的 :-default
#  必須與之相同,否則推流會 401)。推流(publish)帶 publish 帳密;
# 回放 /list、/get 走 any(playback,宿主埠綁 loopback)不需帳密。
VIDEO_PUBLISH_USER="${VIDEO_PUBLISH_USER:-publisher}"
VIDEO_PUBLISH_PASS="${VIDEO_PUBLISH_PASS:-dronedev-publish}"
VIDEO_READ_USER="${VIDEO_READ_USER:-reader}"
VIDEO_READ_PASS="${VIDEO_READ_PASS:-dronedev-read}"

# CI 用 compose plugin;部分主機只有 docker-compose v2 binary,自動擇一
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
else
    COMPOSE=(docker-compose)
fi

compose() {
    RTSP_PORT="${RTSP_PORT}" PLAYBACK_PORT="${PLAYBACK_PORT}" MTX_API_PORT="${MTX_API_PORT}" \
        VIDEO_PUBLISH_USER="${VIDEO_PUBLISH_USER}" VIDEO_PUBLISH_PASS="${VIDEO_PUBLISH_PASS}" \
        VIDEO_READ_USER="${VIDEO_READ_USER}" VIDEO_READ_PASS="${VIDEO_READ_PASS}" \
        "${COMPOSE[@]}" -f "${DIR}/docker-compose.yml" --project-directory "${DIR}" \
        -p "${PROJECT}" "$@"
}

cleanup() {
    rc=$?
    if [[ ${rc} -ne 0 ]]; then
        echo "[video-smoke] 失敗(exit ${rc}),mediamtx 日誌:" >&2
        compose logs --tail 100 mediamtx >&2 || true
    fi
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "${WORK}"
    # 不在 trap 內 exit:保留原始退出碼
}
trap cleanup EXIT

echo "[video-smoke] 起 mediamtx(project=${PROJECT} rtsp:${RTSP_PORT}" \
    "playback:${PLAYBACK_PORT} api:${MTX_API_PORT})"
# 官方 image 無 healthcheck:--wait 只等 running,就緒改由 host 輪詢已發布 API 埠
compose up -d --wait mediamtx

READY=""
for _ in $(seq 1 75); do
    curl -fsS "http://127.0.0.1:${MTX_API_PORT}/v3/paths/list" >/dev/null 2>&1 && { READY=1; break; }
    sleep 0.2
done
if [[ -z "${READY}" ]]; then
    echo "[video-smoke] 等待 MediaMTX API 就緒逾時" >&2
    exit 1
fi
echo "[video-smoke] MediaMTX 就緒,推 10 秒測試流"

# 推流(-re 實時步調;testsrc2 有跨幀運動,編碼負載較真實)。
# 必須 -rtsp_transport tcp:預設 UDP 的 RTP 埠(8000/8001)未發布到宿主,
# 媒體包進不了容器 → 錄不到任何幀(session 卻建得起來,極易誤判)。
# 推流 URL 帶 publish 帳密(authInternalUsers 已關匿名,無帳密會 401 ANNOUNCE)。
ffmpeg -hide_banner -loglevel error -re -f lavfi -i testsrc2=size=1280x720:rate=30 \
    -t 10 -c:v libx264 -preset ultrafast -tune zerolatency \
    -f rtsp -rtsp_transport tcp \
    "rtsp://${VIDEO_PUBLISH_USER}:${VIDEO_PUBLISH_PASS}@127.0.0.1:${RTSP_PORT}/stream"

# 收流結束後 mediamtx 需片刻把最後的 part 落盤
sleep 2

# --- 回放 /list:應回非空時段陣列 ---
LIST="$(curl -fsS "http://127.0.0.1:${PLAYBACK_PORT}/list?path=stream")"
echo "[video-smoke] /list → ${LIST}"
START="$(python3 -c '
import json, sys
segs = json.loads(sys.argv[1])
assert isinstance(segs, list) and segs, "/list 回空陣列"
seg = segs[0]
assert seg["duration"] > 0, f"時段 duration 異常:{seg}"
print(seg["start"])
' "${LIST}")"
echo "[video-smoke] 錄存時段 start=${START}"

# --- 回放 /get:下載片段(start 含時區/毫秒,一律 URL-encode)---
curl -fsS -G -o "${WORK}/seg.mp4" \
    --data-urlencode "path=stream" \
    --data-urlencode "start=${START}" \
    --data-urlencode "duration=10" \
    --data-urlencode "format=mp4" \
    "http://127.0.0.1:${PLAYBACK_PORT}/get"
ls -l "${WORK}/seg.mp4"

# --- ffprobe 斷言:h264 且時長 ≥ 8 s(推了 10 s,容忍頭尾修整)---
CODEC="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name \
    -of csv=p=0 "${WORK}/seg.mp4")"
DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${WORK}/seg.mp4")"
echo "[video-smoke] ffprobe:codec=${CODEC} duration=${DUR}s"
[[ "${CODEC}" == "h264" ]] || { echo "[video-smoke] codec 非 h264" >&2; exit 1; }
python3 -c "import sys; sys.exit(0 if float('${DUR}') >= 8.0 else 1)" \
    || { echo "[video-smoke] 片段時長 ${DUR}s < 8s" >&2; exit 1; }

echo "[video-smoke] PASS:推流→錄存→/list→/get→ffprobe 全通"
