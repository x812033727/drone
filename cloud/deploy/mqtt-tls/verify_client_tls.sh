#!/usr/bin/env bash
# 驗證 aiomqtt client 走 mTLS(cloud/ingest 及服務消費者的連線路徑)。
# 起 mosquitto mTLS 容器 + PKI 憑證,跑 client_tls_check.py(aiomqtt + TLSParameters)。
# 用法:[PYTHON=/path] cloud/deploy/mqtt-tls/verify_client_tls.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKI="$HERE/../../pki"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-18885}"
NAME="mqtt-clienttls-verify-$$"
TMP="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

export PKI_CA_DIR="$TMP/ca"
"$PKI/init_ca.sh" >/dev/null
"$PKI/issue_server.sh" localhost >/dev/null
"$PKI/issue_device.sh" dev-1 >/dev/null
"$PKI/issue_device.sh" backend >/dev/null

CERTS="$TMP/certs"
mkdir -p "$CERTS"
cp "$PKI_CA_DIR/certs/ca.cert.pem" "$CERTS/ca.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.cert.pem" "$CERTS/server.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.key.pem" "$CERTS/server.key.pem"
chmod 644 "$CERTS"/*.pem

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
"$PYTHON" "$HERE/client_tls_check.py" localhost "$PORT" "$CERTS/ca.cert.pem" \
  "$I/backend.cert.pem" "$I/backend.key.pem" "$I/dev-1.cert.pem" "$I/dev-1.key.pem"
