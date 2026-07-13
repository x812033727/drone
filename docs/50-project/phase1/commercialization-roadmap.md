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
| 雲端服務層 | ✅ 已建 | `cloud/log_svc`(ULog 上傳/解析/開單)+ `fleet_svc`(機隊/裝置/韌體 CRUD + `/status` + SSE `/stream`)+ `mission_svc`(航線/任務 CRUD + 派遣 + 進度冪等回收);全採 FastAPI + asyncpg + 版本化前向 migration。**待補:log_svc 認證、org 多租戶隔離、分頁、可觀測性(見 §7)** |
| 操作端前端 | ✅ 已建(唯讀 MVP) | `gcs/web-console`(React+MapLibre 即時地圖 + 機隊清單 + OIDC SSO/PKCE 登入 + nginx 部署)。**待補:任務規劃/派遣/裝置管理寫入 UI、告警、前端 RBAC(見 §7)** |
| 安全機制 | ✅ 已建 | PKI(openssl CA/簽發/輪換/CRL)+ MQTT mTLS + per-device ACL + CRL 強制 + 客戶端 TLS(全連線端)+ 整棧 mTLS overlay + Helm mTLS + API JWT/RBAC + OIDC/JWKS 後端驗簽。**待補:log_svc 認證、預設棧仍明文(見 §7)** |
| ROS2 感知節點 | 🟡 部分 | `px4_mqtt_bridge`(DDS→MQTT 感測橋)+ `obstacle_guard`(P0 純安全邏輯庫 + P1 colcon ROS node,ros-build-ci 守門);**仍缺 precision_land 狀態機/node** |
| 工程成熟度 | ✅ 大致完成 | ruff+pytest+CI(cloud-smoke/proto/coverage/mtls/helm/ros/security)+ SBOM(SPDX+CycloneDX)+ Dependabot/CodeQL/pip-audit + pre-commit + CLAUDE.md 慣例。**待補:依賴 lock、mypy、release/tag/CHANGELOG 流程(見 §7)** |
| 自研飛控/韌體/GCS/硬體/結構 | ⭕ 純規劃 | README/骨架文件(含 OTA 規格、派遣契約、GCS 骨架),無實作碼(屬 Phase 1+ 或硬體) |

> 註:`cloud/log_svc` 已採 **FastAPI + 釘版 requirements + Dockerfile + 純函式測試** 的結構,後續 fleet-svc / mission-svc **沿用此既有範式**,不另立新樣式。

## 3. 波次與進度

> 逐 PR 推進,CI 綠才 merge。狀態:⬜ 未開始 / 🟡 進行中 / ✅ 已合併。

### Wave 0 — 工程地基
| 項 | 內容 | 狀態 |
|----|------|------|
| E1 | 依賴鎖定(uv lock)+ CI 從 lock 安裝 | ⬜ 未做 |
| E2 | mypy(scope cloud/ 與新程式)+ ruff format --check | ⬜ 未做 |
| E3 | pytest-cov + 門檻;移除 ci.yml exit-5 容忍 | ✅ #63 |
| E4 | 一鍵入口(Makefile:dev/test/lint)+ onboarding | ✅ #54 |
| E5 | Dependabot + CodeQL + pip-audit(non-blocking) | ✅ #53 |
| E6 | release 流程(tag/CHANGELOG)+ 釘死映像 digest | ⬜ 未做 |
| E7 | 文件校正 + 本路線圖入庫 | ✅ #52 + rev 2 |

### Wave 1 — 雲端服務地基
| 項 | 內容 | 狀態 |
|----|------|------|
| A1 | `cloud/common` 共用庫(decode 上移)+ cloud-services CI | ⬜ 未做(各服務暫各自複製 auth.py/migrate.py) |
| A2 | ~~PostGIS 實例 + Alembic~~ → **架構調整**:單一 timescaledb 的 `fleet`/`mission` schema + 自研版本化前向 SQL migration runner | ✅(見 §4) |

### Wave 2 — 服務層(FastAPI)
| 項 | 內容 | 狀態 |
|----|------|------|
| B1 | fleet-svc CRUD(device/fleet/firmware) | ✅ #55 |
| B2 | 在線狀態消費者 + SSE stream | ✅ #56 |
| B3 | mission-svc CRUD(route/mission) | ✅ #58 |
| B4 | 派遣 + 進度回收(CLI 降薄客戶端) | ✅ #58 |

### Wave 3 — 操作端 Web 主控台
| 項 | 內容 | 狀態 |
|----|------|------|
| W1 | 前端骨架 + web-ci | ✅ #57 |
| W2 | 機隊清單 + 地圖即時位置 | ✅ #57 |
| W3 | 任務派遣 UI | ⬜ **未做(後端契約已存在,前端未接;見 §7 P0)** |
| W4 | 告警 | ⬜ **未做(見 §7 P0)** |
| W5 | 部署打包(nginx + compose) | ✅ #57 |

