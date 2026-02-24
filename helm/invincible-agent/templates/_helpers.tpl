{{/*
Common labels
*/}}
{{- define "invincible-agent.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Selector labels for a component
Usage: include "invincible-agent.selectorLabels" (dict "component" "engine-a" "root" .)
*/}}
{{- define "invincible-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Full image path for a service
Usage: include "invincible-agent.image" (dict "name" "restate-analyst" "tag" .Values.engineA.image.tag "root" .)
*/}}
{{- define "invincible-agent.image" -}}
{{- $tag := .tag | default .root.Chart.AppVersion -}}
{{ .root.Values.global.imageRegistry }}/{{ .root.Values.global.imagePrefix }}/{{ .name }}:{{ $tag }}
{{- end }}

{{/*
PostgreSQL connection host — uses subchart or external
*/}}
{{- define "invincible-agent.pgHost" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Release.Name }}-postgresql
{{- else -}}
{{ .Values.externalPostgresql.host }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL connection port
*/}}
{{- define "invincible-agent.pgPort" -}}
{{- if .Values.postgresql.enabled -}}
5432
{{- else -}}
{{ .Values.externalPostgresql.port | default 5432 }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL database name
*/}}
{{- define "invincible-agent.pgDatabase" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Values.postgresql.auth.database }}
{{- else -}}
{{ .Values.externalPostgresql.database }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL username
*/}}
{{- define "invincible-agent.pgUser" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Values.postgresql.auth.username }}
{{- else -}}
{{ .Values.externalPostgresql.username }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL password
*/}}
{{- define "invincible-agent.pgPassword" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Values.postgresql.auth.password }}
{{- else -}}
{{ .Values.externalPostgresql.password }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL connection URI
*/}}
{{- define "invincible-agent.pgUri" -}}
postgresql://{{ include "invincible-agent.pgUser" . }}:{{ include "invincible-agent.pgPassword" . }}@{{ include "invincible-agent.pgHost" . }}:{{ include "invincible-agent.pgPort" . }}/{{ include "invincible-agent.pgDatabase" . }}
{{- end }}

{{/*
Restate ingress URL — uses in-chart deployment or external
*/}}
{{- define "invincible-agent.restateIngressUrl" -}}
{{- if .Values.restate.enabled -}}
http://{{ .Release.Name }}-restate:{{ .Values.restate.ingressPort }}
{{- else -}}
{{ .Values.externalRestate.ingressUrl }}
{{- end -}}
{{- end }}
{{/*
Restate admin URL — uses in-chart deployment or external
*/}}
{{- define "invincible-agent.restateAdminUrl" -}}
{{- if .Values.restate.enabled -}}
http://{{ .Release.Name }}-restate:{{ .Values.restate.adminPort }}
{{- else -}}
{{ .Values.externalRestate.adminUrl }}
{{- end -}}
{{- end }}
