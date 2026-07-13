# mission-svc — 航線/任務派遣

> 對 [docs/20-software/cloud-fleet.md §6](../../docs/20-software/cloud-fleet.md) 派遣契約。
> 把 [tools/dispatch_mission.py](../../tools/dispatch_mission.py) 的派遣升為服務;沿用
> [cloud/fleet_svc](../fleet_svc/README.md) 的 FastAPI + asyncpg + 輕量 migration 範式。

## 職責

- 航線庫(route)+ 任務(mission)CRUD;資料落既有 timescaledb 的 `mission` schema。
- **派遣**:`MissionPlan` → `fleet/{drone_id}/cmd/mission`(QoS 1)。
- **控制**:`MissionCommand`(pause/resume/abort)→ `fleet/{drone_id}/cmd/mission_ctrl`。
- **進度回收**:訂 `fleet/+/mission/progress`,更新任務權威狀態(**首個終態為準**,冪等去重);
  mission-svc 擁生命週期,`cloud/ingest` 仍留 TSDB 進度歷史供 Grafana(職責分離)。

## API(`/api/v1`)

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST/GET | `/routes` · GET `/routes/{id}` | 航線庫 |
| POST | `/missions` | 由 route × drone 建任務(凍結航點、產生 mission_id) |
| GET | `/missions?drone_id=` · `/missions/{id}` | 列出 / 取單筆 |
| POST | `/missions/{id}/dispatch` | 派遣(status=created 才可;否則 409) |
| POST | `/missions/{id}/command` | 對執行中任務發 pause/resume/abort |
| GET | `/healthz` | DB 探活 |

## 狀態機

`created → dispatched →`(進度事件)`received/uploaded/in_progress/paused → completed/failed`。
`mission_id` 為端到端追溯鍵(機-雲共用)。終態不可逆(首個終態為準)。

## 認證邊界

本 PR 端點未帶認證(Wave 4 C3 加 JWT);broker 為 Phase 0 anonymous(security.md §8),
compose 綁 loopback,僅限開發內網。
