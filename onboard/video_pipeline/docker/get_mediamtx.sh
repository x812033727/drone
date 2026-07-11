#!/usr/bin/env bash
# 下載並校驗 MediaMTX(版本與 checksum 釘死)。產物:docker/bin/mediamtx
set -euo pipefail

VERSION="v1.12.3"
SHA256="450d1172bf6708cbd630eada115ccfc33453227e16750369113d1dfe34f876d8"
ARCH="linux_amd64"   # Jetson(arm64)改 linux_arm64,checksum 需另查 release 頁

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${DIR}/bin"
BIN="${BIN_DIR}/mediamtx"

if [[ -x "${BIN}" ]] && "${BIN}" --version 2>/dev/null | grep -q "${VERSION}"; then
    echo "[get_mediamtx] 已存在 ${VERSION},略過下載"
    exit 0
fi

URL="https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_${ARCH}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "[get_mediamtx] 下載 ${URL}"
curl -fsSL -o "${TMP}/mediamtx.tar.gz" "${URL}"
echo "${SHA256}  ${TMP}/mediamtx.tar.gz" | sha256sum -c -

mkdir -p "${BIN_DIR}"
tar xzf "${TMP}/mediamtx.tar.gz" -C "${TMP}"
install -m 0755 "${TMP}/mediamtx" "${BIN}"
echo "[get_mediamtx] 完成:${BIN}($("${BIN}" --version))"
