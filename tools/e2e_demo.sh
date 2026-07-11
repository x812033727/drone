#!/usr/bin/env bash
# VT-OPS-03 端到端演示(S25):派遣 → 飛行 → 遙測落庫 → ULog 自動回收出報告。
# 這是 flight-test-plan F19「端到端演示」的軟體版可重複載體(02-V&V RTM 註記),
# 單指令跑通全鏈:
#
#   雲端棧(mosquitto/timescaledb/ingest/log-svc)+ headless SITL
#   → mavsdk_server(單一 spawn,agent 與 mission_exec 子程序顯式共用)
#   → drone_agent(遙測 1 Hz 上報 + 任務下行 + --log-svc-url ULog 自動回收)
#   → dispatch_mission 派 demo_square --wait 等 COMPLETED
#   → psql 斷言:telemetry ≥60 筆且含 armed=true、mission_progress 有
#     STATE_COMPLETED、flight_events 有 EVENT_ARMED/EVENT_DISARMED、
#     flight_logs 出現 report_ok=t(S20 disarm→下載→上傳→報告 閉環)
#
# 需要:docker(+compose plugin 或 docker-compose)、Python 依賴已裝
# (tools/requirements.txt + onboard/drone_agent/requirements.txt
#  + pip install -e onboard/mission_exec -e interfaces/proto/gen/python)。
#
# 本地跑請用隔離埠與獨特名(CLAUDE.md 鐵則 8),例:
#   MQTT_PORT=41883 PG_PORT=45432 GRAFANA_PORT=43100 LOGSVC_PORT=48090 \
#   RTSP_PORT=48554 PLAYBACK_PORT=49996 MTX_API_PORT=49997 \
#   OFFBOARD_PORT=24540 GRPC_PORT=50771 ./tools/e2e_demo.sh
#
# OFFBOARD_PORT ≠ 14540 時自動走容器內 sed build 副本改 offboard remote port
# (鐵則 1:此 image 主動送 MAVLink 到 docker gateway,絕不可做 -p UDP 埠映射)。
# 全程 trap 清理;失敗傾印各容器/行程 log;結論行:E2E RESULT: PASS/FAIL。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="${ROOT}/cloud/deploy/compose"
PYTHON="${PYTHON:-python3}"

# 宿主埠(預設 = compose 預設,CI 可直接用;本地請覆寫為高位埠)
MQTT_PORT="${MQTT_PORT:-1883}"
PG_PORT="${PG_PORT:-5432}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
LOGSVC_PORT="${LOGSVC_PORT:-8090}"
RTSP_PORT="${RTSP_PORT:-8554}"
PLAYBACK_PORT="${PLAYBACK_PORT:-9996}"
MTX_API_PORT="${MTX_API_PORT:-9997}"
OFFBOARD_PORT="${OFFBOARD_PORT:-14540}"   # SITL → host 的 MAVLink offboard 埠
GRPC_PORT="${GRPC_PORT:-50051}"           # mavsdk_server gRPC 埠(單一 spawn)

PROJECT="${COMPOSE_PROJECT:-e2e-demo-$$}"
SITL_NAME="${SITL_NAME:-e2e-sitl-$$}"
DRONE_ID="${DRONE_ID:-e2e-1}"
SITL_IMAGE="jonasvautherin/px4-gazebo-headless:1.15.4"
WORK="$(mktemp -d)"
AGENT_PID=""
MAVSDK_PID=""

# CI 用 compose plugin;部分主機只有 docker-compose v2 binary,自動擇一
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
else
    COMPOSE=(docker-compose)
fi

compose() {
    MQTT_PORT="${MQTT_PORT}" PG_PORT="${PG_PORT}" GRAFANA_PORT="${GRAFANA_PORT}" \
    LOGSVC_PORT="${LOGSVC_PORT}" RTSP_PORT="${RTSP_PORT}" \
    PLAYBACK_PORT="${PLAYBACK_PORT}" MTX_API_PORT="${MTX_API_PORT}" \
        "${COMPOSE[@]}" -f "${COMPOSE_DIR}/docker-compose.yml" \
        --project-directory "${COMPOSE_DIR}" -p "${PROJECT}" "$@"
}

