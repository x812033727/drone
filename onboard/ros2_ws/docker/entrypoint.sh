#!/usr/bin/env bash
# 進容器先 source ROS 2 與 workspace,再執行指令。
set -e
source /opt/ros/humble/setup.bash
source /ros2_ws/install/setup.bash
exec "$@"