### Wave 4 — 安全硬化
| 項 | 內容 | 狀態 |
|----|------|------|
| C1 | PKI(**openssl**,非 step-ca)+ 簽發/輪換/CRL + SITL 裝置身分 | ✅ #65 |
| C2a | **mosquitto**(非 EMQX)+ mTLS(明文向後相容)+ per-device ACL | ✅ #66 |
| C2b | 強制 mTLS + CRL + 客戶端 TLS(全連線端)+ 整棧 overlay | ✅ #67/#68/#69/#70 |
| C3 | API 認證(JWT/OIDC-JWKS)+ RBAC + 關匿名 | ✅ #60/#71(**⚠️ log_svc 尚未接、預設棧仍明文,見 §7 P0**) |

### Wave 5 — 機載感知/安全節點(SITL 邊界)
| 項 | 內容 | 狀態 |
|----|------|------|
| P0 | 純安全邏輯庫(零 ROS,每 PR 回歸) | ✅ #59 |
| P1 | obstacle_guard node(colcon ROS,ros-build-ci) | ✅ #74 |
| P2 | SITL 合成整合(Tier 1) | 🟡 nightly SITL 觀察中 |
| P3 | precision_land 狀態機 + node | ⬜ **未做** |
| P4 | nightly 佈線 | 🟡 部分(sitl-integration + ros/dds 煙霧) |

### Wave 6 — 部署交付 + 供應鏈
| 項 | 內容 | 狀態 |
|----|------|------|
| D1 | Helm chart(客戶交付物) | ✅ #61 + mTLS values #72 |
| D2 | SBOM(SPDX+CycloneDX)+ 依賴掃描 + 映像釘選 | ✅ #64(掃描 non-blocking;映像 digest 釘選待 E6) |

## 4. 架構決策(as-built,rev 2 對齊實作)

> rev 1 規劃了數個「現成重量級元件」,實作時基於**零依賴、易稽核、與既有棧一致**的原則做了調整。下表為**實際落地**版本,取代 rev 1 的規劃值。

| 面向 | rev 1 規劃 | **as-built(實作)** | 調整原因 |
|------|-----------|--------------------|----------|
| 服務層 | Python/FastAPI(不寫 Go) | ✅ Python/FastAPI + asyncpg,沿用 log_svc 範式 | 一致 |
| MQTT broker | EMQX(動態 ACL/CRL/auth hook) | **eclipse-mosquitto:2** + 靜態 per-device ACL(`use_identity_as_username`)+ CRL | mosquitto 零依賴、mTLS+ACL+CRL 已足;EMQX 的動態 hook 待需要時再引入 |
| 資料庫 | TimescaleDB + **獨立 PostGIS** + Alembic | **單一 timescaledb** 的 `fleet`/`mission` schema + 自研版本化前向 SQL migration runner(`migrate.py` + `schema_migrations` 表) | 位置存 lat/lon 雙精度即足,免多一個 PostGIS 實例;前向 SQL 比 Alembic 輕、易審 |
| PKI | smallstep **step-ca** | **openssl** CA(`cloud/pki/*.sh` + `openssl.cnf`) | 零依賴、易稽核、CI 可完整驗 |
| API 認證 | 驗外部 JWT(OIDC-ready)+ RBAC | ✅ HS256 dev / RS256-JWKS 生產 + viewer<operator<admin RBAC + OIDC/PKCE 前端 | 一致(空字串 env 視為未設) |
| 即時傳輸 | SSE | ✅ SSE(token 走 query,EventSource 無法帶 header) | 一致 |
| 避障 | PX4 Collision-Prevention | 🟡 `obstacle_guard` 純邏輯已測 + ROS node;**未閉環到 PX4**(見 §7) | 感知源需硬體 |

> ⚠️ [cloud-fleet.md](../../20-software/cloud-fleet.md) §4 若仍寫 EMQX/PostGIS/step-ca/Go,應同步以本表為準修訂。

## 5. 明確範圍外(需硬體或屬他子系統)

🔒 出廠憑證燒錄(FC-H7/Jetson flash)、TPM/SE;🔒 MAVLink 2 signing + GCS 配對、SIM/IMEI 綁定、WireGuard 遠端診斷(屬 onboard/GCS);OTA 簽章鏈(跨 firmware/onboard);自研飛控韌體、硬體、結構、物理認證。安全分階段落地總表以 [security.md §8](../../20-software/security.md) 為準。

## 7. as-built 缺口登錄(2026-07-13 五維架構稽核)

