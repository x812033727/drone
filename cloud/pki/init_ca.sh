#!/usr/bin/env bash
# 初始化 Drone Fleet 根 CA(離線根,私鑰不出此目錄)。
# 用法:[PKI_CA_DIR=/path] cloud/pki/init_ca.sh
# 對 security.md §2:根 CA 私鑰離線保管;裝置憑證由此 CA 簽發。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
export PKI_CA_DIR="${PKI_CA_DIR:-$HERE/ca}"
CONF="$HERE/openssl.cnf"
export PKI_SAN="${PKI_SAN:-DNS:placeholder}"

mkdir -p "$PKI_CA_DIR"/{certs,crl,issued,private}
chmod 700 "$PKI_CA_DIR/private"
[ -f "$PKI_CA_DIR/index.txt" ] || : >"$PKI_CA_DIR/index.txt"
[ -f "$PKI_CA_DIR/serial" ] || echo 1000 >"$PKI_CA_DIR/serial"
[ -f "$PKI_CA_DIR/crlnumber" ] || echo 1000 >"$PKI_CA_DIR/crlnumber"

if [ -f "$PKI_CA_DIR/private/ca.key.pem" ]; then
  echo "CA 已存在($PKI_CA_DIR),略過。"
  exit 0
fi

openssl genrsa -out "$PKI_CA_DIR/private/ca.key.pem" 4096
chmod 400 "$PKI_CA_DIR/private/ca.key.pem"
openssl req -config "$CONF" -key "$PKI_CA_DIR/private/ca.key.pem" \
  -new -x509 -days 3650 -sha256 -extensions v3_ca \
  -subj "/CN=Drone Fleet Root CA" -out "$PKI_CA_DIR/certs/ca.cert.pem"
chmod 444 "$PKI_CA_DIR/certs/ca.cert.pem"
echo "✓ 根 CA 已建立:$PKI_CA_DIR/certs/ca.cert.pem"
