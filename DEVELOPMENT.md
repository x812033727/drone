# 開發快速開始

本 repo 的一鍵開發入口是根目錄 `Makefile`。完整鐵則與慣例見 [CLAUDE.md](CLAUDE.md)。

```bash
make help          # 列出所有可用目標
make install       # 建 .venv + 安裝所有子系統依賴(對齊 CI)
make lint test     # ruff + pytest(不需 SITL/docker)
make dev           # 起本機雲端棧(隔離高位埠,結束用 make dev-down)
make sitl          # 起 headless PX4 SITL 容器
make proto         # 改 .proto 後重新生成程式碼
```

## 慣例提醒(細節見 CLAUDE.md)

- **本機資源一律用獨特名 + 高位埠**:此機同時跑著多個正式服務,`make dev` 已預設隔離埠(MQTT 31883 / PG 35432 / Grafana 33100…),可用環境變數覆寫。結束務必 `make dev-down`(含 `-v` 清 volume)。
- **compose 指令**:本機為 `docker-compose`(standalone);其他環境可 `make COMPOSE="docker compose" dev`。
- **SITL**:該映像主動送 MAVLink 到 docker gateway,**勿做 `-p` 埠映射**(見 CLAUDE.md 鐵則 1)。
- **proto 契約**:改 `.proto` 先跑 `make proto` 重生並 commit 生成碼(CI 會驗漂移)。

## 端到端本機驗證(無實機)

```bash
make dev                                              # 起雲端棧
. .venv/bin/activate
python tools/publish_fake_telemetry.py --mqtt-port 31883 --count 20   # 灌假遙測
# 開 http://localhost:33100 看 Grafana fleet 看板
make dev-down                                         # 收工清乾淨
```
