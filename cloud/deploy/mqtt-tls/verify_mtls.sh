#!/usr/bin/env bash
# mosquitto mTLS + per-device ACL 端到端驗證:建憑證 → 起 mosquitto TLS 容器 →
# 跑 mtls_check.py 斷言。可本地跑,也適合 CI(需 docker + paho-mqtt)。
# 用法:[PYTHON=/path/python] cloud/deploy/mqtt-tls/verify_mtls.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKI="$HERE/../../pki"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-18883}"
NAME="mqtt-mtls-verify-$$"
TMP="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

export PKI_CA_DIR="$TMP/ca"
echo "→ 建 CA + 憑證(server localhost / device dev-1,dev-2 / backend)..."
"$PKI/init_ca.sh" >/dev/null
"$PKI/issue_server.sh" localhost >/dev/null
for d in dev-1 dev-2 backend; do "$PKI/issue_device.sh" "$d" >/dev/null; done

CERTS="$TMP/certs"
mkdir -p "$CERTS"
cp "$PKI_CA_DIR/certs/ca.cert.pem" "$CERTS/ca.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.cert.pem" "$CERTS/server.cert.pem"
cp "$PKI_CA_DIR/issued/localhost.server.key.pem" "$CERTS/server.key.pem"
"$PKI/gen_crl.sh" >/dev/null # crlfile 需存在才能起 broker(此處無吊銷=空 CRL)
cp "$PKI_CA_DIR/crl/ca.crl.pem" "$CERTS/ca.crl.pem"
# 容器內 mosquitto(uid 1883)需能讀掛入檔;測試 CA 放寬權限無妨
chmod 644 "$CERTS"/*.pem

echo "→ 起 mosquitto mTLS 容器(:$PORT)..."
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8883" \
  -v "$CERTS:/mosquitto/certs:ro" \
  -v "$HERE/mosquitto-tls.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v "$HERE/acl:/mosquitto/config/acl:ro" \
  eclipse-mosquitto:2 >/dev/null

# 等 TLS 埠就緒
for _ in $(seq 1 40); do
  if (exec 3<>"/dev/tcp/localhost/$PORT") 2>/dev/null; then exec 3>&- 3<&-; break; fi
  sleep 0.5
done

echo "→ 跑 mTLS + ACL 斷言..."
"$PYTHON" "$HERE/mtls_check.py" "$PORT" "$CERTS/ca.cert.pem" "$PKI_CA_DIR/issued"
