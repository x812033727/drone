#!/usr/bin/env bash
# 依序套用 firmware/patches/*.patch 到 ${PX4_SRC}(git apply --3way,失敗即紅)。
# patch 數量 = firmware.md §1「≤20 commits」預算的量尺;>10 時啟動 fork repo
# 決策(見 firmware/README.md)。冪等:已套用過(reverse 檢查通過)則跳過。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_SRC="${PX4_SRC:-${DIR}/.px4}"

shopt -s nullglob
PATCHES=("${DIR}/patches/"*.patch)
if [[ ${#PATCHES[@]} -eq 0 ]]; then
    echo "[apply-patches] 無 patch,跳過"
    exit 0
fi

for p in "${PATCHES[@]}"; do
    name="$(basename "${p}")"
    if git -C "${PX4_SRC}" apply --reverse --check "${p}" >/dev/null 2>&1; then
        echo "[apply-patches] ${name} 已套用,跳過"
        continue
    fi
    echo "[apply-patches] 套用 ${name}"
    git -C "${PX4_SRC}" apply --3way "${p}"
done
echo "[apply-patches] 完成(共 ${#PATCHES[@]} 個 patch)"
