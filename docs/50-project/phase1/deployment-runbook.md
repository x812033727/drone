# 50-5 端到端部署 Runbook(compose 單機 / Helm k8s)

> rev 1 · 2026-07。把 [cloud/deploy](../../../cloud/deploy/) 的**現有實作**整理成可照做的部署手冊,
> 涵蓋兩條路徑:**(1) compose 單機**(開發/小型自建)、**(2) Helm/k8s**(客戶私有部署交付物)。
> 上位路線與退出條件以 [commercialization-roadmap.md](commercialization-roadmap.md) 為準。
>
> **以現有實作為準**:所有指令/env/values 皆對應倉庫內既有檔案;凡尚未落地者一律明標「⏳ 待補」,
> 不杜撰。安全設計背景見 [security.md](../../20-software/security.md)。

## 0. 系統組成一覽

| 元件 | compose 服務 | 容器內埠 | 對外面 | 健康檢查 |
|------|--------------|----------|--------|----------|
| MQTT broker | `mosquitto` | 1883(C2 上 8883 mTLS) | 機隊上行遙測入口 | `mosquitto_sub $SYS/broker/uptime` |
| 時序 + 關聯庫 | `timescaledb` | 5432 | 綁 loopback | `pg_isready` |
| 遙測落庫 | `ingest` | — | 內部 | — |
| 機隊/裝置/韌體 + SSE | `fleetsvc` | 8091 | 綁 loopback | `GET /healthz`(含 `SELECT 1`) |
| 航線/任務派遣 + 進度 | `missionsvc` | 8092 | 綁 loopback | `GET /healthz` |
| ULog 上傳/解析 | `logsvc` | 8090 | 綁 loopback | `GET /healthz` |
| 遙測看板 | `grafana` | 3000 | 依部署 | 未設(手動開頁) |
| 影像錄存/回放 | `mediamtx` | RTSP 8554 / playback 9996 / api 9997 | RTSP 對外、playback+api 綁 loopback | 官方 image 無 shell,由 host 輪詢 api |
| Web 指揮中心 | `webconsole` | 80 | 對外(nginx 反代 `/api`) | 依 fleetsvc healthy |

服務原始碼在 `cloud/<svc>/`;compose 定義在 [cloud/deploy/compose/docker-compose.yml](../../../cloud/deploy/compose/docker-compose.yml)。

---

## 路徑一:compose 單機部署

適用:開發機、單機 demo、小型自建。以 [Makefile](../../../Makefile) 的 `make dev` 為一鍵入口
(**隔離高位埠 + 獨特 project 名**,同機可與其他服務並存;此為專案鐵則)。

### 1.1 前置需求

- Docker Engine + Docker Compose(plugin `docker compose` 或 standalone `docker-compose` 皆可;
  Makefile 預設 `docker-compose`,他環境可 `make COMPOSE="docker compose" dev`)。
- Python 3.10+(僅驗證步驟灌假遙測用;`make install` 建 venv)。
- 對外要收機上真流時開放 RTSP 8554;其餘管理埠只綁 loopback。

### 1.2 關鍵設定(環境變數,皆有 dev 預設,正式務必覆寫)

