#!/usr/bin/env bash
# 吊銷裝置憑證(失竊/退役)並更新 CRL。
# 用法:[PKI_CA_DIR=/path] cloud/pki/revoke_device.sh <serial>
set -euo pipefail

SERIAL="${1:?用法: revoke_device.sh <serial>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PKI_CA_DIR="${PKI_CA_DIR:-$HERE/ca}"
CONF="$HERE/openssl.cnf"
export PKI_SAN="${PKI_SAN:-DNS:placeholder}"
CERT="$PKI_CA_DIR/issued/$SERIAL.cert.pem"

if [ ! -f "$CERT" ]; then
  echo "錯誤:找不到憑證 $CERT" >&2
  exit 1
fi

openssl ca -config "$CONF" -revoke "$CERT"
"$HERE/gen_crl.sh"
echo "✓ 已吊銷 $SERIAL 並更新 CRL(fleet-svc 應把 device.status 設為 revoked)"
