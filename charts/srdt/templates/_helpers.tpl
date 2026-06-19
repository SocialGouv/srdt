{{- define "srdt.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "srdt.fullname" -}}
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

{{- define "srdt.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "srdt.selectorLabels" -}}
app.kubernetes.io/name: {{ include "srdt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "srdt.labels" -}}
helm.sh/chart: {{ include "srdt.chart" . }}
{{ include "srdt.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.global.extraLabels }}
{{ toYaml . | trim }}
{{- end }}
{{- end -}}

{{- define "srdt.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "srdt.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Références d'image complètes : <global.imageRegistry>/<repository>:<tag|appVersion> */}}
{{- define "srdt.apiImage" -}}
{{- $reg := .Values.global.imageRegistry | trimSuffix "/" -}}
{{- $tag := .Values.api.image.tag | default .Chart.AppVersion -}}
{{- if $reg -}}
{{- printf "%s/%s:%s" $reg .Values.api.image.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.api.image.repository $tag -}}
{{- end -}}
{{- end -}}

{{- define "srdt.webImage" -}}
{{- $reg := .Values.global.imageRegistry | trimSuffix "/" -}}
{{- $tag := .Values.web.image.tag | default .Chart.AppVersion -}}
{{- if $reg -}}
{{- printf "%s/%s:%s" $reg .Values.web.image.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" .Values.web.image.repository $tag -}}
{{- end -}}
{{- end -}}
