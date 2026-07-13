#!/usr/bin/env bash
# 整棧 mTLS 端到端驗證:裝置(dev-1,TLS)發遙測 → mosquitto-mtls → ingest(backend,
# TLS)→ TimescaleDB 落庫。證明「機-雲全程 mTLS」的安全部署可實際運行。
# 用法:[PYTHON=/path] cloud/deploy/compose/verify_stack_mtls.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKI="$HERE/../../pki"
PYTHON="${PYTHON:-python3}"
# compose 指令:CI 為 plugin(docker compose),本機為 standalone(docker-compose)
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
PROJ="stack-mtls-verify-$$"
TLSP="${MQTT_TLS_PORT:-18883}"
PGP="${PG_PORT:-35491}"
TMP="$(mktemp -d)"
cleanup() {
  MTLS_CERTS_DIR="$TMP/certs" MQTT_TLS_PORT="$TLSP" PG_PORT="$PGP" \
    $COMPOSE -p "$PROJ" -f "$HERE/docker-compose.yml" -f "$HERE/docker-compose.mtls.yml" \
    down -v >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

export PKI_CA_DIR="$TMP/ca"
echo "→ 簽發憑證(server=mosquitto-mtls+localhost / backend / dev-1)..."
"$PKI/init_ca.sh" >/dev/null
"$PKI/issue_server.sh" mosquitto-mtls localhost >/dev/null
"$PKI/issue_device.sh" backend >/dev/null
"$PKI/issue_device.sh" dev-1 >/dev/null
"$PKI/gen_crl.sh" >/dev/null

C="$TMP/certs"
mkdir -p "$C"
cp "$PKI_CA_DIR/certs/ca.cert.pem" "$C/ca.cert.pem"
cp "$PKI_CA_DIR/issued/mosquitto-mtls.server.cert.pem" "$C/server.cert.pem"
cp "$PKI_CA_DIR/issued/mosquitto-mtls.server.key.pem" "$C/server.key.pem"
cp "$PKI_CA_DIR/crl/ca.crl.pem" "$C/ca.crl.pem"
cp "$PKI_CA_DIR/issued/backend.cert.pem" "$C/backend.cert.pem"
cp "$PKI_CA_DIR/issued/backend.key.pem" "$C/backend.key.pem"
chmod 644 "$C"/*.pem

echo "→ 起 mTLS 棧(mosquitto-mtls + timescaledb + ingest,全程 TLS)..."
export MTLS_CERTS_DIR="$C" MQTT_TLS_PORT="$TLSP" PG_PORT="$PGP"
$COMPOSE -p "$PROJ" -f "$HERE/docker-compose.yml" -f "$HERE/docker-compose.mtls.yml" \
  up -d --build mosquitto-mtls timescaledb ingest >/dev/null 2>&1
# 等 timescaledb 就緒 + ingest 連上 broker
for _ in $(seq 1 40); do
  $COMPOSE -p "$PROJ" -f "$HERE/docker-compose.yml" -f "$HERE/docker-compose.mtls.yml" \
    exec -T timescaledb pg_isready -U drone -d drone >/dev/null 2>&1 && break
  sleep 1
done
sleep 4 # 讓 ingest 完成 TLS 連線 + 訂閱

echo "→ 裝置 dev-1(TLS)發布遙測..."
"$PYTHON" - "$TLSP" "$C/ca.cert.pem" "$PKI_CA_DIR/issued/dev-1.cert.pem" \
  "$PKI_CA_DIR/issued/dev-1.key.pem" <<'PY'
import ssl, sys, time, paho.mqtt.client as mqtt
port, ca, cert, key = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
c.tls_set(ca_certs=ca, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)
c.connect("localhost", port); c.loop_start(); time.sleep(0.5)
p = '{"droneId":"dev-1","unixTimeMs":"1720000000000","batteryPct":88.0,"flightMode":"HOLD"}'
c.publish("fleet/dev-1/telemetry", p, qos=1).wait_for_publish()
time.sleep(0.5); c.loop_stop(); c.disconnect()
print("  已發布 fleet/dev-1/telemetry(mTLS)")
PY

echo "→ 斷言 ingest(TLS)已落庫..."
sleep 2
CNT=$($COMPOSE -p "$PROJ" -f "$HERE/docker-compose.yml" -f "$HERE/docker-compose.mtls.yml" \
  exec -T timescaledb psql -U drone -d drone -tAc \
  "SELECT count(*) FROM telemetry WHERE drone_id='dev-1'")
CNT="$(echo "$CNT" | tr -d '[:space:]')"
if [ "${CNT:-0}" -ge 1 ]; then
  echo ""
  echo "RESULT: PASS — 整棧 mTLS 落庫($CNT 筆):裝置 TLS→broker→ingest TLS→DB 全程加密"
else
  echo "✗ 未落庫(count=$CNT)"; exit 1
fi
