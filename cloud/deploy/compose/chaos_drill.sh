#!/usr/bin/env bash
# 混沌演練(R4):驗證既有自癒機制在三種基礎設施故障下確實自動恢復。
#   S1 DB 重啟   → ingest asyncpg pool 自癒(服務不重啟、恢復後續落庫)
#   S2 DB 長停   → 退避耗盡落 DLQ(JSONL 行數 > 0);DB 回來後新訊息恢復落庫
#   S3 MQTT 重啟 → ingest 重連恢復收訊;broker 斷線期間 dispatch 有限時回應(不懸掛)
# 全程斷言:ingest 容器零重啟(自癒 ≠ 靠 restart 兜底)。
# 用法(本機隔離,CLAUDE.md 鐵則 8):
#   MQTT_PORT=31896 PG_PORT=35496 FLEETSVC_PORT=38491 MISSIONSVC_PORT=38492 \
#     COMPOSE_PROJECT=chaos-$$ cloud/deploy/compose/chaos_drill.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
PROJ="${COMPOSE_PROJECT:-chaos-drill}"
export MQTT_PORT="${MQTT_PORT:-31896}"
export PG_PORT="${PG_PORT:-35496}"
export FLEETSVC_PORT="${FLEETSVC_PORT:-38491}"
export MISSIONSVC_PORT="${MISSIONSVC_PORT:-38492}"

compose() { $COMPOSE -f "$HERE/docker-compose.yml" --project-directory "$HERE" -p "$PROJ" "$@"; }

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "[chaos] 失敗(exit $rc),ingest 日誌尾段:" >&2
        compose logs --tail 40 ingest >&2 || true
    fi
    compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# --- helpers ---
SEQ=0
pub() { # 發 1 筆合法 telemetry(proto3 JSON 子集;decode 需 unixTimeMs+droneId)
    SEQ=$((SEQ + 1))
    local now_ms; now_ms="$(($(date +%s) * 1000))"
    docker run --rm --network "${PROJ}_default" eclipse-mosquitto:2 \
        mosquitto_pub -h mosquitto -t fleet/chaos-1/telemetry \
        -m "{\"droneId\":\"chaos-1\",\"unixTimeMs\":\"${now_ms}\",\"latDeg\":25.0,\"lonDeg\":121.5,\"batteryPct\":88,\"flightMode\":\"MISSION\"}" \
        >/dev/null 2>&1 || true
}
rows() { # telemetry 落庫筆數
    compose exec -T timescaledb psql -U drone -d drone -tAc \
        "SELECT count(*) FROM telemetry WHERE drone_id='chaos-1';" 2>/dev/null | tr -d '[:space:]'
}
wait_rows_at_least() { # $1=目標筆數 $2=秒數上限
    local target=$1 limit=$2 n=0
    for _ in $(seq 1 "$limit"); do
        n="$(rows || echo 0)"; [[ "${n:-0}" -ge "$target" ]] && return 0
        sleep 1
    done
    echo "[chaos] 落庫數 ${n:-0} < ${target}(${limit}s)" >&2
    return 1
}
ingest_restarts() { docker inspect --format '{{.RestartCount}}' "$(compose ps -q ingest)"; }
ingest_ready() { # /healthz(MQTT+DB 皆就緒)
    compose exec -T ingest python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8081/healthz', timeout=3)" \
        >/dev/null 2>&1
}
wait_ready() { local limit=$1; for _ in $(seq 1 "$limit"); do ingest_ready && return 0; sleep 1; done; return 1; }

echo "[chaos] 起棧(project=$PROJ)"
compose up -d --build --wait mosquitto timescaledb ingest fleetsvc missionsvc

echo "[chaos] 基線:發 5 筆 → 應全落庫"
for _ in 1 2 3 4 5; do pub; done
wait_rows_at_least 5 30
BASE="$(rows)"