> Wave 0–6 已交付後,對「可商用 + 可直接部署」做全架構稽核,列**程式可達**的剩餘缺口(需外部認證/硬體者見 §5)。逐項以 PR 補齊,CI 綠自動合併。
>
> **完成進度(2026-07-13)**:✅ **P0 G1–G10 全數完成**(可直接部署門檻達標)。✅ **P1 已完成 15 項**:G12/G13/G14/G15/G16/G17/G18/G19/G20/G21/G22/G24/G25/G26/G29。⬜ **P1 剩餘(程式可達,較大/需欄位決策,待排程)**:G23 OTA 機載代理(設計齊、實作量大)、G27 MAVLink dialect/payload 定案(需欄位決策)、G28 派遣 proto FleetMission(尚無消費端)。🔒 **需使用者產品決策**:G11 org 多租戶隔離(需租戶模型)、G30 計費/用量/配額、G31 前端執行期注入、租戶/使用者管理、token 安全策略。

### P0 — 部署阻擋 / 對外裸奔(✅ 全數完成)
| # | 缺口 | 狀態 |
|---|------|------|
| G1 | 無 CI 建置/發布容器映像到 registry(`helm install` ImagePullBackOff) | ✅ #88 release.yml→GHCR+provenance/SBOM |
| G2 | Helm 不 provision Grafana 儀表板/資料源 | ✅ #96 grafana-provisioning ConfigMap |
| G3 | 全 workload 缺 livenessProbe | ✅ #96 全 workload liveness |
| G4 | 容器以 root 跑、無 securityContext | ✅ #96 helm securityContext + #97 映像非 root uid 1000 |
| G5 | log_svc 零認證 | ✅ #93 JWT+RBAC |
| G6 | 機載無 systemd unit / 部署 | ✅ #94 drone-agent.service+install.sh+Jetson 文件 |
| G7 | MediaMTX 影像串流零認證 | ✅ #98 authInternalUsers env 注入 |
| G8 | 預設 compose 棧明文/匿名 | ✅ 文件涵蓋(#98 runbook 明列安全棧=mtls overlay+JWT) |
| G9 | 無端到端部署 runbook | ✅ #98 deployment-runbook.md |
| G10 | web-console 缺寫入 UI + 前端 RBAC | ✅ #99 裝置/任務/派遣/RBAC/告警 |

### P1 — 生產/商用必要
**✅ 已完成**:G12 API 分頁(#103,limit/offset+X-Total-Count)·G13 metrics/告警/SLO(#101)·G14 審計日誌(#106,audit_log 表+GET /audit admin 分頁+旁路 best-effort)·G15 DB 備份 CronJob(#100)·G16 migration pre-upgrade hook Job(#100)·G17 NetworkPolicy+PDB(#100)·G18 cosign keyless 簽章(#102)·G19 CHANGELOG+GitHub Release(#102)·G20 資料保留(#103,timescale retention/壓縮)·G21 ingest healthz+重試/DLQ(#103)·G22 機載憑證到期偵測+輪換提示(#107)·G24 遙測離線緩衝(#107,有界環形緩衝+FIFO 補發)·G25 dependabot 補目錄+npm(#87)·G26 OpenAPI 契約+守門(#102)·G29 依賴 lock(pip-tools)+ mypy(#105,quality-gates.yml)。

**⬜ 剩餘(程式可達,較大或需欄位決策,待排程)**:G23 OTA 機載代理(設計已齊於 ota.md,實作量大;且與 firmware 雙 bank/Jetson 代燒方案交織,見 §5)·G27 MAVLink dialect/payload schema 定案(SPRAY_TELEMETRY/BATTERY_DETAIL/PAYLOAD_STATUS 欄位需拍板)·G28 cloud 派遣 proto FleetMission(尚無消費端,價值待派遣鏈成形)。

**🔒 需使用者產品決策**:G11 org 多租戶隔離(需租戶模型)·G30 計費/用量/配額/限流(需計價維度)·G31 前端執行期環境注入。

### P1/P2 — 需設計決策或外部
precision_land 狀態機、租戶/使用者管理模型、token 安全(localStorage/refresh)、多環境 values profile、HPA、SOC2/UN38.3/SORA(外部認證)、真實深度感知(硬體)。

## 8. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:軟體商用化四軌路線圖(Wave 0–6)+ 現況基線盤點 + 架構決策 |
| 2 | 2026-07-13 | Wave 0–6 交付後對齊:§2 現況/§3 波次狀態更新為實際合併(#52–#75)、§4 改為 as-built(mosquitto/openssl/單一 timescaledb+前向 SQL,取代 EMQX/step-ca/PostGIS+Alembic)、新增 §7 as-built 缺口登錄(五維架構稽核,P0 G1–G10 逐項補齊) |
| 3 | 2026-07-13 | §7 缺口補齊:P0 G1–G10 全數完成(可直接部署達標,#87–#99);P1 完成 12 項(#100–#103:備份/migration hook/NetworkPolicy+PDB/可觀測性/cosign/CHANGELOG/分頁/保留/ingest healthz+DLQ/OpenAPI 契約);標註剩餘程式可達 P1 與需產品決策項 |
