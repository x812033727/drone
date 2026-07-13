# cloud/deploy/mqtt-tls — MQTT mTLS + per-device ACL(C2a)

> 對 [docs/20-software/security.md §2/§3](../../../docs/20-software/security.md):機-雲 mTLS、
> 每機一憑證、主題隔離。建立在 [cloud/pki](../../pki/README.md)(C1)的憑證體系上。

## 內容

- `mosquitto-tls.conf`:保留明文 `1883`(dev/內網向後相容)+ 新增 `8883` **mTLS 監聽器**
  (`require_certificate` + `use_identity_as_username`,cert CN → MQTT username)。
- `acl`:**per-device 主題 ACL**——裝置(username=序號)只能發自己的
  `fleet/<serial>/{telemetry,mission/progress,events,sensors/#}`、只能訂
  `fleet/<serial>/cmd/#`;後端服務帳號(CN=`backend`)可讀寫全機隊 `fleet/#`。
- `verify_mtls.sh` + `mtls_check.py`:端到端自我驗證(起 mosquitto TLS 容器 + PKI 憑證)。

## 驗證

```bash
cloud/deploy/mqtt-tls/verify_mtls.sh   # 需 docker + paho-mqtt(PYTHON=... 可指定直譯器)
```
斷言:①無 client 憑證連線被拒 ②裝置訂/發他機主題被 ACL 隔離(收不到/送不到)
③自己主題正常 + mTLS 端到端 pub/sub 通。

## 端到端安全語義

- **裝置身分**:連線需出示由 Drone Fleet CA 簽發的 client 憑證(CN=機身序號),
  broker 以 CN 為 username;偽造 broker 或無憑證連線一律被拒。
- **機身隔離**:任一裝置無法讀寫其他裝置的主題(ACL pattern `%u`),防冒名派任務/竄改遙測。
- **後端**:ingest / fleet-svc / mission-svc 消費者以 `backend` 憑證連線,讀全機隊 + 下行 cmd。

## 待做(C2b,後續)

- 各連線端(`drone_agent` / `ingest` / fleet-svc / mission-svc 消費者 / dispatch)加
  TLS client 憑證支援(env 驅動:`MQTT_TLS_CA`/`MQTT_TLS_CERT`/`MQTT_TLS_KEY`,預設明文向後相容)。
- broker 載入 CRL(C1 `gen_crl.sh` 產出)即時拒絕吊銷裝置。
- compose/Helm 切換到 mTLS 監聽器(移除明文 `1883`)。
- 動態 ACL(EMQX HTTP hook → fleet-svc)取代靜態 ACL(若需上線即時授權變更)。
