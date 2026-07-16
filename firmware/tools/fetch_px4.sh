#!/usr/bin/env bash
# 抓 PX4 upstream(釘版於 px4.lock)到 ${PX4_SRC};冪等:tag 相符即跳過。
# 配方對齊 onboard/ros2_ws/docker/Dockerfile.px4-sitl-dds(shallow + NuttX tag 陷阱解法)。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${DIR}/px4.lock"

PX4_SRC="${PX4_SRC:-${DIR}/.px4}"

if [[ -d "${PX4_SRC}/.git" ]]; then
    HAVE="$(git -C "${PX4_SRC}" describe --tags --exact-match 2>/dev/null || true)"
    if [[ "${HAVE}" == "${PX4_TAG}" ]]; then
        echo "[fetch-px4] ${PX4_SRC} 已在 ${PX4_TAG},跳過 clone"
        exit 0
    fi
    echo "[fetch-px4] ${PX4_SRC} 版本不符(${HAVE:-無 tag} ≠ ${PX4_TAG}),重抓" >&2
    rm -rf "${PX4_SRC}"
fi

echo "[fetch-px4] clone ${PX4_TAG}(shallow + shallow-submodules)→ ${PX4_SRC}"
git clone --depth 1 --recursive --shallow-submodules -b "${PX4_TAG}" \
    "${PX4_URL}" "${PX4_SRC}"

# NuttX tag 陷阱(見 px4.lock 註解)
git -C "${PX4_SRC}/platforms/nuttx/NuttX/nuttx" tag -f "${NUTTX_LOCAL_TAG}"
echo "[fetch-px4] 完成:$(git -C "${PX4_SRC}" describe --tags)"
