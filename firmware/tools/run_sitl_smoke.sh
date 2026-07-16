#!/usr/bin/env bash
# SIH 煙霧:背景起自建 px4_sitl(sihsim_quadx,headless)→ 等 heartbeat → 收斂清理。
# SIH 動力學在 PX4 內部模擬(免 Gazebo,秒級就緒);與 Dockerfile.px4-sitl-dds
# 的 CMD 同一啟動路徑(make px4_sitl sihsim_quadx,detached/無 TTY 實測可跑)。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_SRC="${PX4_SRC:-${DIR}/.px4}"
HEARTBEAT_PORT="${HEARTBEAT_PORT:-14540}"
HEARTBEAT_TIMEOUT="${HEARTBEAT_TIMEOUT:-90}"
PX4_LOG="${PX4_LOG:-$(mktemp /tmp/px4-sih-smoke.XXXXXX.log)}"

PX4_PID=""
cleanup() {
    rc=$?
    if [[ ${rc} -ne 0 ]]; then
        echo "[sitl-smoke] 失敗(exit ${rc}),px4 log 尾段:" >&2
        tail -50 "${PX4_LOG}" >&2 || true
    fi
    # 殺整個行程群(make → sitl 包裝 → px4)
    if [[ -n "${PX4_PID}" ]]; then
        kill -- -"${PX4_PID}" 2>/dev/null || kill "${PX4_PID}" 2>/dev/null || true
    fi
    pkill -x px4 2>/dev/null || true
}
trap cleanup EXIT

# --- dialect 生成標頭斷言(patch 0001 + inject_dialect 的建置期硬證)---
GEN_DIR="${PX4_SRC}/build/px4_sitl_default/mavlink"
for h in spray_telemetry battery_detail payload_status; do
    if ! find "${GEN_DIR}" -name "mavlink_msg_${h}.h" | grep -q .; then
        echo "[sitl-smoke] 自訂 dialect 標頭未生成:mavlink_msg_${h}.h(${GEN_DIR})" >&2
        exit 1
    fi
done
echo "[sitl-smoke] dialect 生成標頭 OK(drone_sitl)"

echo "[sitl-smoke] 起 SIH(headless,log=${PX4_LOG})"
(
    cd "${PX4_SRC}"
    exec env HEADLESS=1 PX4_SYS_AUTOSTART=10040 PX4_SIM_MODEL=sihsim_quadx \
        setsid make px4_sitl sihsim_quadx
) </dev/null >"${PX4_LOG}" 2>&1 &
PX4_PID=$!

echo "[sitl-smoke] 等 heartbeat(udpin:${HEARTBEAT_PORT},上限 ${HEARTBEAT_TIMEOUT}s)"
python3 "${DIR}/tools/smoke/wait_heartbeat.py" \
    --port "${HEARTBEAT_PORT}" --timeout "${HEARTBEAT_TIMEOUT}"

# --- out-of-tree 模組斷言(SMOKE_MODULES 逗號分隔;預設 payload_sim)---
# px4-<cmd> 為 SITL client shim,連上運行中的 instance 0。
BIN_DIR="${PX4_SRC}/build/px4_sitl_default/bin"
SMOKE_MODULES="${SMOKE_MODULES:-payload_sim}"
SMOKE_TOPICS="${SMOKE_TOPICS:-drone_payload_status,drone_spray_status,drone_battery_detail}"
IFS=',' read -ra MODS <<< "${SMOKE_MODULES}"
for mod in "${MODS[@]}"; do
    [[ -x "${BIN_DIR}/px4-${mod}" ]] || { echo "[sitl-smoke] 缺 client shim px4-${mod}(模組未建進?)" >&2; exit 1; }
    "${BIN_DIR}/px4-${mod}" start >/dev/null 2>&1 || true   # 已啟動時容忍
    "${BIN_DIR}/px4-${mod}" status
done
sleep 2   # 讓 1 Hz 發布器出至少一筆
IFS=',' read -ra TOPICS <<< "${SMOKE_TOPICS}"
for topic in "${TOPICS[@]}"; do
    OUT="$("${BIN_DIR}/px4-listener" "${topic}" 2>&1 || true)"
    if ! grep -q "timestamp" <<< "${OUT}"; then
        echo "[sitl-smoke] uORB topic ${topic} 無資料:${OUT}" >&2
        exit 1
    fi
    echo "[sitl-smoke] uORB ${topic} OK"
done

echo "[sitl-smoke] PASS:自建 px4_sitl(SIH)起機 + heartbeat + out-of-tree 模組/uORB"
