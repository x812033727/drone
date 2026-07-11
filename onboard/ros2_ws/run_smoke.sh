#!/usr/bin/env bash
# 一鍵 uXRCE-DDS 煙霧:PX4 SITL(SIH)→ Micro XRCE-DDS Agent → ROS 2 topic(bridge_smoke)
#
# 流程:build 兩顆 image(ROS 2 環境、自建 PX4 v1.15.4 SIH SITL)
# → 起 ROS 2 容器(--network host,先跑 agent 待命)
# → 起 SITL 容器(--network host,uxrce_dds_client 連 127.0.0.1:8888)
# → 輪詢 px4 進程就緒 → 容器內跑 listener 收滿 N 筆 vehicle_status 判 PASS
# → 清理全部容器。
#
# 為什麼 SITL 不用 jonasvautherin/px4-gazebo-headless:1.15.4?
# 該 image 的 PX4 build 不含 uxrce_dds_client(舊 cmake 靜默跳過模組,
# 詳 docker/Dockerfile.px4-sitl-dds 開頭註解)→ 煙霧必失敗。
#
# 容器名固定 px4-s8-* / ros2-s8-* 前綴,清理只碰自己的容器。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

SITL_IMAGE="drone-px4-sitl-dds:s8"
ROS2_IMAGE="drone-ros2-smoke:s8"
SITL_NAME="px4-s8-sitl"
ROS2_NAME="ros2-s8-smoke"
SITL_UP_TIMEOUT="${SITL_UP_TIMEOUT:-120}" # 等 px4 進程就緒的上限(秒)
SMOKE_COUNT="${SMOKE_COUNT:-10}"          # 要收的 VehicleStatus 筆數
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-60}"      # listener 逾時秒數

log() { echo "[run_smoke] $*"; }

cleanup() {
    log "清理容器($SITL_NAME / $ROS2_NAME)"
    docker rm -f "$SITL_NAME" "$ROS2_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 埠衝突防護:--network host 下 agent 佔 UDP 8888、SITL 佔 UDP 14550 等,
# 被占直接報錯退出(常見肇因:別的 agent/SITL/QGC 還開著)。
if command -v ss >/dev/null 2>&1; then
    for port in 8888 14550; do
        if ss -lun | grep -q ":$port "; then
            log "錯誤:UDP $port 已被占用(ss -lun | grep $port 查佔用者),請先釋放再跑"
            exit 1
        fi
    done
else
    log "警告:找不到 ss,略過埠占用檢查"
fi

# 上次異常中斷的同名殘留容器直接清掉(名字帶 s8 前綴,不會誤傷他人)
docker rm -f "$SITL_NAME" "$ROS2_NAME" >/dev/null 2>&1 || true

log "build ROS 2 image($ROS2_IMAGE;首次含 agent + px4_msgs source build,約 10 分)"
docker build -t "$ROS2_IMAGE" -f docker/Dockerfile .

log "build PX4 SITL image($SITL_IMAGE;首次含 PX4 v1.15.4 source build,約 10 分)"
docker build -t "$SITL_IMAGE" -f docker/Dockerfile.px4-sitl-dds docker/

log "啟動 agent 待命($ROS2_NAME,--network host,UDP 8888)"
docker run -d --name "$ROS2_NAME" --network host "$ROS2_IMAGE" \
    MicroXRCEAgent udp4 -p 8888 >/dev/null

log "啟動 PX4 SITL($SITL_NAME,--network host,SIH 免 Gazebo)"
docker run -d --name "$SITL_NAME" --network host "$SITL_IMAGE" >/dev/null

log "等 px4 進程就緒(上限 ${SITL_UP_TIMEOUT}s)"
elapsed=0
until docker exec "$SITL_NAME" pgrep -x px4 >/dev/null 2>&1; do
    if ! docker ps -q --filter "name=^${SITL_NAME}$" | grep -q .; then
        log "錯誤:SITL 容器已退出,log 如下"
        docker logs "$SITL_NAME" --tail 30 || true
        exit 1
    fi
    if [ "$elapsed" -ge "$SITL_UP_TIMEOUT" ]; then
        log "錯誤:${SITL_UP_TIMEOUT}s 內 px4 進程未就緒,SITL log 如下"
        docker logs "$SITL_NAME" --tail 30 || true
        exit 1
    fi
    sleep 3
    elapsed=$((elapsed + 3))
done
log "px4 已就緒(約 ${elapsed}s),uxrce client 將自行連上 agent"

log "跑 listener(收 $SMOKE_COUNT 筆 VehicleStatus,逾時 ${SMOKE_TIMEOUT}s)"
if docker exec "$ROS2_NAME" /ros2_entrypoint.sh \
    ros2 run bridge_smoke listener --count "$SMOKE_COUNT" --timeout "$SMOKE_TIMEOUT"; then
    log "PASS:uXRCE-DDS 鏈路(PX4 → agent → ROS 2 topic)全通"
else
    rc=$?
    log "FAIL:listener 未在時限內收滿資料(exit $rc),傾印兩端 log 供排查"
    log "---- agent log(tail 20)----"
    docker logs "$ROS2_NAME" --tail 20 || true
    log "---- SITL log(tail 30)----"
    docker logs "$SITL_NAME" --tail 30 || true
    exit "$rc"
fi
