#!/usr/bin/env bash
# PKI 自我驗證:在臨時 CA 目錄跑完整生命週期並斷言。
# 可本地跑,也適合當 CI job(runner 皆有 openssl)。用法:cloud/pki/verify_pki.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PKI_CA_DIR="$TMP/ca"

fail() { echo "✗ $1" >&2; exit 1; }

# 1. 建 CA
"$HERE/init_ca.sh" >/dev/null
[ -f "$PKI_CA_DIR/certs/ca.cert.pem" ] || fail "CA 憑證未建立"
openssl x509 -in "$PKI_CA_DIR/certs/ca.cert.pem" -noout -subject | grep -q "Drone Fleet Root CA" \
  || fail "CA subject 不符"
echo "✓ CA 建立"

# 2. 簽發裝置憑證
"$HERE/issue_device.sh" dev-1 >/dev/null
CERT="$PKI_CA_DIR/issued/dev-1.cert.pem"
[ -f "$CERT" ] || fail "裝置憑證未簽發"
# 憑證由 CA 驗證通過
openssl verify -CAfile "$PKI_CA_DIR/certs/ca.cert.pem" "$CERT" >/dev/null \
  || fail "裝置憑證無法由 CA 驗證"
# CN 與 clientAuth EKU
openssl x509 -in "$CERT" -noout -subject | grep -q "CN *= *dev-1" || fail "CN 不是 dev-1"
openssl x509 -in "$CERT" -noout -ext extendedKeyUsage | grep -q "TLS Web Client Authentication" \
  || fail "缺 clientAuth EKU"
echo "✓ 裝置憑證簽發 + CA 驗證 + clientAuth"

# 3. 吊銷前 CRL 不含此憑證
"$HERE/gen_crl.sh" >/dev/null
SERIAL_HEX=$(openssl x509 -in "$CERT" -noout -serial | sed 's/.*=//')
if openssl crl -in "$PKI_CA_DIR/crl/ca.crl.pem" -noout -text | grep -q "$SERIAL_HEX"; then
  fail "吊銷前 CRL 不應含此憑證"
fi
echo "✓ 吊銷前 CRL 乾淨"

# 4. 吊銷 → CRL 含此憑證序號
"$HERE/revoke_device.sh" dev-1 >/dev/null
openssl crl -in "$PKI_CA_DIR/crl/ca.crl.pem" -noout -text | grep -q "$SERIAL_HEX" \
  || fail "吊銷後 CRL 應含此憑證序號"
echo "✓ 吊銷 + CRL 含吊銷序號"

# 5. 針對 CRL 驗證應失敗(憑證已吊銷)
CHAIN="$TMP/chain.pem"
cat "$PKI_CA_DIR/certs/ca.cert.pem" "$PKI_CA_DIR/crl/ca.crl.pem" >"$CHAIN"
if openssl verify -crl_check -CAfile "$CHAIN" "$CERT" >/dev/null 2>&1; then
  fail "已吊銷憑證的 CRL 檢查應失敗"
fi
echo "✓ 已吊銷憑證 CRL 檢查正確拒絕"

echo ""
echo "RESULT: PASS — PKI 生命週期(建 CA / 簽發 / 驗證 / 吊銷 / CRL 拒絕)全通過"
