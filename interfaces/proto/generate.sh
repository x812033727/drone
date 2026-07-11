#!/usr/bin/env bash
# 由 .proto 產生 Python 生成碼至 gen/python/(生成碼 commit 進版控)。
#
# 用法:
#   pip install -r interfaces/proto/requirements-dev.txt   # 固定版 grpcio-tools
#   bash interfaces/proto/generate.sh
#
# CI 會重跑本腳本並 `git diff --exit-code interfaces/proto/gen/`,
# 確保生成碼與 schema 同步且工具鏈版本一致。
set -euo pipefail

cd "$(dirname "$0")"

OUT=gen/python

# 清掉舊生成碼,避免殘留已刪除的訊息檔
rm -rf "${OUT}/drone"
mkdir -p "${OUT}"

python3 -m grpc_tools.protoc \
  -I . \
  --python_out="${OUT}" \
  --pyi_out="${OUT}" \
  drone/v1/telemetry.proto \
  drone/v1/mission.proto

# 串好 package,讓 `from drone.v1 import telemetry_pb2` 可用
touch "${OUT}/drone/__init__.py" "${OUT}/drone/v1/__init__.py"

echo "OK: 生成碼已輸出至 interfaces/proto/${OUT}/drone/v1/"