psql_q() {
    compose exec -T timescaledb psql -U drone -d drone -tAc "$1"
}

cleanup() {
    rc=$?
    if [[ ${rc} -ne 0 ]]; then
        echo "[e2e] 失敗(exit ${rc}),傾印各元件 log:" >&2
        echo "--- drone_agent(尾 80 行)---" >&2
        tail -n 80 "${WORK}/agent.log" >&2 2>/dev/null || true
        echo "--- mavsdk_server(尾 20 行)---" >&2
        tail -n 20 "${WORK}/mavsdk-server.log" >&2 2>/dev/null || true
        echo "--- SITL(尾 60 行)---" >&2
        docker logs "${SITL_NAME}" --tail 60 >&2 2>/dev/null || true
        echo "--- 雲端棧(尾 150 行)---" >&2
        compose logs --tail 150 >&2 2>/dev/null || true
        echo "E2E RESULT: FAIL"
    fi
    [[ -n "${AGENT_PID}" ]] && kill "${AGENT_PID}" 2>/dev/null || true
    [[ -n "${MAVSDK_PID}" ]] && kill "${MAVSDK_PID}" 2>/dev/null || true
    docker rm -f "${SITL_NAME}" >/dev/null 2>&1 || true
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "${WORK}"
    # 不在 trap 內 exit:保留原始退出碼
}
trap cleanup EXIT

