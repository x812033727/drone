#!/usr/bin/env bash
# drone_agent 機載安裝腳本(Jetson / 機載電腦,Ubuntu/Debian 系)。
# 冪等:可重複執行做升級。需 root(sudo)。
#
#   sudo ./install.sh /path/to/repo   # 預設 repo=腳本上溯三層
#
# 完成後:
#   sudo cp drone-agent.env.example /etc/drone/agent.env && sudoedit /etc/drone/agent.env
#   sudo systemctl enable --now drone-agent
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
PREFIX=/opt/drone
STATE_DIR=/var/lib/drone
CFG_DIR=/etc/drone
UNIT_SRC="$(dirname "${BASH_SOURCE[0]}")/drone-agent.service"

if [[ $EUID -ne 0 ]]; then
  echo "需 root:sudo $0" >&2
  exit 1
fi

if [[ ! -d "$REPO_ROOT/onboard/drone_agent" ]]; then
  echo "找不到 repo(onboard/drone_agent 不存在於 $REPO_ROOT);請傳入 repo 根路徑" >&2
  exit 1
fi

echo "==> 建立 drone 系統帳號與目錄"
id -u drone &>/dev/null || useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin drone
install -d -o drone -g drone -m 0750 "$STATE_DIR" /run/drone
install -d -m 0755 "$CFG_DIR"

echo "==> 建立 venv 並安裝 drone_agent(+ mission_exec,派遣子程序需要)"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet -r "$REPO_ROOT/onboard/drone_agent/requirements.txt"
# 生成 proto 契約(drone.v1)供 agent import;mission_exec 供派遣子程序執行。
if [[ -d "$REPO_ROOT/interfaces/proto/gen/python" ]]; then
  "$PREFIX/venv/bin/pip" install --quiet -e "$REPO_ROOT/interfaces/proto/gen/python"
fi
"$PREFIX/venv/bin/pip" install --quiet -e "$REPO_ROOT/onboard/drone_agent"
if [[ -f "$REPO_ROOT/onboard/mission_exec/pyproject.toml" ]]; then
  "$PREFIX/venv/bin/pip" install --quiet -e "$REPO_ROOT/onboard/mission_exec"
fi

echo "==> 安裝 systemd unit"
install -m 0644 "$UNIT_SRC" /etc/systemd/system/drone-agent.service
systemctl daemon-reload

echo
echo "✓ 安裝完成。接著:"
echo "  1) sudo cp $(dirname "${BASH_SOURCE[0]}")/drone-agent.env.example $CFG_DIR/agent.env"
echo "  2) sudo chmod 600 $CFG_DIR/agent.env && sudoedit $CFG_DIR/agent.env   # 填 DRONE_ID / MQTT / MAVLINK_URL / (mTLS 憑證)"
echo "  3) sudo systemctl enable --now drone-agent"
echo "  4) systemctl status drone-agent ; journalctl -u drone-agent -f"
