# 機載部署(onboard deployment)

把 `drone_agent`(+ 派遣時 spawn 的 `mission_exec`)部署成機載電腦(Jetson / x86 伴機)上的 **systemd 常駐服務**。這解掉 `drone_agent/README` 提到「MAVSDK 異常結束交給 systemd 重啟」卻無 unit 的缺口(G6)。

> 影像管線(`video_pipeline`)的部署見其自身 README;本文只管 agent/mission_exec。
> 邊緣端選 systemd 原生部署(非容器):免容器開銷、直接存取序列飛控埠與系統時鐘。

## 快速開始

```bash
# 在機載電腦上,取得 repo 後:
sudo onboard/deploy/systemd/install.sh            # 建 drone 帳號 + venv + 裝 unit
sudo cp onboard/deploy/systemd/drone-agent.env.example /etc/drone/agent.env
sudo chmod 600 /etc/drone/agent.env
sudoedit /etc/drone/agent.env                      # 填 DRONE_ID / MQTT / MAVLINK_URL / (mTLS)
sudo systemctl enable --now drone-agent
systemctl status drone-agent
journalctl -u drone-agent -f                        # 看即時日誌
```

## 元件與埠

| 元件 | 角色 | 埠 |
|------|------|----|
| `drone-agent.service` | 長駐:遙測 1Hz + 心跳 30s + 訂閱雲端派遣 | — |
| mavsdk_server(agent 自 spawn) | MAVSDK↔飛控 gRPC 橋 | gRPC 50051、飛控 UDP 14540 |
| mission_exec(派遣時 spawn) | 任務狀態機子程序,共用 agent 的 mavsdk_server(`--mavsdk-address localhost:50051`) | — |

預設 `drone_agent` 自行 spawn mavsdk_server。若要跑 **standalone** mavsdk_server(升級 agent 不重啟飛控連線),於 `agent.env` 設 `EXTRA_ARGS=--mavsdk-address localhost:50051` 並另行常駐一個 mavsdk_server。

## 設定(`/etc/drone/agent.env`)

見 [`systemd/drone-agent.env.example`](systemd/drone-agent.env.example)。必填 `DRONE_ID` / `MQTT_HOST` / `MQTT_PORT` / `MAVLINK_URL` / `RATE`;選配旗標放 `EXTRA_ARGS`;mTLS 憑證路徑(`MQTT_TLS_CA/CERT/KEY`)由 `drone_agent/tls.py` 直接讀取。

**MAVLINK_URL 常見值**:SITL=`udpin://0.0.0.0:14540`;實機序列=`serial:///dev/ttyACM0:115200`(需在 unit 取消註解 `SupplementaryGroups=dialout`)。

## 安全與資源(unit 已內建)

- 以非 root `drone` 帳號跑;`NoNewPrivileges` / `ProtectSystem=strict` / `PrivateTmp` 等加固。
- `MemoryMax=512M` / `CPUQuota=80%` / `TasksMax=256`(D7 資源上限,按機型調)。
- `Restart=always` + 啟動限速(60s 內 10 次)承擔失效復原,避免崩潰迴圈打爆機器。
- ⚠️ 未設 `WatchdogSec`:agent 尚未實作 `sd_notify(WATCHDOG=1)`,貿然設定會被誤殺;硬看門狗待 agent 支援後啟用。

## 日誌輪替

日誌走 journald。限制磁碟佔用(Jetson eMMC 有限):`/etc/systemd/journald.conf` 設 `SystemMaxUse=200M`、`MaxRetentionSec=2week` 後 `sudo systemctl restart systemd-journald`。飛行 ULog 的回收上雲由 agent 的 `--log-svc-url` 負責,與服務日誌無關。

## 憑證佈建(provisioning)

Phase 1 對外部署需 per-device 憑證:由 [`cloud/pki`](../../cloud/pki) 以 `CN=<DRONE_ID>` 簽發 → 佈建到 `/etc/drone/certs/`(chmod 600,owner drone)→ 在 `agent.env` 指向。出廠燒錄 / HSM / 自動註冊流程屬硬體與安全決策(見 roadmap §5)。

## 升級 / 回滾

```bash
git -C <repo> pull                       # 或部署新版本 tag
sudo onboard/deploy/systemd/install.sh   # 冪等:重裝 venv 依賴 + unit
sudo systemctl restart drone-agent
```
回滾:checkout 舊 tag 後重跑 install.sh + restart。agent 唯讀遙測、任務狀態在雲端權威,重啟不影響飛行安全。

## 疑難排解

- **一直 restart**:`journalctl -u drone-agent -e` 看例外;常見=`MAVLINK_URL` 錯 / 飛控未連 / MQTT 不通。
- **`address already in use` 50051/14540**:同機已有 mavsdk_server;改用 `EXTRA_ARGS=--mavsdk-address localhost:50051` 共用。
- **序列埠 permission denied**:取消 unit 的 `SupplementaryGroups=dialout` 註解並 `daemon-reload` + restart。
- **進入 failed(啟動限速)**:`systemctl reset-failed drone-agent` 後再 start。
