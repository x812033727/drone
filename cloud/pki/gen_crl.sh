#!/usr/bin/env bash
# 產生 / 更新憑證吊銷清單(CRL)。C2 起由 EMQX 載入此 CRL 即時拒絕吊銷裝置。
# 用法:[PKI_CA_DIR=/path] cloud/pki/gen_crl.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
export PKI_CA_DIR="${PKI_CA_DIR:-$HERE/ca}"
CONF="$HERE/openssl.cnf"
export PKI_SAN="${PKI_SAN:-DNS:placeholder}"

openssl ca -config "$CONF" -gencrl -out "$PKI_CA_DIR/crl/ca.crl.pem"
echo "✓ CRL 已更新:$PKI_CA_DIR/crl/ca.crl.pem"
