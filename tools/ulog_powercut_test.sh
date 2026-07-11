#!/usr/bin/env bash
# VT-SAF-02 ULog 斷電近似治具(S25;手動工具,不進 nightly):
# 迴圈 N 次(預設 3):起 headless SITL → arm+takeoff(記錄進行中)→ arm 後
# 15-25 秒隨機點 docker kill(SIGKILL 整個容器 = 斷電近似,PX4 無任何 flush
# 機會)→ docker cp 撈出容器內最新 .ulg → tools/ulog_report.py 能解析已寫入
# 部分即算通過(完全無法開啟 = FAIL)→ 記錄「損失尾秒數」供參考。
#
# ⚠ 侷限聲明:這是 **SITL 近似**——檔案系統是容器 overlayfs、掉的是行程不是
# 電源,SD 卡控制器/檔案系統日誌行為與實機不同。實機斷電治具(REQ-SAF-02
# 「寫入中斷電 ×20 零丟失」)屬 Phase 0 飛測週次與 Phase 1 L2 台架項
# (docs/02-verification-validation.md RTM VT-SAF-02);本治具只回答
# 「記錄管線在無預警終止下,已落盤部分是否可解析」這一軟體側子問題。
#
# 用法:
#   ./tools/ulog_powercut_test.sh [N]        # N 預設 3;CI/快驗用 2
#   OFFBOARD_PORT=24540 GRPC_PORT_BASE=50820 ./tools/ulog_powercut_test.sh 2
#
# 需要:docker、Python 依賴(tools/requirements.txt + pip install -e
# onboard/mission_exec -e interfaces/proto/gen/python;pyulog 解析、mavsdk 飛行)。
# 每輪獨立容器(無 --rm:kill 後還要 docker cp,結束才 rm -f);
# OFFBOARD_PORT ≠ 14540 時走容器內 sed build 副本改埠(鐵則 1:勿 -p)。
# 輸出各輪結果與結論行:POWERCUT RESULT: PASS/FAIL。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
ROUNDS="${1:-${POWERCUT_ROUNDS:-3}}"
OFFBOARD_PORT="${OFFBOARD_PORT:-14540}"
GRPC_PORT_BASE="${GRPC_PORT_BASE:-50820}"   # 每輪 +1,避免上輪殘留佔埠
SITL_IMAGE="jonasvautherin/px4-gazebo-headless:1.15.4"
WORK="$(mktemp -d)"
NAME=""
FLIGHT_PID=""

cleanup() {
    rc=$?
    if [[ ${rc} -ne 0 && -n "${NAME}" ]]; then
        echo "[powercut] 異常退出(exit ${rc}),SITL log:" >&2
        docker logs "${NAME}" --tail 60 >&2 2>/dev/null || true
        tail -n 40 "${WORK}"/flight-*.log >&2 2>/dev/null || true
    fi
    # 飛行 helper 以 setsid 自成 process group:連 spawn 的 mavsdk_server 一起收
    [[ -n "${FLIGHT_PID}" ]] && { kill -TERM -- "-${FLIGHT_PID}" 2>/dev/null || true; }
    [[ -n "${NAME}" ]] && docker rm -f "${NAME}" >/dev/null 2>&1 || true
    rm -rf "${WORK}"
}
trap cleanup EXIT

# 飛行 helper:連 SITL → 定位就緒 → arm(重試)→ takeoff → 懸停到被殺。
# arm 成功即印 ARMED_OK(父腳本以此起算隨機斷電窗)。
cat >"${WORK}/flight.py" <<'PY'
import asyncio, os, sys
from mavsdk import System
from mission_exec.executor import _arm_with_retry, wait_position_ready
from mission_exec.main import wait_connected

async def main(offboard_port: int, grpc_port: int) -> None:
    drone = System(port=grpc_port)
    await drone.connect(system_address=f"udpin://0.0.0.0:{offboard_port}")
    await asyncio.wait_for(wait_connected(drone), timeout=90)
    await asyncio.wait_for(wait_position_ready(drone), timeout=150)
    await _arm_with_retry(drone)
    print("ARMED_OK", flush=True)
    await drone.action.set_takeoff_altitude(15.0)
    await drone.action.takeoff()
    while True:  # 懸停維持記錄,直到父腳本殺容器/本行程
        await asyncio.sleep(1)

try:
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
except Exception as e:  # 容器被殺後鏈路必斷:記一行即硬退(鐵則 4,grpc 執行緒拖住 exit)
    print(f"flight helper 結束:{e}", flush=True)
    os._exit(0)
PY

wait_grep() { # 檔案 關鍵字 逾時秒;找到回 0
    local f="$1" pat="$2" t="$3"
    for _ in $(seq 1 "${t}"); do
        grep -q "${pat}" "${f}" 2>/dev/null && return 0
        [[ -n "${FLIGHT_PID}" ]] && ! kill -0 "${FLIGHT_PID}" 2>/dev/null && return 1
        sleep 1
    done
    return 1
}

declare -a SUMMARY
FAILED=0

