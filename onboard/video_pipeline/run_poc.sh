#!/usr/bin/env bash
# 一鍵 POC:起 MediaMTX → sender 推流 → measure 量測 → WHEP 檢查 → 清理。
# 埠被占時以環境變數改埠:RTSP_PORT / WEBRTC_PORT / WEBRTC_UDP_PORT / API_PORT
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RTSP_PORT="${RTSP_PORT:-8554}"
WEBRTC_PORT="${WEBRTC_PORT:-8889}"
WEBRTC_UDP_PORT="${WEBRTC_UDP_PORT:-8189}" # WebRTC ICE 單一 UDP 埠(webrtcLocalUDPAddress)
API_PORT="${API_PORT:-9997}"
FRAMES="${FRAMES:-300}"
WIDTH="${WIDTH:-1920}" HEIGHT="${HEIGHT:-1080}" FPS="${FPS:-30}" BITRATE="${BITRATE:-4000}"
RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/stream"

# 暫存檔帶 PID 前綴,避免並行執行互踩固定檔名(/tmp/poc_*)
TMP_PREFIX="${TMPDIR:-/tmp}/poc_$$"
MTX_LOG="${TMP_PREFIX}_mediamtx.log"
LATENCY_JSON="${TMP_PREFIX}_latency.json"
WHEP_ANSWER="${TMP_PREFIX}_whep_answer.sdp"

MTX_PID="" SENDER_PID=""
cleanup() {
    rc=$?
    [[ -n "${SENDER_PID}" ]] && kill "${SENDER_PID}" 2>/dev/null || true
    [[ -n "${MTX_PID}" ]] && kill "${MTX_PID}" 2>/dev/null || true
    wait 2>/dev/null || true
    if [[ ${rc} -eq 0 ]]; then
        # 成功:統計已印到 stdout,清掉暫存檔(統計 json 保留供後續取用)
        rm -f "${MTX_LOG}" "${WHEP_ANSWER}"
    else
        echo "[poc] 失敗(exit ${rc}),診斷檔保留:${TMP_PREFIX}_*" >&2
    fi
}
trap cleanup EXIT INT TERM

# --- 0. 埠占用檢查 ---
# grep 不用 -q:pipefail 下 grep -q 提前退出會讓 ss 吃 SIGPIPE(exit 141),
# 整條 pipeline 非零 → if 判斷反轉(占用被誤判為空閒)。
for p in "${RTSP_PORT}" "${WEBRTC_PORT}" "${API_PORT}"; do
    if ss -tln "sport = :${p}" 2>/dev/null | grep LISTEN >/dev/null; then
        echo "[poc] 埠 ${p} 已被占用;請以 RTSP_PORT/WEBRTC_PORT/API_PORT 環境變數改埠" >&2
        exit 1
    fi
done
# WebRTC ICE 用的單一 UDP 埠也要檢查(被占時 WHEP 信令仍會 201,實際媒體面才失敗)
if ss -uln "sport = :${WEBRTC_UDP_PORT}" 2>/dev/null | grep UNCONN >/dev/null; then
    echo "[poc] UDP 埠 ${WEBRTC_UDP_PORT}(WebRTC ICE)已被占用;請以 WEBRTC_UDP_PORT 環境變數改埠" >&2
    exit 1
fi

# --- 1. MediaMTX ---
"${DIR}/docker/get_mediamtx.sh"
MTX_RTSPADDRESS=":${RTSP_PORT}" MTX_WEBRTCADDRESS=":${WEBRTC_PORT}" \
    MTX_WEBRTCLOCALUDPADDRESS=":${WEBRTC_UDP_PORT}" \
    MTX_APIADDRESS="127.0.0.1:${API_PORT}" \
    "${DIR}/docker/bin/mediamtx" "${DIR}/docker/mediamtx.yml" >"${MTX_LOG}" 2>&1 &
MTX_PID=$!
MTX_READY=""
for _ in $(seq 1 50); do
    curl -fsS "http://127.0.0.1:${API_PORT}/v3/paths/list" >/dev/null 2>&1 && { MTX_READY=1; break; }
    kill -0 "${MTX_PID}" 2>/dev/null || { echo "[poc] MediaMTX 啟動失敗,見 ${MTX_LOG}" >&2; exit 1; }
    sleep 0.2
