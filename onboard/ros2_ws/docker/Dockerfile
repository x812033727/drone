# onboard/ros2_ws 容器化開發/煙霧環境 —— host 不裝 ROS,一切在容器內。
# build context 為 onboard/ros2_ws(見 run_smoke.sh):
#   docker build -t drone-ros2-smoke:s8 -f docker/Dockerfile .
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
# 版本:v2.4.3 = 最新 v2.x(PX4 1.15 client 走 XRCE-DDS 2.x 協定),
# superbuild 釘 fastdds 2.14.x / fastcdr 2.2.x(上游分支存在,實測可 build);
# PX4 文件舊建議的 v2.4.2 釘的 fastdds 2.12.x 分支已被上游刪除,build 必失敗(實測)。
RUN git clone --depth 1 -b v2.4.3 https://github.com/eProsima/Micro-XRCE-DDS-Agent.git /tmp/agent \
    && cmake -S /tmp/agent -B /tmp/agent/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/agent/build -j"$(nproc)" \
    && cmake --install /tmp/agent/build \
    && ldconfig /usr/local/lib \
    && rm -rf /tmp/agent

WORKDIR /ros2_ws

# --- px4_msgs(source build,單獨一層)---
# 訊息定義必須與韌體一致(不一致 → 序列化/欄位錯位,topic 收不到或亂值);
# SITL 跑 PX4 1.15.4 → 對應 px4_msgs 的 release/1.15 分支。
# 放在 bridge_smoke 之前單獨 build:訊息編譯最慢(數分鐘),
# 之後迭代自家 package 時此層有 docker 快取,不會重編。
RUN git clone --depth 1 -b release/1.15 https://github.com/PX4/px4_msgs.git src/px4_msgs \
    && source /opt/ros/humble/setup.bash \
    && colcon build --packages-select px4_msgs

# --- bridge_smoke(build 進 image,而非掛載編譯)---
# 選「build 進 image」:煙霧目標是可重現的一鍵驗證,單一 image 自帶全部產物,
# CI 與本機行為一致、無 host 路徑/權限問題。開發迭代時仍可
# `docker run -v $PWD/src:/ros2_ws/src ... colcon build` 掛載重編,兩者不互斥。
COPY src/bridge_smoke src/bridge_smoke
RUN source /opt/ros/humble/setup.bash && colcon build --packages-select bridge_smoke

COPY docker/entrypoint.sh /ros2_entrypoint.sh
ENTRYPOINT ["/ros2_entrypoint.sh"]
CMD ["bash"]
