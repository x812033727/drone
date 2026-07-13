# 50-5 軟體平台商用化路線圖(Phase 0 → Phase 1 軟體)

> rev 1 · 2026-07。本文是**軟體平台**從 Phase 0 POC 走向「客戶可部署的軟體產品」的執行路線圖與進度追蹤。
> 上位計畫、退出條件與實機里程碑以 [roadmap.md](../roadmap.md) 為準;本文只管軟體交付,不重定義 Phase 邊界。

## 1. 定位與誠實邊界

商用無人機的「可商用 + 可直接使用」對**實體機**而言,需實體飛控板、累計飛行小時、台/美/歐認證(見 [roadmap.md](../roadmap.md) Phase 3),屬多年物理與法規工程,**不在軟體範疇**。

本路線圖聚焦可純軟體推進、且能在**無實體硬體**下以 SITL/合成方式驗證的部分,目標把軟體平台提升到:

- 客戶能照文件安裝、帶**認證與 TLS**、可**版本化交付**(Helm)
- 有**機隊儀表板**與**任務派遣**的操作端
- 供應鏈**可稽核**(SBOM / 依賴掃描 / lock)
- 飛安**感知/安全邏輯**每 PR 回歸(限速/降落狀態機,SITL 邊界內)

凡因缺硬體只能做到 SITL/合成驗證者,於對應項目明確標註,不與需求正式驗證混淆。

## 2. 現況基線(2026-07 盤點確認,對齊 main @ S25)

| 子系統 | 狀態 | 說明 |
|--------|------|------|
| 飛行資料鏈 | ✅ 端到端可運作 | `drone_agent`(遙測→MQTT)、`mission_exec`(任務狀態機 + MissionCommand PAUSE/RESUME/ABORT + 斷點續飛)、`cloud/ingest`(→TimescaleDB→Grafana)、`dispatch` CLI |
| 失效保護 + 任務場景回歸 | ✅ SITL 實測 | F05–F08 自動任務 + F09–F12 失效保護 + nightly SITL/uXRCE-DDS 煙霧 |
| 契約層 | ✅ 成熟 | `interfaces/proto` v0.4(telemetry/mission/events/sensors,buf lint + 生成碼同步驗證)+ `mavlink/` 自訂 dialect + `payload/` schema |
| 高頻感測橋 | ✅ 已做 | `onboard/ros2_ws/src/px4_mqtt_bridge`(DDS→MQTT 感測器橋) |
| 影像管線 | ✅ POC + 錄存回放 | MediaMTX 常駐錄存棧 + sender(v4l2 源)+ 回放煙霧 |
| 雲端服務層 | 🟡 起步 | `cloud/log_svc`(FastAPI:ULog 上傳/解析/異常開單)已建,確立 FastAPI 服務範式;**仍缺 fleet-svc / mission-svc / REST 讀取 API** |
| 操作端前端 | ⭕ 未做 | 僅 Grafana;`gcs/` 只有 README |
| 安全機制 | ⭕ Phase 0 明列豁免 | 無 mTLS/裝置憑證/ACL/API 認證 |
| ROS2 感知節點 | ⭕ 未做 | 有 `bridge_smoke` 煙霧 + `px4_mqtt_bridge`;**仍缺 obstacle_guard / precision_land 感知安全節點** |
| 工程成熟度 | ⚠️ 部分 | 有 ruff+pytest+CI(含 cloud-smoke/proto)+ CLAUDE.md 慣例;缺 lock/型別/覆蓋率/掃描/release 流程 |
| 自研飛控/韌體/GCS/硬體/結構 | ⭕ 純規劃 | README/骨架文件(含 OTA 規格、派遣契約、GCS 骨架),無實作碼(屬 Phase 1+ 或硬體) |

> 註:`cloud/log_svc` 已採 **FastAPI + 釘版 requirements + Dockerfile + 純函式測試** 的結構,後續 fleet-svc / mission-svc **沿用此既有範式**,不另立新樣式。

## 3. 波次與進度

> 逐 PR 推進,CI 綠才 merge。狀態:⬜ 未開始 / 🟡 進行中 / ✅ 已合併。

