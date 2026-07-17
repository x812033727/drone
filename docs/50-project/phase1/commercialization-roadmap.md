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
| P3 | precision_land 狀態機 + node | ✅ #117(狀態機 SEARCH→ACQUIRED→DESCEND→LANDED+REACQUIRE/ABORT,colcon 實建,32 測試;真感知源/PX4 橋接屬 Phase 1) |
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
> **完成進度(2026-07-13,全數清零)**:✅ **P0 G1–G10 全數完成**(可直接部署門檻達標)。✅ **P1/前瞻缺口 G11–G31 全數完成**(含 G11 org 多租戶隔離 + G11b SSE 串流隔離、G23 OTA 機載代理、G27 dialect 定案、G28 派遣 proto、G30 用量/配額/限流、G31 前端 runtime 注入)。**所有「程式可達」缺口皆已補足並端到端驗證合併**。**唯一剩餘 = 需外部/決策**:金流 payment provider 串接(需綠界/Stripe 決策;計量底座 usage_counter 已備)、UN38.3/SORA/SOC2 認證與實體硬體製造(需外部機構/工廠,見 §5)。
>
> **運營化補完(2026-07-13 續)**:✅ org/租戶/配額管理後端(#118,fleet.org plan/status/配額覆寫 + admin /orgs CRUD + suspended 擋寫)· ✅ 租戶管理 + 用量檢視 UI(#119,admin gating)· ✅ **綠界 ECPay 訂閱金流(#120)**:checkout + CheckMacValue 驗章(綠界官方測試向量 known-answer 驗證)+ webhook 啟用方案 + billing_transaction,零硬編憑證(沙箱/正式走 env)· ✅ precision_land 精準降落(#117,Wave5 P3)。**商業化全可運營;綠界正式上線僅需填 ECPAY_* env。**

### 第二輪整合稽核(2026-07-13,對新功能之間的接線)
> 大量新功能上線後再稽核「跨元件斷點」,補足如下:
> - ✅ **跨 org 派遣安全漏洞**(#123):mission_svc 建任務未驗證目標機所有權 → 讀 fleet.device 的 org 擋跨 org(404),真 PG 驗證。
> - ✅ **ECPay 部署注入點**(#124):Helm secret/values + compose 加 ECPAY_*/配額 env(先前客戶部署金流靜默跑沙箱)。
> - ✅ **OTA 雲端觸發端**(#125):fleet_svc `POST /devices/{id}/ota` + `tools/dispatch_ota.py`(payload round-trip 餵回 ota.py 驗證);先前機載訂了雲端無從觸發。
> - ✅ **告警閉環**(#125 後端 + #126 前端):ingest 訂閱 `fleet/+/alerts`+`ota/progress`→device_alerts 表→fleet_svc `GET /alerts`(多租戶)→web-console 告警分頁;先前 cert/OTA 告警發了無人收。
> - ✅ **Prometheus scrape**(#124):compose(profile 隔離)+ Helm prometheus.yaml,scrape 四服務 /metrics + 載入 alert-rules;先前 /metrics 與告警規則無人消費。
> - ✅ **前端自助訂閱**(#122):web-console 升級/結帳 UI 導向綠界;先前 billing 後端可達、operator 無入口。
> - ✅ **cloud/common 去重**(#127,Wave1 A1):抽 drone_common(auth 純邏輯/migrate/audit),保守拆分保住測試耦合、行為零改變。
>
>
> **後續補完(#129/#130)**:✅ 韌體管理 + OTA 推送 UI(#129,後端 #125 有端點無前端 → 補齊,OTA 操作閉環端到端通:console 推送→端點→機載→進度走告警分頁)。✅ **限流改 DB-backed 精確**(#130,`rate_limit_counter` fixed-window 原子 upsert,多副本精確,真 PG 200×2 併發驗 final=400 唯一)——解掉原「需 Redis」的 per-process 近似,**免引入 Redis**。
>
> **僅餘 2 項刻意延後(誠實)**:①FleetMission 派遣 proto(#109)無消費端——前瞻契約,現行派遣走 mission.proto 已運作,無使用場景故不強接(要接需重構可運作的派遣流,零功能增益);②影像串流整合進 console——video_pipeline 屬 POC、無真實相機(Jetson+相機為 Phase 1 硬體),為不存在的 feed 做 WHEP/WebRTC 瀏覽器整合屬低價值臆測,待真實影像源到位再做。
>
> **仍餘 P2(低價值/需決策/需硬體,刻意延後)**:①FleetMission 派遣 proto(#109)無消費端——前瞻契約,現行派遣走 mission.proto 已運作,無使用場景故不強接;②per-org 限流(#115)為 per-process,replicas>1 近似——精確全域限流需 Redis(部署基礎設施決策),DB-backed 用量/配額本身正確;③影像串流整合進 console——video_pipeline 屬 POC,真實機載相機/Jetson 為 Phase 1 硬體,無真實影像源前整合價值有限。

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
**✅ 已完成**:G12 API 分頁(#103,limit/offset+X-Total-Count)·G13 metrics/告警/SLO(#101)·G14 審計日誌(#106,audit_log 表+GET /audit admin 分頁+旁路 best-effort)·G15 DB 備份 CronJob(#100)·G16 migration pre-upgrade hook Job(#100)·G17 NetworkPolicy+PDB(#100)·G18 cosign keyless 簽章(#102)·G19 CHANGELOG+GitHub Release(#102)·G20 資料保留(#103,timescale retention/壓縮)·G21 ingest healthz+重試/DLQ(#103)·G22 機載憑證到期偵測+輪換提示(#107)·G24 遙測離線緩衝(#107,有界環形緩衝+FIFO 補發)·G25 dependabot 補目錄+npm(#87)·G26 OpenAPI 契約+守門(#102)·G27 MAVLink dialect/payload schema 定案(SPRAY_TELEMETRY/BATTERY_DETAIL/PAYLOAD_STATUS 三訊息 rev 1 + payload descriptor schema 二進位/CRC/防寫定案,mavgen 往返 + jsonschema 驗證通過)·G29 依賴 lock(pip-tools)+ mypy(#105,quality-gates.yml)。

**✅ 已完成(續,最終波)**:G11 org 多租戶隔離(#113,JWT org claim+逐查詢過濾+跨 org 404+真 PG 驗)+ G11b SSE 串流 org 過濾(#114,drone_id 白名單)·G23 OTA 機載代理(#111,Ed25519 簽章 A/B slot+斷點續傳+健檢回滾;實體 flash 屬 Phase 3)·G28 派遣 proto FleetMission/MissionAssignment(#109,buf lint/breaking 綠+生成碼重生)·G30 用量計量 usage_counter+配額 402+限流 429(#115,零依賴 token bucket)·G31 前端 runtime config.js 注入(#110,一份映像多環境)。

**🔒 唯一剩餘 = 需外部/決策(非程式可達)**:payment provider 金流串接(需綠界/Stripe 決策;usage_counter 計量底座已備)·UN38.3/SORA/SOC2 認證·實體硬體製造與適航(見 §5)。

### P1/P2 — 需設計決策或外部
precision_land 狀態機、租戶/使用者管理模型、token 安全(localStorage/refresh)、多環境 values profile、HPA、SOC2/UN38.3/SORA(外部認證)、真實深度感知(硬體)。

## 7.1 第二輪四軌補強(2026-07-16~17,#135–#165)

> §7 的「程式可達缺口」清零後,開新戰線把四個原本停在規劃/POC 的維度推進到
> SITL/合成源可驗。CI 綠自動合併,逐 PR 推進,共 **32 支全數合併**。

### 韌體軌(firmware/,原僅 README → PX4 客製可建可驗)
- F1 建置鷹架 + firmware-ci(釘版 PX4 v1.15.4 shallow clone + ccache,path-gate)
- F2 out-of-tree 模組機制(EXTERNAL_MODULES_LOCATION;payload_sim + 3 自訂 uORB)
- F3 drone_sitl dialect 上機(wrapper + inject + patch 0001)
- **F4 三自訂訊息 SITL 實收里程碑**(streams patch 0002;pymavlink 實收欄位往返)
- F5 PA-1 SIH airframe(patch 0003 + 參數包回讀)· F6 失效保護矩陣對 §4 回歸
- F7 geofence GeoJSON→PX4 圍欄轉換器 · F8 圍欄上傳-回讀 SITL 容量實測
- F9 drone_spray 農噴模組(流量閉環 + 斷藥觸發,標準 vehicle_command 不動狀態機)
- 誠實延後:SMBus BMS 驅動本體、FC-H7 board bring-up、armed-飛行 RTL 行為(nightly gazebo 層)

### 影像軌(POC → 合成源閉環)
- V1 常駐棧 webrtc + drone/<serial> path · V2 web-console VideoPanel(原生 WHEP)
- V3 fleet JWT ↔ MediaMTX 認證橋(org 隔離)· V4 simcam 合成相機容器
- V5 Helm mediamtx template · **V6 aiortc 媒體面探針**(ICE/DTLS/SRTP 收幀 + 解像素時戳)

### 穩健度軌(可商用 → 可扛量/可信賴,不加新功能)
- R1 loadgen 基座 · R2 SSE 訂閱者 gauge + 壓測 · R3 load-smoke(PR 可用性 + nightly)
- R4 chaos 三場景(DB 重啟/DLQ/MQTT 重連)· R5 Playwright tier-1(blocking)· R6 tier-2 真棧
- R7 schemathesis fuzz(**抓到並修 offset int8 溢位 500**)· R8 hypothesis 屬性測試 · R9 基準回填

### GCS 軌(web-console 深化 + dialect 消費鏈;不深 fork QGC)
- G1 README 對齊 S16 決策 · G2 mavlink-ci dialect 守門 · G3 qgc-profiles 參數/範本
- G4 QGC .plan 轉換器 + dispatch --plan · G5 地圖點擊繪航點
- **G6-G8 dialect 消費鏈**:payload.proto + drone_agent payload_listener + ingest 落庫 + console

### 端到端里程碑
SITL(payload_sim → streams → MAVLink)→ drone_agent(pymavlink 解碼)→ MQTT →
ingest → TimescaleDB → console 全鏈路實測通;aiortc WHEP 媒體面全鏈路實證(收幀 + 時戳)。

### nightly/weekly 觀測(continue-on-error + 失敗開 issue)
sitl-integration(02:30)· load-smoke(03:10)· chaos-drill(03:40)·
video-probe(03:50)· web-e2e-stack(04:10)· api-fuzz(weekly)。連綠兩週後逐項評估升 blocking。

**2026-07-17 觀測期六支各手動跑一次確認,並修掉暴露的問題(全數合併,現皆綠):**
- **load-smoke → #167 → 修 #168**:nightly 50-user 檔位打出 `POST /dispatch` 並發 500。根因 mission-svc 派遣用**固定 MQTT client-id**,broker 同 id 互踢 → QoS1 PUBACK 遺失 → 10s 逾時。修法=每次連線唯一 client-id;隔離棧重跑 dispatch 500 **3→0**、max 延遲 **10000ms→143ms**。
- **api-fuzz** 連三修穩定綠(**#169** timeout 25→50m、**#170** `--no-shrink`、**#171** weekly examples 300→120):weekly 深跑對已知 500 端點反覆 shrinking 且 volume-bound,原 25m 逾時被標 cancelled;三修疊加後 **6 分鐘綠**。
- **sitl-integration**:`failsafe-scenarios (f11)` 首跑因 SITL 起飛未爬升的**環境 flake**(框架自標「場景環境錯誤」)失敗,重跑即綠;其餘 5 支一次綠。
- **✅ 已修(#173)**:api-fuzz 揭露的 5 個 schemathesis 500 findings 全數轉 422——① ② ③ serial/org_id/name lone Unicode surrogate(asyncpg 綁 text 做 UTF-8 編碼 `UnicodeEncodeError`)、④ ⑤ max_devices/max_fleets 超大整數(int4 `OverflowError`)。修法:`_WriteModel` 基底掃全字串欄位拒 surrogate + 配額 `le=INT4_MAX` + `RequestValidationError` 處理器 `ensure_ascii` 序列化(預設處理器回顯 surrogate input 使 422 回應本身炸成 500,才是真正的 500 來源)。

### 誠實邊界(仍需外部/硬體)
實體飛控板/FC-H7 bring-up、SMBus BMS 驅動、真相機(Jetson)、TURN/NAT、
UN38.3/SORA/SOC2 認證、金流正式憑證——不在 SITL/合成可達範圍。負載基準數字
為共用開發機實測僅供迴歸對照,正式容量規劃須專屬硬體重跑。

## 8. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07 | 初版:軟體商用化四軌路線圖(Wave 0–6)+ 現況基線盤點 + 架構決策 |
| 2 | 2026-07-13 | Wave 0–6 交付後對齊:§2 現況/§3 波次狀態更新為實際合併(#52–#75)、§4 改為 as-built(mosquitto/openssl/單一 timescaledb+前向 SQL,取代 EMQX/step-ca/PostGIS+Alembic)、新增 §7 as-built 缺口登錄(五維架構稽核,P0 G1–G10 逐項補齊) |
| 4 | 2026-07-13 | 全數清零:最終波 G11+G11b 多租戶(REST+SSE)、G23 OTA、G27 dialect、G28 派遣 proto、G30 用量/配額/限流、G31 前端 runtime 注入全部合併;所有程式可達缺口補足,唯餘 payment 串接+外部認證+硬體 |
| 3 | 2026-07-13 | §7 缺口補齊:P0 G1–G10 全數完成(可直接部署達標,#87–#99);P1 完成 12 項(#100–#103:備份/migration hook/NetworkPolicy+PDB/可觀測性/cosign/CHANGELOG/分頁/保留/ingest healthz+DLQ/OpenAPI 契約);標註剩餘程式可達 P1 與需產品決策項 |
| 5 | 2026-07-17 | 新增 §7.1 第二輪四軌補強(#135–#165,32 支全合):韌體 F1–F9(PX4 客製 SITL 可驗)、影像 V1–V6(合成源閉環 + aiortc 媒體面實證)、穩健 R1–R9(壓測/混沌/E2E/fuzz/hypothesis)、GCS G1–G8(dialect 消費鏈 + 地圖規劃);SITL→agent→MQTT→DB→console 全鏈路通;5 支 nightly 觀測期 |
| 6 | 2026-07-17 | §7.1 觀測期六支各手動跑一次確認全綠:load-smoke 揭露並修 mission-svc 派遣並發 500(#167→#168,固定 MQTT client-id 互踢)、api-fuzz 連三修穩定綠(#169 timeout/#170 --no-shrink/#171 examples 300→120,6 分鐘綠)、sitl f11 環境 flake 重跑即綠 |
| 7 | 2026-07-17 | 分流並修 api-fuzz 揭露的 5 個 schemathesis 500 findings(#173,轉 422):surrogate 文字(serial/org_id/name)+ int4 溢位配額(max_devices/max_fleets);根因含 RequestValidationError 回顯 surrogate 使 422 回應本身炸 500,以 ensure_ascii 序列化根治;fleet_svc 186 tests 全綠 + openapi 重生 |
