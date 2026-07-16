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

echo "[sitl-smoke] PASS:自建 px4_sitl(SIH)起機 + heartbeat"
