# drone-platform Helm chart(私有部署交付物)

把 [compose 最小棧](../compose/docker-compose.yml)轉為 Kubernetes 部署,作為客戶
**私有部署**交付物(自建機房、資料不出機房)——對 [cloud-fleet.md §3](../../../docs/20-software/cloud-fleet.md)
「多租戶與私有部署」。

## 元件

| 元件 | 類型 | 說明 |
|------|------|------|
| timescaledb | StatefulSet + PVC | 遙測時序 + fleet/mission 關聯(同實例) |
| mosquitto | Deployment | MQTT broker(Phase 0/1 anonymous;C2 上 mTLS+ACL) |
| ingest | Deployment | 遙測 → TimescaleDB |
| fleetsvc | Deployment + Service | 機隊/裝置/韌體 + 在線狀態 + SSE(JWT/RBAC) |
| missionsvc | Deployment + Service | 航線/任務派遣 + 進度(JWT/RBAC) |
| logsvc | StatefulSet + PVC | ULog 上傳/解析 |
| grafana | Deployment(可選) | 遙測看板 |
| webconsole | Deployment + Service + Ingress | Web 指揮中心(nginx 反代 /api → svc) |

## 安裝

```bash
helm install drone ./cloud/deploy/helm/drone-platform \
  --namespace drone --create-namespace \
  --set secrets.pgPassword='<強密碼>' \
  --set secrets.grafanaAdminPassword='<強密碼>' \
  --set secrets.jwtSecret='<32+ bytes>'          # 或 secrets.jwtJwksUrl 走 OIDC
# 對外:--set ingress.enabled=true --set ingress.host=drone.客戶網域
```

## 正式部署必做

1. **覆寫 secrets**(pgPassword/grafanaAdminPassword;jwtSecret 或 jwtJwksUrl),或用
   `secrets.existingSecret` 指向預建 Secret(勿把明文密鑰入 values 版控)。
2. **釘映像 digest**:`image.tag` 建議設 `@sha256:...`(供應鏈可追溯,對 D2 SBOM)。
3. **關 Grafana 匿名**:`grafana.anonymous=false`(預設已關)。
4. **私有 registry**:`image.registry` 指向客戶內部倉庫 + `imagePullSecrets`。

## mTLS 安全部署(C2)

啟用機-雲 mTLS(broker 8883 雙向 TLS + per-device ACL + CRL,服務以 backend 憑證連線):

```bash
# 1) 用 cloud/pki 簽發憑證(server=<release>-drone-platform-mosquitto / backend / 各裝置),
#    建成 k8s Secret(需含 ca.cert.pem/server.cert.pem/server.key.pem/ca.crl.pem/
#    backend.cert.pem/backend.key.pem):
kubectl -n drone create secret generic drone-mqtt-certs --from-file=ca.cert.pem=... [...]
# 2) 啟用:
helm upgrade drone ... --set mtls.enabled=true --set mtls.certSecret=drone-mqtt-certs
```
啟用後 mosquitto 走 8883 mTLS(內嵌 acl per-device 隔離 + crlfile),fleetsvc/missionsvc/
ingest 自動帶 `MQTT_TLS_*` 以 backend 憑證連線。server 憑證 SAN 需含服務名
`<release>-drone-platform-mosquitto`。對 [cloud/deploy/mqtt-tls](../mqtt-tls/README.md) 的 k8s 版。

## 金流 / 配額 / 監控

### 訂閱金流(綠界 ECPay)

fleetsvc 內嵌訂閱結帳(`fleet_svc/billing.py`)。**`ecpay.*` 全空 = 沙箱模式**(用綠界公開
測試商店,不收真錢、不影響 cloud-smoke)。走正式收款:

```bash
helm upgrade drone ./cloud/deploy/helm/drone-platform --reuse-values \
  --set ecpay.merchantId='<商店代號>' \
  --set ecpay.hashKey='<HashKey>' --set ecpay.hashIV='<HashIV>' \
  --set ecpay.returnUrl='https://drone.客戶網域/api/billing/callback'   # 需外部可達
```

- **憑證**(`merchantId`/`hashKey`/`hashIV`)敏感,寫入 chart Secret(`ECPAY_MERCHANT_ID`/
  `ECPAY_HASH_KEY`/`ECPAY_HASH_IV`),fleetsvc 以 `envFrom` 注入。用 `secrets.existingSecret`
  時,請在該預建 Secret 一併放這三個鍵(缺鍵則退回沙箱)。
- **非敏感**(`returnUrl`/`clientBackUrl`/`stage`/`pricePro`/`priceEnterprise`)由 values 直接
  帶入 fleetsvc env。`returnUrl` 是綠界 server 回調 `/billing/callback` 的公開 URL,**務必外部
  可達**(綠界要能 POST 進來),通常即 `ingress.host` + `/api/billing/callback`。
- `stage=true` 可在持有正式憑證時仍打綠界測試環境驗證。

### 配額 / 限流

`quota.*` 對應 `fleet_svc/limits.py`:`maxDevices`/`maxFleets` 為每租戶現存資源上限
(超限回 **402**),`rateLimitPerMin` 為寫入端點每分鐘速率上限(超限回 **429**)。**留空 = 程式
寬鬆預設**(10000/1000/6000;dev 不觸發),依方案/規模覆寫:

```bash
helm upgrade drone ... --set quota.maxDevices=500 --set quota.maxFleets=50 --set quota.rateLimitPerMin=600
```

### 監控閉環(Prometheus)

