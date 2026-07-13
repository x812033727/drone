#!/usr/bin/env bash
# 為 broker(MQTT mTLS 監聽器)簽發伺服器憑證(serverAuth,SAN=hostname)。
# 用法:[PKI_CA_DIR=/path] cloud/pki/issue_server.sh <hostname> [extra_san]
#   例:issue_server.sh mosquitto localhost   → SAN=DNS:mosquitto,DNS:localhost
set -euo pipefail

HOST="${1:?用法: issue_server.sh <hostname> [extra_san_dns]}"
EXTRA="${2:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PKI_CA_DIR="${PKI_CA_DIR:-$HERE/ca}"
CONF="$HERE/openssl.cnf"
export PKI_SAN="${PKI_SAN:-DNS:placeholder}"
OUT="$PKI_CA_DIR/issued"

if [ ! -f "$PKI_CA_DIR/private/ca.key.pem" ]; then
  echo "錯誤:CA 未初始化,先跑 init_ca.sh" >&2
  exit 1
fi

SAN="DNS:$HOST"
[ -n "$EXTRA" ] && SAN="$SAN,DNS:$EXTRA"

openssl genrsa -out "$OUT/$HOST.server.key.pem" 2048
chmod 400 "$OUT/$HOST.server.key.pem"
openssl req -config "$CONF" -key "$OUT/$HOST.server.key.pem" -new -sha256 \
  -subj "/CN=$HOST" -out "$OUT/$HOST.server.csr.pem"
PKI_SAN="$SAN" openssl ca -config "$CONF" -batch -extensions server_cert \
  -days 365 -notext -md sha256 \
  -in "$OUT/$HOST.server.csr.pem" -out "$OUT/$HOST.server.cert.pem"
rm -f "$OUT/$HOST.server.csr.pem"
echo "✓ 伺服器憑證已簽發:$OUT/$HOST.server.cert.pem (SAN=$SAN)"