### Wave 0 — 工程地基
| 項 | 內容 | 狀態 |
|----|------|------|
| E1 | 依賴鎖定(uv lock)+ CI 從 lock 安裝 | ⬜ |
| E2 | mypy(scope cloud/ 與新程式)+ ruff format --check | ⬜ |
| E3 | pytest-cov + 門檻;移除 ci.yml exit-5 容忍 | ⬜ |
| E4 | 一鍵入口(Makefile:dev/test/lint)+ onboarding | ⬜ |
| E5 | Dependabot + CodeQL + pip-audit(non-blocking) | ⬜ |
| E6 | release 流程(tag/CHANGELOG)+ 釘死映像 digest | ⬜ |
| E7 | 文件校正 + 本路線圖入庫 | 🟡 |

### Wave 1 — 雲端服務地基
| 項 | 內容 | 狀態 |
|----|------|------|
| A1 | `cloud/common` 共用庫(decode 上移)+ cloud-services CI | ⬜ |
| A2 | PostGIS 實例 + Alembic migration 骨架 | ⬜ |

### Wave 2 — 服務層(FastAPI)
| 項 | 內容 | 狀態 |
|----|------|------|
| B1 | fleet-svc CRUD(device/fleet/firmware) | ⬜ |
| B2 | 在線狀態消費者 + SSE stream | ⬜ |
| B3 | mission-svc CRUD(route/mission) | ⬜ |
| B4 | 派遣 + 進度回收(CLI 降薄客戶端) | ⬜ |

### Wave 3 — 操作端 Web 主控台
| 項 | 內容 | 狀態 |
|----|------|------|
| W1 | 前端骨架 + web-ci | ⬜ |
| W2 | 機隊清單 + 地圖即時位置 | ⬜ |
| W3 | 任務派遣 UI | ⬜ |
| W4 | 告警 | ⬜ |
| W5 | 部署打包(nginx + compose) | ⬜ |

### Wave 4 — 安全硬化
| 項 | 內容 | 狀態 |
|----|------|------|
| C1 | PKI(step-ca)+ 簽發/輪換/CRL + SITL 裝置身分 | ⬜ |
| C2a | EMQX + mTLS(明文向後相容) | ⬜ |
| C2b | 強制 mTLS + per-device ACL + CRL | ⬜ |
| C3 | API 認證(JWT/OIDC)+ RBAC + 關匿名 | ⬜ |

### Wave 5 — 機載感知/安全節點(SITL 邊界)
| 項 | 內容 | 狀態 |
|----|------|------|
| P0 | 純安全邏輯庫(零 ROS,每 PR 回歸) | ⬜ |
| P1 | obstacle_guard node(Collision-Prevention) | ⬜ |
| P2 | SITL 合成整合(Tier 1) | ⬜ |
| P3 | precision_land 狀態機 + node | ⬜ |
| P4 | nightly 佈線 | ⬜ |

### Wave 6 — 部署交付 + 供應鏈
| 項 | 內容 | 狀態 |
|----|------|------|
| D1 | Helm chart(客戶交付物) | ⬜ |
| D2 | SBOM + 依賴掃描 blocking + 映像釘選 | ⬜ |

## 4. 已拍板架構決策

- 服務層 **Python/FastAPI**(不寫 Go);裝置閘道採現成 broker → 本決策使 [cloud-fleet.md](../../20-software/cloud-fleet.md) §4「後端 Go+Python」需同步修訂為「後端 Python;閘道採現成 broker(EMQX);Go 僅實測熱點時個案引入」。
- Broker **EMQX**(內建動態 ACL/CRL/HTTP auth hook)。
- 資料庫:遙測 **TimescaleDB**(不動)+ 關聯/地理 **獨立 PostGIS** 實例 + Alembic migration。
- PKI **smallstep step-ca**;API 認證 **驗外部 JWT(OIDC-ready)** + RBAC。
- 即時傳輸 **SSE**;讀取 API 由 **fleet-svc 兼任**;避障 **PX4 Collision-Prevention**。

## 5. 明確範圍外(需硬體或屬他子系統)

🔒 出廠憑證燒錄(FC-H7/Jetson flash)、TPM/SE;🔒 MAVLink 2 signing + GCS 配對、SIM/IMEI 綁定、WireGuard 遠端診斷(屬 onboard/GCS);OTA 簽章鏈(跨 firmware/onboard);自研飛控韌體、硬體、結構、物理認證。安全分階段落地總表以 [security.md §8](../../20-software/security.md) 為準。

## 6. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:軟體商用化四軌路線圖(Wave 0–6)+ 現況基線盤點 + 架構決策 |