for round in $(seq 1 "${ROUNDS}"); do
    NAME="powercut-$$-${round}"
    GRPC_PORT=$((GRPC_PORT_BASE + round))
    FLOG="${WORK}/flight-${round}.log"
    echo "[powercut] ── 第 ${round}/${ROUNDS} 輪(container=${NAME} grpc:${GRPC_PORT})──"

    # 無 --rm:SIGKILL 後容器停止但保留,才能 docker cp 撈 log;結束 rm -f
    if [[ "${OFFBOARD_PORT}" == "14540" ]]; then
        docker run -d --name "${NAME}" "${SITL_IMAGE}" >/dev/null
    else
        docker run -d --name "${NAME}" --entrypoint /bin/bash "${SITL_IMAGE}" \
            -c "sed -i 's/14540+px4_instance/${OFFBOARD_PORT}+px4_instance/' \
                /root/Firmware/build/px4_sitl_default/etc/init.d-posix/px4-rc.mavlink \
                && exec /root/entrypoint.sh" >/dev/null
    fi

    setsid "${PYTHON}" "${WORK}/flight.py" "${OFFBOARD_PORT}" "${GRPC_PORT}" \
        >"${FLOG}" 2>&1 &
    FLIGHT_PID=$!

    if ! wait_grep "${FLOG}" "ARMED_OK" 240; then
        echo "[powercut] 第 ${round} 輪:240 秒內未 arm(SITL/依賴問題,非治具斷言)" >&2
        tail -n 30 "${FLOG}" >&2 || true
        SUMMARY+=("第 ${round} 輪:FAIL(未能起飛)")
        FAILED=1
        kill -TERM -- "-${FLIGHT_PID}" 2>/dev/null || true; FLIGHT_PID=""
        docker rm -f "${NAME}" >/dev/null 2>&1 || true; NAME=""
        continue
    fi
    T_ARM=$(date +%s)

    # 記錄檔於 arm 時建立:先取容器內 .ulg 路徑(kill 後無法 exec)
    sleep 3
    ULG_IN=$(docker exec "${NAME}" sh -c \
        "find /root/Firmware/build/px4_sitl_default -name '*.ulg' 2>/dev/null | head -1" || true)

    CUT_AFTER=$((RANDOM % 11 + 15))   # arm 後 15-25 秒隨機斷電點
    REMAIN=$((CUT_AFTER - ($(date +%s) - T_ARM)))
    [[ "${REMAIN}" -gt 0 ]] && sleep "${REMAIN}"
    T_KILL=$(date +%s)
    docker kill "${NAME}" >/dev/null   # 預設 SIGKILL:容器全行程即死 = 斷電近似
    echo "[powercut] arm 後 $((T_KILL - T_ARM)) 秒 SIGKILL(目標 ${CUT_AFTER} 秒)"
    kill -TERM -- "-${FLIGHT_PID}" 2>/dev/null || true
    FLIGHT_PID=""

    ROUND_OK=1
    ULG_OUT="${WORK}/round-${round}.ulg"
    if [[ -z "${ULG_IN}" ]] || ! docker cp "${NAME}:${ULG_IN}" "${ULG_OUT}" >/dev/null 2>&1; then
        echo "[powercut] 第 ${round} 輪:撈不到 .ulg(in='${ULG_IN}')" >&2
        ROUND_OK=0
    else
        SIZE=$(stat -c %s "${ULG_OUT}")
        # 通過準則:ulog_report 能開檔解析已寫入部分(輸出含記錄長度行);
        # exit 1 可能只是異常規則(截斷檔 GPS 佔比等)觸發,不算解析失敗
        REPORT="${WORK}/report-${round}.txt"
        "${PYTHON}" "${ROOT}/tools/ulog_report.py" "${ULG_OUT}" >"${REPORT}" 2>&1 || true
        if grep -q "記錄長度" "${REPORT}"; then
            # 損失尾秒數(參考值):實際記錄窗(arm→kill)−ULog 已落盤時長
            LOSS=$("${PYTHON}" - "${ULG_OUT}" "$((T_KILL - T_ARM))" <<'PY'
import sys
from pyulog import ULog
u = ULog(sys.argv[1])
dur = (u.last_timestamp - u.start_timestamp) / 1e6
print(f"{max(0.0, float(sys.argv[2]) - dur):.1f}")
PY
            ) || { LOSS="n/a"; }
            echo "[powercut] 第 ${round} 輪:.ulg ${SIZE} bytes,可解析;損失尾秒數 ≈ ${LOSS} s(參考)"
            sed -n '1,6p' "${REPORT}"
            SUMMARY+=("第 ${round} 輪:PASS(${SIZE} bytes,損失尾 ≈ ${LOSS} s)")
        else
            echo "[powercut] 第 ${round} 輪:ulog_report 無法解析截斷檔:" >&2
            tail -n 20 "${REPORT}" >&2 || true
            ROUND_OK=0
        fi
    fi
    if [[ "${ROUND_OK}" -eq 0 ]]; then
        SUMMARY+=("第 ${round} 輪:FAIL(截斷檔不可解析/未撈到)")
        FAILED=1
    fi
    docker rm -f "${NAME}" >/dev/null 2>&1 || true
    NAME=""
done

echo "[powercut] ── 總結 ──"
for line in "${SUMMARY[@]}"; do echo "[powercut] ${line}"; done
if [[ "${FAILED}" -ne 0 ]]; then
    echo "POWERCUT RESULT: FAIL"
    exit 1
fi
echo "POWERCUT RESULT: PASS"
