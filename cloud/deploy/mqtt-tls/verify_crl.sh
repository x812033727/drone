#!/usr/bin/env bash
# 驗證 CRL 吊銷:被吊銷的裝置憑證於 mTLS 握手即被拒,未吊銷的正常連上。
# 用法:[PYTHON=/path] cloud/deploy/mqtt-tls/verify_crl.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKI="$HERE/../../pki"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-18887}"
NAME="mqtt-crl-verify-$$"
TMP="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

export PKI_CA_DIR="$TMP/ca"
echo "→ 建 CA + 憑證(server / dev-1 / dev-revoked),吊銷 dev-revoked..."
"$PKI/init_ca.sh" >/dev/null
"$PKI/issue_server.sh" localhost >/dev/null
"$PKI/issue_device.sh" dev-1 >/dev/null
"$PKI/issue_device.sh" dev-revoked >/dev/null
"$PKI/revoke_device.sh" dev-revoked >/dev/null # 吊銷 + 重生 CRL(含 dev-revoked)

CERTS="$TMP/certs"
mkdir -p "$CERTS"
cp "$PKI_CA_DIR/certs/ca.cert.pem" "$CERTS/ca.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.cert.pem" "$CERTS/server.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.key.pem" "$CERTS/server.key.pem"
cp "$PKI_CA_DIR/crl/ca.crl.pem" "$CERTS/ca.crl.pem"
chmod 644 "$CERTS"/*.pem

echo "→ 起 mosquitto mTLS + CRL 容器(:$PORT)..."
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8883" \
  -v "$CERTS:/mosquitto/certs:ro" \
  -v "$HERE/mosquitto-tls.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v "$HERE/acl:/mosquitto/config/acl:ro" \
  eclipse-mosquitto:2 >/dev/null

for _ in $(seq 1 40); do
  if (exec 3<>"/dev/tcp/localhost/$PORT") 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 0.5
done

I="$PKI_CA_DIR/issued"
echo "→ 斷言..."
"$PYTHON" "$HERE/crl_check.py" "$PORT" "$CERTS/ca.cert.pem" "$I/dev-1.cert.pem" "$I/dev-1.key.pem" ok
"$PYTHON" "$HERE/crl_check.py" "$PORT" "$CERTS/ca.cert.pem" \
  "$I/dev-revoked.cert.pem" "$I/dev-revoked.key.pem" reject
echo ""
echo "RESULT: PASS — CRL 吊銷生效(dev-1 連上、dev-revoked 被拒)"