| 環境變數 | dev 預設 | 說明 |
|----------|----------|------|
| `PG_PASSWORD` | `dronedev` | TimescaleDB 密碼(ingest/fleet/mission/grafana 連線共用) |
| `GRAFANA_ANONYMOUS` | `true`(dev) | 匿名唯讀看板;**正式設 `false`** |
| `GRAFANA_ADMIN_PASSWORD` | `dronedev` | Grafana admin 密碼 |
| `JWT_SECRET` / `JWT_JWKS_URL` | 空 | fleet/mission API 認證。**空 = 停用(dev 全放行)**;正式設 HS256 密鑰或 OIDC JWKS URL。另有 `JWT_AUDIENCE` / `JWT_ISSUER` |
| `VIDEO_PUBLISH_USER` / `VIDEO_PUBLISH_PASS` | `publisher` / `dronedev-publish` | **MediaMTX 推流帳密**(RTSP publish);關匿名後推流必帶 |
| `VIDEO_READ_USER` / `VIDEO_READ_PASS` | `reader` / `dronedev-read` | MediaMTX 拉流帳密(RTSP read) |
| `ECPAY_MERCHANT_ID` / `ECPAY_HASH_KEY` / `ECPAY_HASH_IV` | 空 | **綠界金流憑證**。**全空 = 沙箱模式**(用綠界公開測試商店,不收真錢、不影響 cloud-smoke);三者齊備才走正式收款 |
| `ECPAY_RETURN_URL` | 空 | 綠界 server 回調本服務 `/billing/callback` 的公開 URL。**正式收款必填且需外部可達**(綠界要能 POST 到此,localhost 無效) |
| `ECPAY_CLIENT_BACK_URL` / `ECPAY_STAGE` / `ECPAY_PRICE_PRO` / `ECPAY_PRICE_ENTERPRISE` | 空 | 付款後前端返回 URL(選)/`true` 強制打綠界測試環境 / 各方案月費 TWD 覆寫(空=pro 3000、enterprise 30000) |
| `QUOTA_MAX_DEVICES` / `QUOTA_MAX_FLEETS` | 空(=10000 / 1000) | 每租戶現存資源上限;超限回 **402**。空=程式寬鬆預設(dev/cloud-smoke 不觸發) |
| `RATE_LIMIT_PER_MIN` | 空(=6000) | 每租戶寫入端點每分鐘速率上限;超限回 **429 + Retry-After** |
| 埠覆寫 | 見下 | `MQTT_PORT` `PG_PORT` `GRAFANA_PORT` `RTSP_PORT` `PLAYBACK_PORT` `MTX_API_PORT` `LOGSVC_PORT` `FLEETSVC_PORT` `MISSIONSVC_PORT` `WEBCONSOLE_PORT` `PROM_PORT`(監控,見 §1.7) |

`make dev` 用的隔離埠:MQTT `31883` · PG `35432` · Grafana `33100` · RTSP `38554` ·
playback `39996` · mtx-api `39997` · logsvc `38090`(project 名 `drone-dev`)。

> **影像認證**:`cloud/deploy/compose/mediamtx/mediamtx.yml` 的 `authInternalUsers` 留空以
> **關閉匿名**,實際使用者由 docker-compose.yml 的 `mediamtx.environment` 以
> `MTX_AUTHINTERNALUSERS_*` 注入(0=publish、1=read、2=any 僅 api、3=any 僅 playback;
> api/playback 宿主埠只綁 loopback)。MediaMTX v1.12.3 不支援設定檔內 `${ENV}` 內插,
> 故走此 `MTX_` 覆寫路徑。詳見 [onboard/video_pipeline/README.md](../../../onboard/video_pipeline/README.md)。

### 1.3 部署步驟

```bash
# 一鍵(隔離高位埠;結束用 make dev-down / 追日誌 make dev-logs)
make dev

# 或直接在 compose 目錄(正式部署先 export 上表 env)
cd cloud/deploy/compose
PG_PASSWORD='<強密碼>' GRAFANA_ANONYMOUS=false GRAFANA_ADMIN_PASSWORD='<強密碼>' \
  JWT_SECRET='<32+ bytes>' VIDEO_PUBLISH_PASS='<強密碼>' VIDEO_READ_PASS='<強密碼>' \
  docker compose up -d --build --wait --wait-timeout 180
```

**Migration 自跑**:TimescaleDB 首次啟動由 `timescale/init.sql`
(掛 `docker-entrypoint-initdb.d`)建表;`fleetsvc`/`missionsvc` 啟動時前向套用各自
`migrations/*.sql`(見 `apply_migrations`)。無需手動跑 migration。

### 1.4 驗證

```bash
# a) 健康檢查(服務綁 loopback)
curl -fsS http://127.0.0.1:${FLEETSVC_PORT:-8091}/healthz
curl -fsS http://127.0.0.1:${MISSIONSVC_PORT:-8092}/healthz
curl -fsS http://127.0.0.1:${LOGSVC_PORT:-8090}/healthz

# b) 灌假遙測 → 斷言落庫(對應 cloud-smoke CI)
python tools/publish_fake_telemetry.py --mqtt-port ${MQTT_PORT:-1883} \
  --drone-id demo-1 --rate 5 --count 10 --with-sensors --with-mission-events --with-heartbeat
docker compose exec -T timescaledb \
  psql -U drone -d drone -tAc "SELECT count(*) FROM telemetry WHERE drone_id='demo-1'"   # 應 ≥ 1

# c) 看板:開 http://localhost:${GRAFANA_PORT:-3000} 看 fleet 看板
#    (compose 已內建 provisioning:timescaledb datasource + fleet 儀表板,開箱即用)

# d) 影像錄存回放端到端(推流→/list→/get→ffprobe)
cd cloud/deploy/compose && RTSP_PORT=38554 PLAYBACK_PORT=39996 MTX_API_PORT=39997 \
  COMPOSE_PROJECT=vsmoke-$$ ./video_smoke.sh
```

