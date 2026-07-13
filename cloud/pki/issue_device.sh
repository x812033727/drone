#!/usr/bin/env bash
# 為裝置簽發 mTLS client 憑證(CN=serial,SAN=DNS:serial,EKU clientAuth)。
# 用法:[PKI_CA_DIR=/path] cloud/pki/issue_device.sh <serial>
# 再次對同一 serial 執行 = 輪換(產生新私鑰與新憑證;舊憑證仍在效期內,
# 換發完成後可 revoke_device.sh 吊銷舊的)。SITL 裝置身分:serial 用 dev-1 等。
set -euo pipefail

SERIAL="${1:?用法: issue_device.sh <serial>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PKI_CA_DIR="${PKI_CA_DIR:-$HERE/ca}"
CONF="$HERE/openssl.cnf"
export PKI_SAN="${PKI_SAN:-DNS:placeholder}"
OUT="$PKI_CA_DIR/issued"

if [ ! -f "$PKI_CA_DIR/private/ca.key.pem" ]; then
  echo "錯誤:CA 未初始化,先跑 init_ca.sh" >&2
  exit 1
fi

openssl genrsa -out "$OUT/$SERIAL.key.pem" 2048
chmod 400 "$OUT/$SERIAL.key.pem"
openssl req -config "$CONF" -key "$OUT/$SERIAL.key.pem" -new -sha256 \
  -subj "/CN=$SERIAL" -out "$OUT/$SERIAL.csr.pem"
PKI_SAN="DNS:$SERIAL" openssl ca -config "$CONF" -batch -extensions device_cert \
  -days 365 -notext -md sha256 \
  -in "$OUT/$SERIAL.csr.pem" -out "$OUT/$SERIAL.cert.pem"
rm -f "$OUT/$SERIAL.csr.pem"

echo "✓ 裝置憑證已簽發:$OUT/$SERIAL.cert.pem"
# SHA-256 指紋供 fleet-svc device.cert_fingerprint(綁機身序號)
echo -n "指紋:"
openssl x509 -in "$OUT/$SERIAL.cert.pem" -noout -fingerprint -sha256 | sed 's/.*=//'
