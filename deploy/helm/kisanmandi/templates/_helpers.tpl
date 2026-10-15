{{/* Common template helpers. Keeping names consistent here is what makes
     `helm list` and `kubectl get all` readable later. */}}

{{- define "kisanmandi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "kisanmandi.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "kisanmandi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels applied to every object. These are what let you write
     `kubectl get all -l app.kubernetes.io/instance=kisanmandi`. */}}
{{- define "kisanmandi.labels" -}}
helm.sh/chart: {{ include "kisanmandi.chart" . }}
{{ include "kisanmandi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "kisanmandi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kisanmandi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Non-secret environment. Secrets are injected separately so they never
     appear in `kubectl describe deployment` output. */}}
{{- define "kisanmandi.commonEnv" -}}
- name: DATA_DIR
  value: {{ .Values.config.dataDir | quote }}
- name: LANDING_BACKEND
  value: {{ .Values.config.landingBackend | quote }}
- name: LANDING_LOCAL_DIR
  value: {{ .Values.config.landingLocalDir | quote }}
- name: PAGE_SIZE
  value: {{ .Values.config.pageSize | quote }}
- name: MAX_PAGES
  value: {{ .Values.config.maxPages | quote }}
- name: MIN_REQUEST_INTERVAL_SECONDS
  value: {{ .Values.config.minRequestIntervalSeconds | quote }}
- name: STALENESS_DAYS
  value: {{ .Values.config.stalenessDays | quote }}
- name: MIN_PLAUSIBLE_PRICE
  value: {{ .Values.config.minPlausiblePrice | quote }}
- name: MAX_PLAUSIBLE_PRICE
  value: {{ .Values.config.maxPlausiblePrice | quote }}
- name: FORECAST_HORIZON_DAYS
  value: {{ .Values.config.forecastHorizonDays | quote }}
- name: HOLD_THRESHOLD_PCT
  value: {{ .Values.config.holdThresholdPct | quote }}
- name: TRANSPORT_COST_PER_QUINTAL
  value: {{ .Values.config.transportCostPerQuintal | quote }}
- name: MIN_HISTORY_POINTS
  value: {{ .Values.config.minHistoryPoints | quote }}
{{- end -}}