echo "[chaos] S1:DB 重啟 → pool 自癒(不重啟服務)"
compose restart timescaledb >/dev/null
wait_ready 60 || { echo "[chaos] S1 ingest 未在 60s 內恢復就緒" >&2; exit 1; }
for _ in 1 2 3 4 5; do pub; sleep 0.3; done
wait_rows_at_least $((BASE + 4)) 30   # QoS0 容忍掉 1 筆
[[ "$(ingest_restarts)" == "0" ]] || { echo "[chaos] S1 ingest 發生容器重啟(應由 pool 自癒)" >&2; exit 1; }
echo "[chaos] S1 PASS(rows $(rows),restarts=0)"

echo "[chaos] S2:DB 長停 → DLQ 落地;恢復後續落庫"
compose stop timescaledb >/dev/null
sleep 3
for _ in 1 2 3 4 5; do pub; sleep 0.5; done
sleep 3
DLQ_LINES="$(compose exec -T ingest sh -c 'cat ingest_dlq.jsonl 2>/dev/null | wc -l' </dev/null 2>/dev/null | tr -dc '0-9' || true)"
[[ "${DLQ_LINES:-0}" =~ ^[0-9]+$ && "${DLQ_LINES}" -gt 0 ]] || { echo "[chaos] S2 DLQ 無落地(got='${DLQ_LINES}')" >&2; exit 1; }
compose start timescaledb >/dev/null
# 注意:ingest 的 db-ready 旗標在「下一次成功寫入」才翻回(實測)——
# 不能先等 /healthz(會死等),直接發訊以落庫證明恢復。
for _ in $(seq 1 30); do compose exec -T timescaledb pg_isready -U drone -d drone >/dev/null 2>&1 && break; sleep 1; done
S2_BASE="$(rows)"
for i in $(seq 1 10); do pub; sleep 1; n="$(rows || echo 0)"; [[ "${n:-0}" -ge $((S2_BASE + 2)) ]] && break; done
wait_rows_at_least $((S2_BASE + 2)) 20
echo "[chaos] S2 PASS(DLQ ${DLQ_LINES} 行,恢復後續落庫)"

echo "[chaos] S3:MQTT 重啟 → 重連恢復;斷線期間 dispatch 有限時回應"
# 先備妥 route+mission(dev 模式=admin;dispatch 在 broker 停止期間打)
ROUTE_ID="$(curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"name":"chaos","waypoints":[{"lat_deg":25.0,"lon_deg":121.5,"rel_alt_m":30}]}' \
    "http://127.0.0.1:${MISSIONSVC_PORT}/api/v1/routes" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
MISSION_PK="$(curl -fsS -X POST -H 'Content-Type: application/json' \
    -d "{\"route_id\":\"${ROUTE_ID}\",\"drone_id\":\"chaos-1\"}" \
    "http://127.0.0.1:${MISSIONSVC_PORT}/api/v1/missions" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
compose stop mosquitto >/dev/null
set +e
DISPATCH_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
    "http://127.0.0.1:${MISSIONSVC_PORT}/api/v1/missions/${MISSION_PK}/dispatch")"
DISPATCH_RC=$?
set -e
if [[ $DISPATCH_RC -ne 0 ]]; then
    echo "[chaos] S3 dispatch 在 broker 斷線時 20s 內無回應(curl rc=$DISPATCH_RC)——懸掛缺口,開修復 PR" >&2
    exit 1
fi
echo "[chaos] S3 dispatch(broker 斷線)→ HTTP ${DISPATCH_CODE}(有限時回應)"
[[ "${DISPATCH_CODE}" -ge 500 && "${DISPATCH_CODE}" -lt 600 ]] || \
    echo "[chaos] 注意:dispatch 斷線回應碼 ${DISPATCH_CODE}(預期 5xx,如實記錄)" >&2
compose start mosquitto >/dev/null
wait_ready 60
S3_BASE="$(rows)"
for _ in 1 2 3 4 5; do pub; sleep 0.5; done
wait_rows_at_least $((S3_BASE + 4)) 40
[[ "$(ingest_restarts)" == "0" ]] || { echo "[chaos] S3 ingest 容器重啟(應由重連迴圈自癒)" >&2; exit 1; }
echo "[chaos] S3 PASS(broker 重啟後恢復收訊,restarts=0)"

echo "[chaos] PASS:三場景全通(DB 重啟自癒 / DLQ 落地與恢復 / MQTT 重連 + dispatch 有限時)"
