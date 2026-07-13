#!/usr/bin/env bash
# 產出軟體物料單(SBOM):SPDX + CycloneDX 兩種格式。
# 對 docs/20-software/security.md §6(SBOM 隨版本歸檔——歐盟 CRA 與美國政府採購前置)。
#
# 需 syft(https://github.com/anchore/syft)。用法:
#   tools/gen_sbom.sh [輸出目錄]        # 預設 ./sbom
#
# 掃描範圍為整個 repo(dir:.):各子系統 requirements/pyproject 的 Python 依賴、
# GitHub Actions 版本、前端 package-lock 等宣告的軟體元件。
set -euo pipefail

OUT="${1:-sbom}"
VERSION="${2:-dev}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

if ! command -v syft >/dev/null 2>&1; then
  echo "錯誤:找不到 syft。安裝見 https://github.com/anchore/syft" >&2
  exit 1
fi

echo "產出 SBOM(掃描 $ROOT,版本 $VERSION)..."
syft "dir:$ROOT" --source-name drone-platform --source-version "$VERSION" \
                 -o "spdx-json=$OUT/drone-sbom.spdx.json" \
                 -o "cyclonedx-json=$OUT/drone-sbom.cyclonedx.json"
echo "✓ SBOM 已產出:"
echo "  $OUT/drone-sbom.spdx.json"
echo "  $OUT/drone-sbom.cyclonedx.json"
