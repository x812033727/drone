# onboard/ros2_ws 容器化開發/煙霧環境 —— host 不裝 ROS,一切在容器內。
# build context 為 **repo 根**(S22 起,照 cloud/ingest 先例:
# px4_mqtt_bridge 需要 COPY interfaces/proto/gen/python 的契約生成碼):
#   docker build -t drone-ros2-smoke:s8 -f onboard/ros2_ws/docker/Dockerfile <repo根>
# RUN 層指令不變 → px4_msgs / agent 的 docker 快取語義不受 context 搬家影響。
#
# base 選 ros:humble(= ros-base,已含 colcon/cmake/gcc,無 GUI):
# 煙霧與後續 headless package 只需 rclpy + 訊息生成;osrf/ros:humble-desktop
# 多出的 rviz/示範件用不到,image 徒增 2GB+,Jetson 上也不會裝 desktop。
FROM ros:humble

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# --- Micro XRCE-DDS Agent(source build)---
# 查證(2026-07):ros:humble 的 apt 源共 3589 個 ros-humble-* 套件,
# 「沒有」ros-humble-micro-xrce-dds-agent,也沒有 ros-humble-px4-msgs;
# snap 在容器內不可用 → source build 是最簡可重現路徑。
# 版本:v2.4.3 = 最新 v2.x(PX4 1.15 client 走 XRCE-DDS 2.x 協定)。
#
# 依賴釘版(防 nightly 外部漂移):superbuild 原生把 fastdds/fastcdr 釘在
# 「移動分支」2.14.x / 2.2.x(GIT_TAG 直接吃分支名),上游 push/刪分支都會
# 讓 nightly 無聲變化或直接紅——既往事故:v2.4.2 釘的 fastdds 2.12.x 分支
# 被上游刪除,build 必失敗(實測)。tag 變數是 plain set(非 cache),
# -D 蓋不掉,故以 sed 改成不可變的 release tag(2026-07 時各分支的 tip):
#   fastcdr 2.2.x → v2.2.7、fastdds 2.14.x → v2.14.6
# sed 後 grep 驗證釘版確實生效,上游改版造成 sed 落空時直接 fail 而非無聲跟漂。
RUN git clone --depth 1 -b v2.4.3 https://github.com/eProsima/Micro-XRCE-DDS-Agent.git /tmp/agent \
    && sed -i \
        -e 's/set(_fastcdr_tag 2\.2\.x)/set(_fastcdr_tag v2.2.7)/' \
        -e 's/set(_fastdds_tag 2\.14\.x)/set(_fastdds_tag v2.14.6)/' \
        /tmp/agent/CMakeLists.txt \
    && grep -q 'set(_fastcdr_tag v2\.2\.7)' /tmp/agent/CMakeLists.txt \
    && grep -q 'set(_fastdds_tag v2\.14\.6)' /tmp/agent/CMakeLists.txt \
    && cmake -S /tmp/agent -B /tmp/agent/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/agent/build -j"$(nproc)" \
    && cmake --install /tmp/agent/build \
    && ldconfig /usr/local/lib \
    && rm -rf /tmp/agent

WORKDIR /ros2_ws

# --- px4_msgs(source build,單獨一層)---
# 訊息定義必須與韌體一致(不一致 → 序列化/欄位錯位,topic 收不到或亂值);
# SITL 跑 PX4 1.15.4 → 對應 px4_msgs 的 release/1.15 分支。
# 注意:跟隨 release/1.15「分支」(而非釘 SHA)是刻意的金絲雀設計——
# 上游對 1.15 訊息定義的修補要立即被 nightly 煙霧看見,勿改成釘死。
# 放在 bridge_smoke 之前單獨 build:訊息編譯最慢(數分鐘),
# 之後迭代自家 package 時此層有 docker 快取,不會重編。
RUN git clone --depth 1 -b release/1.15 https://github.com/PX4/px4_msgs.git src/px4_msgs \
    && source /opt/ros/humble/setup.bash \
    && colcon build --packages-select px4_msgs

# --- 機-雲契約生成碼 + MQTT client(S22,px4_mqtt_bridge 用)---
# paho-mqtt 釘版(對齊 venv 實測版);protobuf 版本約束沿 gen/python
# 的 pyproject(>=5.26,<8),由安裝 drone-proto 時 pip 解出。
# 裝到系統 python(ros:humble 的 rclpy 也在系統 python,不能開 venv 隔離)。
COPY interfaces/proto/gen/python /opt/drone-proto
# 兩個陷阱(實測):
# 1. apt 的 pip 22.0.2 對 PEP 621([project] 表)的 PEP 517 建置會產出
#    UNKNOWN-0.0.0 空包(無 drone module、**無錯誤**)→ 必須先升 pip
#    (升到 /usr/local,26.x 實測正確產出 drone-proto-0.4.0),
#    並在裝完後以 import 驗證裝對。
# 2. **不可** pip 升級系統 setuptools:/usr/local 的新 setuptools 會撞
#    apt 舊 packaging(canonicalize_version TypeError),後續 colcon build
#    全滅(實測);只升 pip 不動 setuptools,colcon 用的系統件保持 59.6 原狀。
# 另:清掉 host 端 pip install -e 可能殘留進 COPY 的 build/ 與 *.egg-info,
# 避免 stale metadata 干擾建置。
RUN apt-get update && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --upgrade pip \
    && rm -rf /opt/drone-proto/build /opt/drone-proto/*.egg-info \
    && pip3 install --no-cache-dir paho-mqtt==2.1.0 /opt/drone-proto \
    && python3 -c "from drone.v1 import sensors_pb2; import paho.mqtt" \
    && python3 -c "import setuptools; v = setuptools.__version__; assert v.startswith('59.'), f'系統 setuptools 被升到 {v},colcon build 會壞(見上方註解)'"

# --- 自家 package(build 進 image,而非掛載編譯)---
# 選「build 進 image」:煙霧目標是可重現的一鍵驗證,單一 image 自帶全部產物,
# CI 與本機行為一致、無 host 路徑/權限問題。開發迭代時仍可
# `docker run -v $PWD/src:/ros2_ws/src ... colcon build` 掛載重編,兩者不互斥。
COPY onboard/ros2_ws/src/bridge_smoke src/bridge_smoke
RUN source /opt/ros/humble/setup.bash && colcon build --packages-select bridge_smoke

COPY onboard/ros2_ws/src/px4_mqtt_bridge src/px4_mqtt_bridge
RUN source /opt/ros/humble/setup.bash && colcon build --packages-select px4_mqtt_bridge

COPY onboard/ros2_ws/docker/entrypoint.sh /ros2_entrypoint.sh
ENTRYPOINT ["/ros2_entrypoint.sh"]
CMD ["bash"]