done
# 輪詢耗盡也要有終判:進程活著但 API 一直不通(如埠被防火牆擋)不得放行
if [[ -z "${MTX_READY}" ]]; then
    echo "[poc] 等待 MediaMTX 就緒逾時,log 如下:" >&2
    tail -n 30 "${MTX_LOG}" >&2 || true
    exit 1
fi
echo "[poc] MediaMTX 就緒(rtsp:${RTSP_PORT} webrtc:${WEBRTC_PORT} ice-udp:${WEBRTC_UDP_PORT})"

# --- 2. sender 推流 ---
python3 "${DIR}/sender.py" --width "${WIDTH}" --height "${HEIGHT}" --fps "${FPS}" \
    --bitrate "${BITRATE}" --rtsp-url "${RTSP_URL}" &
SENDER_PID=$!

# 等 path 就緒(sender RECORD session 建立)再啟動量測端,避免 rtspsrc 404
for _ in $(seq 1 100); do
    READY=$(curl -fsS "http://127.0.0.1:${API_PORT}/v3/paths/get/stream" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ready"))' 2>/dev/null || true)
    [[ "${READY}" == "True" ]] && break
    kill -0 "${SENDER_PID}" 2>/dev/null || { echo "[poc] sender 啟動失敗" >&2; exit 1; }
    sleep 0.2
done
if [[ "${READY:-}" != "True" ]]; then
    echo "[poc] 等待串流就緒逾時" >&2
    exit 1
fi

# --- 3. 端到端延遲量測 ---
python3 "${DIR}/measure_latency.py" --rtsp-url "${RTSP_URL}" --frames "${FRAMES}" --json \
    | tee "${LATENCY_JSON}"

# --- 4. WebRTC(WHEP)腿檢查:同一路流可被 WebRTC 協商訂閱 ---
# 以手工 SDP offer 走 WHEP 信令,期望 201 + 含 video section 的 answer。
# 只驗信令層可協商(POC 範圍);ICE/DTLS/媒體面實跑列為 Phase 1 實機項。
echo "[poc] WebRTC 檢查:"
PATH_STATE=$(curl -fsS "http://127.0.0.1:${API_PORT}/v3/paths/get/stream" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ready"], [t for t in d["tracks"]])')
echo "[poc]   path ready + tracks: ${PATH_STATE}"
OFFER=$'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\n'
OFFER+=$'a=ice-ufrag:pocpoc12\r\na=ice-pwd:pocpocpocpocpocpocpocpoc\r\n'
OFFER+=$'a=fingerprint:sha-256 4A:AD:B9:B1:3F:82:18:3B:54:02:12:DF:3E:5D:49:6B:19:E5:7C:AB:11:22:33:44:55:66:77:88:99:AA:BB:CC\r\n'
OFFER+=$'m=video 9 UDP/TLS/RTP/SAVPF 96\r\nc=IN IP4 0.0.0.0\r\na=mid:0\r\na=recvonly\r\n'
OFFER+=$'a=rtpmap:96 H264/90000\r\na=fmtp:96 packetization-mode=1;profile-level-id=42e01f\r\n'
OFFER+=$'a=setup:actpass\r\na=rtcp-mux\r\n'
WHEP_CODE=$(printf '%s' "${OFFER}" | curl -s -o "${WHEP_ANSWER}" -w '%{http_code}' \
    -X POST -H 'Content-Type: application/sdp' --data-binary @- \
    "http://127.0.0.1:${WEBRTC_PORT}/stream/whep")
NOSTREAM_CODE=$(printf '%s' "${OFFER}" | curl -s -o /dev/null -w '%{http_code}' \
    -X POST -H 'Content-Type: application/sdp' --data-binary @- \
    "http://127.0.0.1:${WEBRTC_PORT}/no_such_stream/whep")
echo "[poc]   WHEP:POST /stream/whep → HTTP ${WHEP_CODE}(應 201=協商成功," \
     "answer 存於 ${WHEP_ANSWER});不存在路徑 → HTTP ${NOSTREAM_CODE}(應 400/404)"
if [[ "${WHEP_CODE}" != "201" ]] || ! grep -q '^m=video' "${WHEP_ANSWER}" \
    || [[ "${NOSTREAM_CODE}" != "400" && "${NOSTREAM_CODE}" != "404" ]]; then
    echo "[poc] WHEP 檢查未通過" >&2
    exit 1
fi
echo "[poc] 完成。統計:${LATENCY_JSON}(保留;其餘暫存檔由 trap 清理)"
