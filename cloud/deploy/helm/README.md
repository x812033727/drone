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

## 現況與後續

- 映像須先由各服務 Dockerfile 建置並推入 `image.registry`(CI 發佈流程屬 release wave)。
- 待補:mediamtx(影像錄存)、Grafana dashboard/datasource provisioning(ConfigMap)、
  NetworkPolicy 網段隔離、mTLS(C2)、SBOM 附掛(D2)。

## 驗證

```bash
helm lint ./cloud/deploy/helm/drone-platform
helm template drone ./cloud/deploy/helm/drone-platform | kubectl apply --dry-run=client -f -
```