### 1.5 mTLS 安全部署(C2,可選 overlay)

機-雲全程 mTLS 用 overlay [docker-compose.mtls.yml](../../../cloud/deploy/compose/docker-compose.mtls.yml)
疊加(獨立 `mosquitto-mtls:8883` + per-device ACL + CRL,ingest 帶 backend 憑證連線):

```bash
# 憑證由 cloud/pki 簽發(含 ca/server/backend/*.cert.pem + ca.crl.pem)
MTLS_CERTS_DIR=/path/to/certs \
  docker-compose -f docker-compose.yml -f docker-compose.mtls.yml up -d --build \
    mosquitto-mtls timescaledb ingest
./verify_stack_mtls.sh   # 驗雙向 TLS + ACL 隔離
```

### 1.6 升級 / 回滾

```bash
git pull && cd cloud/deploy/compose
docker compose up -d --build --wait          # 滾動重建(migration 啟動自跑;image tag 已釘 1.12.3 等)
docker compose logs --tail 200               # 觀察
# 回滾:checkout 前一版 tag 後重跑 up;資料在具名 volume(timescale-data/ulog-archive/
#       mediamtx-recordings/prometheus-data)不隨 up 清除,down 勿加 -v
```

### 1.7 監控閉環(Prometheus,可選 profile)

各服務已內建 `/metrics`(fleetsvc:8091、missionsvc:8092、logsvc:8090、ingest:9090)。
compose 附一個 `prometheus` 服務抓取它們並載入
[alert-rules.yaml](../../../cloud/deploy/observability/alert-rules.yaml)。以 profile
`monitoring` **隔離**:預設 `docker compose up`(含 cloud-smoke)**不起** Prometheus,故不影響
煙霧;要監控才顯式加 profile:

```bash
cd cloud/deploy/compose
docker compose --profile monitoring up -d            # 連同 prometheus 一起起
# Prometheus UI(只綁 loopback,正式對外請走反代 + 認證):
open http://127.0.0.1:${PROM_PORT:-9464}          # Status → Targets 應四個 job 皆 UP
```

scrape 設定 [prometheus/prometheus.yml](../../../cloud/deploy/compose/prometheus/prometheus.yml)
(job 名對齊 alert-rules.yaml 的 `fleetsvc|missionsvc|logsvc|ingest`);規則檔直接掛
observability 單一來源,免複製。Grafana 亦可加 Prometheus datasource 查這些指標。

### 1.8 OTA 軟體更新(機載 agent 設定)

雲端派發軟體套件 OTA(G23)於**機載 drone-agent** 端啟用,設定見
[onboard/deploy/systemd/drone-agent.env.example](../../../onboard/deploy/systemd/drone-agent.env.example):
`EXTRA_ARGS` 加 `--enable-ota` 訂閱 `fleet/{drone_id}/cmd/ota`,並**務必**設 `OTA_PUBLIC_KEY`
指向 Ed25519 **公鑰** PEM 檔路徑(未設 = fail-closed 拒絕所有安裝)。私鑰只在雲端簽章側,絕不佈到機上。

---

## 路徑二:Helm / Kubernetes(私有部署交付物)

把 compose 最小棧轉為 k8s 部署,作為客戶**私有部署**交付(資料不出機房)。
Chart 在 [cloud/deploy/helm/drone-platform](../../../cloud/deploy/helm/drone-platform/);
權威說明見 [cloud/deploy/helm/README.md](../../../cloud/deploy/helm/README.md)。

### 2.1 前置需求

1. **映像 registry**:各服務由自身 `cloud/<svc>/Dockerfile`(及 `gcs/web-console/Dockerfile`)
   建置並推入 `image.registry`(預設 `ghcr.io/x812033727/drone`)。
   ⏳ **待補(G1)**:CI 自動發佈映像流程尚未上線;目前需手動 build+push,或指向已有 registry。
