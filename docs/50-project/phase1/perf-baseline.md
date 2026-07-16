# 50-6 效能基準(方法論 + 實測記錄)

> rev 1 · 2026-07。雲端平台的負載基準:**怎麼量、在哪量、量到多少**。
> 工具在 [tools/loadgen/](../../../tools/loadgen/README.md);SLO 口徑見 [slo.md](slo.md)。
> 原則:**數字只填實測值**,未測標「⏳ 待測」——不杜撰。

## 1. 誠實邊界(先讀這個)

- **GitHub Actions 2-core runner 上的絕對延遲/吞吐數字無意義**:受測服務、DB、
  broker、負載產生器全擠同一台共享 VM。CI 上的負載 job 只當**迴歸煙霧**
  (不 crash、零非預期 5xx、記憶體/fd 有界、恢復自動),延遲數字僅存 artifact
  供趨勢對照,**永不設為門檻**。
- 本表的容量數字一律在**專屬機**(下表註明規格)以隔離棧實測。
- HS256 token 路徑 ≠ 生產 JWKS 驗簽路徑(後者已有單元測試;JWKS 供應商異常
  不在本基準範圍)。

## 2. 量測方法

前置:隔離棧 + `JWT_SECRET`(dev 模式=全 admin,壓不到配額/限流/org 路徑):

```bash
cd cloud/deploy/compose && JWT_SECRET=devsecret \
  MQTT_PORT=31883 PG_PORT=35432 FLEETSVC_PORT=38091 MISSIONSVC_PORT=38092 \
  GRAFANA_PORT=33100 RTSP_PORT=38554 PLAYBACK_PORT=39996 MTX_API_PORT=39997 \
  LOGSVC_PORT=38090 WEBCONSOLE_PORT=38080 \
  docker-compose -p loadbase up -d --build --wait   # 結束必 down -v
```

| 場景 | 指令 | 記錄什麼 |
|------|------|----------|
| REST 讀 + 派遣流 | `JWT_SECRET=devsecret FLEET_BASE=http://127.0.0.1:38091 MISSION_BASE=http://127.0.0.1:38092 locust -f tools/loadgen/locustfile.py --headless -u <U> -r 2 -t 120s --csv /tmp/loadgen` | p50/p95/失敗率(csv);402/429 另計為預期 |
| 遙測 fan-in | `python tools/loadgen/mqtt_fanin.py --drones <N> --rate <R> --seconds 120 --port 31883` | 實發 msg/s;落庫率(腳本印出的 psql 查詢) |
| SSE 訂閱量 | (sse_swarm.py,後續 PR) | fd/RSS/訂閱者 gauge 歸零 |

## 3. 基準記錄

> 每列一次實測;環境欄寫機器規格與棧版本(git sha)。

### 3.1 REST(locust)

| 日期 | 環境 | 併發 U | p50 | p95 | 非預期錯誤率 | 402/429 | 備註 |
|------|------|--------|-----|-----|--------------|---------|------|
| ⏳ 待測 | | | | | | | |

### 3.2 遙測 fan-in(mqtt_fanin)

| 日期 | 環境 | drones×rate | 實發 msg/s | 落庫率 | 備註 |
|------|------|-------------|-----------|--------|------|
| ⏳ 待測 | | | | | |

### 3.3 SSE 訂閱量(sse_swarm,後續 PR)

| 日期 | 環境 | 訂閱者數(正常/慢讀/斷線) | fd 峰值 | RSS 峰值 | 斷線後 gauge 歸零 | 備註 |
|------|------|---------------------------|---------|----------|-------------------|------|
| ⏳ 待測 | | | | | | |

## 4. 版本紀錄

| rev | 日期 | 變更 |
|-----|------|------|
| 1 | 2026-07-16 | 初版:方法論 + 記錄表骨架(loadgen 基座 PR) |