# ── 0. 依賴自檢(缺件早退,訊息清楚) ─────────────────────────────
"${PYTHON}" - <<'PY'
import importlib
missing = [m for m in ("mavsdk", "aiomqtt", "httpx", "mission_exec", "drone.v1.mission_pb2")
           if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit(
        "缺 Python 依賴:" + ", ".join(missing)
        + "(pip install -r tools/requirements.txt -r onboard/drone_agent/requirements.txt"
        + " && pip install -e onboard/mission_exec -e interfaces/proto/gen/python)"
    )
PY

# ── 1. 雲端棧 ────────────────────────────────────────────────────
echo "[e2e] 起雲端棧(project=${PROJECT} mqtt:${MQTT_PORT} pg:${PG_PORT} logsvc:${LOGSVC_PORT})"
compose up -d --build --wait --wait-timeout 300

# ── 2. headless SITL(鐵則 1:勿 -p;非預設埠走容器內 sed build 副本) ──
echo "[e2e] 起 SITL(container=${SITL_NAME} offboard:${OFFBOARD_PORT})"
if [[ "${OFFBOARD_PORT}" == "14540" ]]; then
    docker run --rm -d --name "${SITL_NAME}" "${SITL_IMAGE}" >/dev/null
else
    docker run --rm -d --name "${SITL_NAME}" --entrypoint /bin/bash "${SITL_IMAGE}" \
        -c "sed -i 's/14540+px4_instance/${OFFBOARD_PORT}+px4_instance/' \
            /root/Firmware/build/px4_sitl_default/etc/init.d-posix/px4-rc.mavlink \
            && exec /root/entrypoint.sh" >/dev/null
fi

# ── 3. mavsdk_server(鐵則 5:一個 spawn,agent 與 mission_exec 顯式共用) ──
MAVSDK_SERVER_BIN="$("${PYTHON}" -c \
    'import mavsdk, pathlib; print(pathlib.Path(mavsdk.__file__).parent / "bin" / "mavsdk_server")')"
"${MAVSDK_SERVER_BIN}" -p "${GRPC_PORT}" "udpin://0.0.0.0:${OFFBOARD_PORT}" \
    >"${WORK}/mavsdk-server.log" 2>&1 &
MAVSDK_PID=$!

# ── 4. drone_agent(遙測上報 + 任務下行 + ULog 自動回收) ─────────
echo "[e2e] 起 drone_agent(drone_id=${DRONE_ID},log-svc=http://127.0.0.1:${LOGSVC_PORT})"
PYTHONPATH="${ROOT}/onboard/drone_agent" "${PYTHON}" -m drone_agent.main \
    --drone-id "${DRONE_ID}" \
    --mqtt-host 127.0.0.1 --mqtt-port "${MQTT_PORT}" \
    --mavsdk-address "127.0.0.1:${GRPC_PORT}" \
    --log-svc-url "http://127.0.0.1:${LOGSVC_PORT}" \
    >"${WORK}/agent.log" 2>&1 &
AGENT_PID=$!

CONNECTED=""
for _ in $(seq 1 120); do
    grep -q "已連上飛行器" "${WORK}/agent.log" 2>/dev/null && { CONNECTED=1; break; }
    kill -0 "${AGENT_PID}" 2>/dev/null || { echo "[e2e] drone_agent 提前退出" >&2; exit 1; }
    sleep 1
done
[[ -n "${CONNECTED}" ]] || { echo "[e2e] 120 秒內未連上 SITL" >&2; exit 1; }
echo "[e2e] agent 已連上 SITL;等 EKF/GPS lock(實測約 40-60 秒)"
sleep 60

# ── 5. 派遣 demo_square,等 COMPLETED(斷言 1) ───────────────────
echo "[e2e] 派遣 demo_square(--wait)"
"${PYTHON}" "${ROOT}/tools/dispatch_mission.py" \
    --drone-id "${DRONE_ID}" \
    --mission "${ROOT}/onboard/mission_exec/missions/demo_square.json" \
    --mqtt-host 127.0.0.1 --mqtt-port "${MQTT_PORT}" \
    --wait --timeout 600 | tee "${WORK}/dispatch.log"
grep -q "STATE_COMPLETED" "${WORK}/dispatch.log" \
    || { echo "[e2e] 斷言失敗:dispatch 未見 STATE_COMPLETED" >&2; exit 1; }
echo "[e2e] 任務 COMPLETED;等 RTL 降落 → disarm → ULog 回收落庫"

# ── 6. 等 flight_logs 出現 report_ok=t(斷言 5;S20 閉環,含 RTL 時間) ──
FL_OK=0
for _ in $(seq 1 75); do
    FL_OK=$(psql_q "SELECT count(*) FROM flight_logs WHERE drone_id='${DRONE_ID}' AND report_ok=true" || echo 0)
    [[ "${FL_OK}" -ge 1 ]] && break
    sleep 4
done

# ── 7. 全部落庫斷言 ─────────────────────────────────────────────
FAILED=0
assert_ge() { # label 實際值 門檻
    echo "[e2e] 斷言 $1:$2(需 ≥ $3)"
    [[ "$2" -ge "$3" ]] || { echo "[e2e]   ↑ 未達標" >&2; FAILED=1; }
}
assert_ge "telemetry 落庫筆數" \
    "$(psql_q "SELECT count(*) FROM telemetry WHERE drone_id='${DRONE_ID}'")" 60
assert_ge "telemetry armed=true 筆數" \
    "$(psql_q "SELECT count(*) FROM telemetry WHERE drone_id='${DRONE_ID}' AND armed=true")" 1
assert_ge "mission_progress STATE_COMPLETED 筆數" \
    "$(psql_q "SELECT count(*) FROM mission_progress WHERE drone_id='${DRONE_ID}' AND state='STATE_COMPLETED'")" 1
assert_ge "flight_events EVENT_ARMED 筆數" \
    "$(psql_q "SELECT count(*) FROM flight_events WHERE drone_id='${DRONE_ID}' AND event='EVENT_ARMED'")" 1
assert_ge "flight_events EVENT_DISARMED 筆數" \
    "$(psql_q "SELECT count(*) FROM flight_events WHERE drone_id='${DRONE_ID}' AND event='EVENT_DISARMED'")" 1
assert_ge "flight_logs report_ok=true 筆數(ULog 自動回收閉環)" "${FL_OK}" 1

# 失敗結論行(E2E RESULT: FAIL)由 trap cleanup 統一輸出(任何非零退出皆印)
[[ "${FAILED}" -eq 0 ]] || exit 1
echo "E2E RESULT: PASS"
