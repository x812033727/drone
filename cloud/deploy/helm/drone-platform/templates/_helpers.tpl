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