2. **Secrets 覆寫**:`pgPassword` / `grafanaAdminPassword`、`jwtSecret` 或 `jwtJwksUrl`
   (勿把明文入 values 版控;可用 `secrets.existingSecret` 指向預建 Secret)。
3. **mTLS 憑證**(啟用 C2 時):由 `cloud/pki` 簽發後 `kubectl create secret` 建成 `certSecret`。
4. **Ingress + TLS**:對外時需 IngressController + TLS Secret(見 §2.5)。
5. 叢集能拉私有映像 → `imagePullSecrets`。

### 2.2 關鍵設定(values,見 [values.yaml](../../../cloud/deploy/helm/drone-platform/values.yaml))

| values key | 預設 | 正式部署 |
|------------|------|----------|
| `image.registry` / `image.tag` | `ghcr.io/x812033727/drone` / `0.1.0` | 指客戶私有倉庫;**tag 建議釘 `@sha256:...`**(供應鏈可追溯,對 D2 SBOM) |
| `imagePullSecrets` | `[]` | 私有 registry 拉取憑證 |
| `secrets.pgPassword` / `secrets.grafanaAdminPassword` | `change-me-*` | **務必覆寫**或用 `secrets.existingSecret` |
| `secrets.jwtSecret` / `secrets.jwtJwksUrl` | 空 | 設其一啟用 API 認證(HS256 或 OIDC/RS256);空 = dev 全放行(NOTES.txt 會告警) |
| `mtls.enabled` / `mtls.certSecret` | `false` / 空 | 啟用機-雲 mTLS(broker 走 8883 + per-device ACL + CRL,服務帶 backend 憑證) |
| `ecpay.merchantId` / `ecpay.hashKey` / `ecpay.hashIV` | 空 | **綠界金流憑證**(敏感;寫入 Secret,`existingSecret` 模式改由該 Secret 提供 `ECPAY_*` 三鍵)。**全空 = 沙箱**;齊備才走正式收款 |
| `ecpay.returnUrl` / `ecpay.clientBackUrl` / `ecpay.stage` / `ecpay.pricePro` / `ecpay.priceEnterprise` | 空 | 非敏感,由 values 注入 fleetsvc env。`returnUrl` 為綠界回調 `/billing/callback` 的公開 URL,**需外部可達** |
| `quota.maxDevices` / `quota.maxFleets` / `quota.rateLimitPerMin` | 空(=10000/1000/6000) | 每租戶配額(超限 402)與寫入限流(超限 429);空=程式寬鬆預設 |
| `prometheus.enabled` | `true` | 內建 Prometheus 抓各服務 `/metrics` + 載入 alert-rules。已有中央 Prometheus 可設 `false` |
| `grafana.anonymous` | `false` | 私有部署預設關匿名(對比 dev compose) |
| `ingress.enabled` / `ingress.host` / `ingress.tls` | `false` / `drone.example.com` / `[]` | 對外 Web 指揮中心 + TLS |
| 各服務 `replicas` / `resources` / `storage` | 見 values | 依規模調整;timescaledb/logsvc 為 StatefulSet+PVC |

### 2.3 部署步驟

```bash
# 驗證(不套用)
helm lint ./cloud/deploy/helm/drone-platform
helm template drone ./cloud/deploy/helm/drone-platform | kubectl apply --dry-run=client -f -

# 安裝
helm install drone ./cloud/deploy/helm/drone-platform \
  --namespace drone --create-namespace \
  --set secrets.pgPassword='<強密碼>' \
  --set secrets.grafanaAdminPassword='<強密碼>' \
  --set secrets.jwtSecret='<32+ bytes>'          # 或 secrets.jwtJwksUrl 走 OIDC

# 對外 + TLS
helm upgrade drone ./cloud/deploy/helm/drone-platform --reuse-values \
  --set ingress.enabled=true --set ingress.host=drone.客戶網域 \
  --set-json 'ingress.tls=[{"secretName":"drone-tls","hosts":["drone.客戶網域"]}]'
```

**Migration 自跑**:服務 Pod 啟動時 `fleetsvc`/`missionsvc` 前向套用 `migrations/*.sql`;
timescaledb 首次以 init 建表。無獨立 migration job。

### 2.4 驗證

