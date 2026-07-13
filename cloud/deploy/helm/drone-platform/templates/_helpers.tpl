{{- define "drone.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "drone.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "drone.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "drone.labels" -}}
app.kubernetes.io/name: {{ include "drone.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* 密鑰 Secret 名稱:用既有或本 chart 建立 */}}
{{- define "drone.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "drone.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* 服務映像:registry/<name>:tag(tag 可為 @sha256 digest) */}}
{{- define "drone.image" -}}
{{- $svc := index . 1 -}}
{{- $root := index . 0 -}}
{{- printf "%s/%s:%s" $root.Values.image.registry $svc $root.Values.image.tag -}}
{{- end -}}

{{/* fleet/mission/ingest/log 服務共用的 PG_DSN 環境 */}}
{{- define "drone.pgDsn" -}}
postgresql://drone:$(PG_PASSWORD)@{{ include "drone.fullname" . }}-timescaledb:5432/drone
{{- end -}}

{{/* MQTT 埠:mTLS 走 8883,否則 1883 */}}
{{- define "drone.mqttPort" -}}
{{- if .Values.mtls.enabled -}}8883{{- else -}}1883{{- end -}}
{{- end -}}

{{/* mTLS client env(服務以 backend 憑證連線;mtls 停用時為空) */}}
{{- define "drone.mqttTlsEnv" -}}
{{- if .Values.mtls.enabled }}
- name: MQTT_TLS_CA
  value: /mqtt-certs/ca.cert.pem
- name: MQTT_TLS_CERT
  value: /mqtt-certs/backend.cert.pem
- name: MQTT_TLS_KEY
  value: /mqtt-certs/backend.key.pem
{{- end }}
{{- end -}}

{{/* mTLS 憑證 volume(掛 certSecret) */}}
{{- define "drone.mqttCertVolume" -}}
{{- if .Values.mtls.enabled }}
- name: mqtt-certs
  secret:
    secretName: {{ .Values.mtls.certSecret }}
{{- end }}
{{- end -}}

{{/* mTLS 憑證 volumeMount */}}
{{- define "drone.mqttCertMount" -}}
{{- if .Values.mtls.enabled }}
- name: mqtt-certs
  mountPath: /mqtt-certs
  readOnly: true
{{- end }}
{{- end -}}

{{/* Pod-level securityContext(自研 Python 服務:以非 root uid 1000 執行)。
     映像未內建 USER,故靠此強制降權;fsGroup 讓掛載卷(log_svc PVC/憑證)可讀寫。 */}}
{{- define "drone.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Container-level securityContext(自研服務:完整加固)。
     readOnlyRootFilesystem 由 values.security.readOnlyRootFilesystem 控制(預設 false);
     若要開啟需為 /tmp 等可寫路徑另掛 emptyDir,否則 uvicorn/python 會因無法寫入而失敗。 */}}
{{- define "drone.containerSecurityContext" -}}
allowPrivilegeEscalation: false
runAsNonRoot: true
capabilities:
  drop:
    - ALL
readOnlyRootFilesystem: {{ .Values.security.readOnlyRootFilesystem }}
{{- end -}}

{{/* Container-level securityContext(第三方映像:保守處理)。
     只關特權升級 + 丟棄所有 Linux capabilities,不強制 runAsNonRoot/uid——
     grafana(472)/postgres(999)/mosquitto(1883)各有自訂 uid,強制 1000 會壞掉;
     待各映像改為 unprivileged 再收斂(TODO)。webconsole nginx 另需 NET_BIND_SERVICE,
     故不使用本 helper 而於其 template 內就地宣告。 */}}
{{- define "drone.thirdPartyContainerSecurityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop:
    - ALL
{{- end -}}
