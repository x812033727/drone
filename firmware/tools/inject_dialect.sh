#!/usr/bin/env bash
# 把自訂 dialect 注入 PX4 mavlink submodule 的 message_definitions(冪等)。
# dialect XML 無法完全 out-of-tree:mavgen 於建置期在 submodule 目錄內解析。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${DIR}/.." && pwd)"
PX4_SRC="${PX4_SRC:-${DIR}/.px4}"

DEFS="${PX4_SRC}/src/modules/mavlink/mavlink/message_definitions/v1.0"
[[ -d "${DEFS}" ]] || { echo "[inject-dialect] 找不到 ${DEFS}(先 fetch)" >&2; exit 1; }

cp "${REPO_ROOT}/interfaces/mavlink/drone_custom.xml" "${DEFS}/"
cp "${DIR}/mavlink/drone_sitl.xml" "${DEFS}/"
echo "[inject-dialect] drone_custom.xml + drone_sitl.xml → ${DEFS}"