```bash
kubectl -n drone get pods                       # 全 Running/Ready
kubectl -n drone rollout status deploy/drone-drone-platform-fleetsvc
# 無 Ingress 時 port-forward(NOTES.txt 亦會提示)
kubectl -n drone port-forward svc/drone-drone-platform-webconsole 8080:80
# 開 http://localhost:8080 → 指揮中心;fleetsvc/missionsvc 的 /healthz 應 200
```
安裝後 `helm` 會印 NOTES.txt:若未設 `jwtSecret`/`jwtJwksUrl` 會**警告 API 認證停用**。

### 2.5 升級 / 回滾

```bash
helm upgrade drone ./cloud/deploy/helm/drone-platform --reuse-values --set image.tag='<新版>'
helm history drone
helm rollback drone <REVISION>          # PVC 資料保留;回滾只換工作負載版本
```

## 2.x 故障演練(chaos drill)

`cloud/deploy/compose/chaos_drill.sh`:對隔離棧注入三種基礎設施故障並斷言自癒
(DB 重啟 → asyncpg pool 自癒不重啟服務;DB 長停 → DLQ JSONL 落地、恢復後續落庫;
MQTT 重啟 → 重連恢復、斷線期間 dispatch 有限時回應)。CI 為 nightly
`chaos-drill.yml`(觀測期,失敗自動開 issue)。實測恢復數字見
[perf-baseline.md §3.4](perf-baseline.md)。

負載/容量基準(REST 延遲、遙測 fan-in 落庫率、SSE 訂閱者容量)見
[perf-baseline.md](perf-baseline.md);⚠️ 該表數字為共用開發機實測,僅供迴歸
對照——正式容量規劃須在專屬硬體以同一方法論(loadgen)重跑。
⚠️ 已知語意:ingest 的 db-ready 旗標在「下一次成功寫入」才翻回——DB 恢復後
/healthz 仍 503 屬正常,發一筆遙測即恢復;僅覆蓋單機 compose,不含 k8s 多副本。

---

## 3. 常見問題(FAQ)

- **RTSP 推流 401 / ANNOUNCE failed**:關匿名後推流未帶帳密。用
  `rtsp://<VIDEO_PUBLISH_USER>:<VIDEO_PUBLISH_PASS>@host:8554/drone/<serial>`
  (串流命名 `drone/<serial>`,serial = fleet 裝置序號);帳密與部署時注入的一致。
- **WHEP/WebRTC 看不到畫面(信令 201 但無媒體)**:ICE candidate 通告容器內 UDP 埠,
  `WEBRTC_UDP_PORT` 的宿主映射必須同號(compose 已自動同號);跨機觀看要以
  `MTX_WEBRTCADDITIONALHOSTS` 通告宿主對外 IP。
- **回放 `/list` / `/get` 打不通**:playback(9996)與 api(9997)只綁 loopback(內網豁免);
  對外請走 Web 指揮中心或另加反代 + 認證,勿直接外露這兩埠。
- **fleet/mission API 回 401/403**:設了 `JWT_SECRET`/`JWT_JWKS_URL` 即啟用 RBAC(viewer 讀 / operator 改);
  帶合法 JWT。dev 想全放行則清空該 env。
- **埠衝突**:同機多棧務必用埠覆寫 env + 獨特 compose project 名(`make dev` 已內建)。
- **`--wait` 卡在 mediamtx**:官方 image 無 healthcheck,`--wait` 只等 running;
  就緒改由 host 輪詢 api(`/v3/paths/list`),見 `video_smoke.sh`。
- **Grafana 看板空白**:compose 已 provisioning(datasource + fleet 儀表板),空白多半是
  遙測未落庫(先跑 §1.4b 灌假遙測);**Helm 端**的 datasource/dashboard provisioning 尚待補(見下 G2)。
- **資料被清空**:`docker compose down -v` 會刪具名 volume(含錄影/遙測)。日常停棧用不帶 `-v` 的 `down`。

---

## 4. 待補(誠實邊界)

| 項目 | 狀態 | 追蹤 |
|------|------|------|
| 映像 registry 發佈(CI build+push) | ⏳ 未上線,需手動 build/push | **G1** |
| Grafana datasource / dashboard provisioning | compose ✅ 已內建;**Helm** 端 ConfigMap ⏳ 待補 | **G2** |
| Helm 內 mediamtx(影像錄存) | ⏳ chart 尚無 mediamtx 元件(compose 已有) | helm README「待補」 |
| NetworkPolicy 網段隔離 / SBOM 附掛 | ⏳ | 見 helm README |