各服務內建 `/metrics`(fleetsvc:8091、missionsvc:8092、logsvc:8090、ingest:9090)。
`prometheus.enabled`(**預設 true**)部署一個 Prometheus(Deployment + Service + ConfigMap),
抓取上述目標並載入告警規則(chart `files/prometheus/alert-rules.yaml`,與
[observability/alert-rules.yaml](../observability/alert-rules.yaml) 同源)。scrape 走同 namespace
服務 DNS;ingest 無 HTTP Service,故 chart 另建 `<release>-…-ingest-metrics:9090` Service 供抓取。
Grafana 亦自動掛一個 Prometheus datasource(`prometheus.enabled=true` 時)。

```bash
# 看板/查詢(port-forward Prometheus UI)
kubectl -n drone port-forward svc/<release>-drone-platform-prometheus 9090:9090
# Status → Targets 應四個 job 皆 UP;Alerts 見載入的規則
```

TSDB 用 `emptyDir`(重啟不留存);要長期保存改掛 PVC。已有中央 Prometheus 的客戶可設
`prometheus.enabled=false`,改用 `observability/alert-rules.yaml` 接自己的抓取。

## 生產運維(P1)

以下四項皆有 values 旗標,預設值選「安全且無特殊 CNI 也能 `helm install` 成功」。

### 備份/還原(TimescaleDB)

`backup.enabled`(預設 true)產生一個 CronJob,依 `backup.schedule`(預設每日 03:00)以
`pg_dump -Fc`(自訂格式、含壓縮、支援選擇性還原)備份到本地 **backup PVC**
(`backup.storage`,預設 10Gi),並清除超過 `backup.retentionDays`(預設 7)天的舊檔。

```bash
# 手動立即備份(從 CronJob 觸發一次性 Job)
kubectl -n drone create job --from=cronjob/<release>-drone-platform-backup manual-backup-1
# 列出備份檔
kubectl -n drone exec deploy/<release>-drone-platform-... -- ls -lh /backup   # 或掛 PVC 檢視
```

**還原**(把某個 dump 灌回 timescaledb):

```bash
# 1) 進 timescaledb Pod 或另起一個掛 backup PVC + 連 DB 的臨時 Pod
kubectl -n drone exec -it sts/<release>-drone-platform-timescaledb -- bash
# 2) 用 pg_restore(-c 先清既有物件;--if-exists 避免不存在時報錯)
PGPASSWORD=<pgPassword> pg_restore -h localhost -U drone -d drone \
  --clean --if-exists /backup/drone-YYYYmmdd-HHMMSS.dump
```

**異地/物件儲存(S3)**:屬部署決策,本 chart 只做本地 PVC 版。設 `backup.s3.enabled=true`
+ `backup.s3.bucket=s3://.../timescaledb`,CronJob 會在 dump 後 `aws s3 cp` 外送——但需自備
**含 aws CLI 的映像**(覆寫 `timescaledb.image` 或改用 sidecar)與憑證(env 或 IRSA/Workload
Identity)。預設關,避免預設映像無 aws 而失敗。

### 資料庫 migration(pre-upgrade hook)

`migration.useHook`(預設 true)把 fleet/mission 的 SQL migration 改由 **Helm hook Job**
(`python -m fleet_svc.migrate` / `python -m mission_svc.migrate`)先跑完再滾動更新 app,
消除多副本 app 同時啟動自跑 migration 的競態。app 啟動仍會冪等自跑作 fallback
(`schema_migrations` 去重),故 `useHook=false` 退回純 app 自跑亦可運作。

hook 時機由 `migration.hooks` 控制,**預設僅 `pre-upgrade`**:本 chart 內建 timescaledb,
`pre-install` 階段 DB 尚未建立會使 hook 卡死,故「首次安裝」的 migration 交給 app 自跑
(replicas 預設 1、無競態);若改接**外部既有 DB**,可加 `pre-install` 讓安裝也走 hook。

### NetworkPolicy 網段隔離

`networkPolicy.enabled`(**預設 false**,因需 CNI 支援如 Calico/Cilium)產生預設 deny-all
ingress + 逐服務放行:webconsole→fleet/mission,服務→timescaledb/mosquitto,
Ingress 控制器/port-forward→webconsole:80。policyTypes 僅 Ingress(不限 egress,DNS 不受影響)。
外部裝置(drone→mosquitto)與外部 ULog 上傳走叢集外來源,需另加 `from ipBlock/namespaceSelector`
規則。可設 `networkPolicy.ingressControllerNamespace` 把 webconsole 入口收斂為僅該 namespace。

### PodDisruptionBudget

`pdb.enabled`(預設 true)為 **replicas>1** 的服務(fleet/mission/ingest/log/webconsole)產生
PDB(`minAvailable`,預設 1),節點排空/叢集升級時保最小可用數。單副本服務不產生 PDB
(minAvailable:1 會擋住唯一 Pod 的自願驅逐),故預設(各服務 replicas=1)不影響節點排空。

## 現況與後續

- 映像須先由各服務 Dockerfile 建置並推入 `image.registry`(CI 發佈流程屬 release wave)。
- ✅ mediamtx(影像串流:RTSP+WebRTC/WHEP+錄存;auth internal|http;選配 simcam)。待補:SBOM 附掛(D2)。
  (Grafana datasource/dashboard provisioning、Prometheus 抓取 + 告警規則已內建,見上「監控閉環」。)

## 驗證

```bash
helm lint ./cloud/deploy/helm/drone-platform
helm template drone ./cloud/deploy/helm/drone-platform | kubectl apply --dry-run=client -f -
```
