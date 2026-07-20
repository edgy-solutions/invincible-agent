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
In-cluster service domain suffix appended to every <release>-<svc> name.

Defaults to the FQDN form `.<release-ns>.svc.cluster.local` — NOT empty.

Why the default matters: a BARE service name (`<release>-engine-a`) has no
dots, so it does NOT suffix-match a NO_PROXY entry of ".svc" or
".svc.cluster.local". Under a corporate proxy the in-cluster call is then
handed to the proxy and dies (`ProxyError ... Unable to connect to proxy`).
This bit the supervisor's verb dispatch: engines registered a bare
`endpoint_url`, so every specialist call was proxied and `execute_subtask`
failed, which cascaded to no UI payload and a blank answer card. The
dagsterUrl helper below already hardcodes the FQDN for exactly this reason;
this helper defaulting to "" meant every engine URL silently lost that
protection whenever global.clusterDomain wasn't set.

The FQDN resolves identically inside the cluster whether or not a proxy is
configured, so it is strictly safer as the default. global.clusterDomain
remains an override for clusters whose domain isn't `cluster.local`.

NOTE: endpoint_url is baked into the verb edge at REGISTRATION time —
re-register (rollout restart the engines) after changing this, or existing
edges keep the old form.
*/}}
{{- define "invincible-agent.svcDomain" -}}
{{- if .Values.global.clusterDomain -}}
{{- .Values.global.clusterDomain -}}
{{- else -}}
.{{ .Release.Namespace }}.svc.cluster.local
{{- end -}}
{{- end }}

{{/*
Full image path for a service.
Usage:
  include "invincible-agent.image" (dict
    "name" "restate-analyst"
    "tag" .Values.engineA.image.tag
    "root" .)
Optional override knobs (purely additive; existing callers unaffected):
  "registry"   — full registry host, e.g. "docker.io". Takes precedence
                 over .Values.global.imageRegistry when set. Lets a single
                 component (e.g. the canonical dagster-k8s image) live at
                 a different registry from the rest of the iagent images.
  "repository" — repository path; concatenated with the registry above.
*/}}
{{- define "invincible-agent.image" -}}
{{- $tag := .tag | default .root.Chart.AppVersion -}}
{{- if .registry -}}
{{ .registry }}/{{ .repository | default (printf "%s/%s" .root.Values.global.imagePrefix .name) }}:{{ $tag }}
{{- else if .repository -}}
{{ .root.Values.global.imageRegistry }}/{{ .repository }}:{{ $tag }}
{{- else -}}
{{ .root.Values.global.imageRegistry }}/{{ .root.Values.global.imagePrefix }}/{{ .name }}:{{ $tag }}
{{- end -}}
{{- end }}

{{/*
PostgreSQL connection host — uses subchart or external
*/}}
{{- define "invincible-agent.pgHost" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Release.Name }}-postgresql{{ include "invincible-agent.svcDomain" . }}
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
http://{{ .Release.Name }}-restate{{ include "invincible-agent.svcDomain" . }}:{{ .Values.restate.ingressPort }}
{{- else -}}
{{ .Values.externalRestate.ingressUrl }}
{{- end -}}
{{- end }}
{{/*
Restate admin URL — uses in-chart deployment or external
*/}}
{{- define "invincible-agent.restateAdminUrl" -}}
{{- if .Values.restate.enabled -}}
http://{{ .Release.Name }}-restate{{ include "invincible-agent.svcDomain" . }}:{{ .Values.restate.adminPort }}
{{- else -}}
{{ .Values.externalRestate.adminUrl }}
{{- end -}}
{{- end }}

{{/*
Neo4j URI
*/}}
{{- define "invincible-agent.neo4jUri" -}}
{{- if .Values.neo4j.enabled -}}
bolt://{{ .Release.Name }}-neo4j{{ include "invincible-agent.svcDomain" . }}:7687
{{- else -}}
{{ .Values.externalNeo4j.uri }}
{{- end -}}
{{- end }}

{{/*
Neo4j Username
*/}}
{{- define "invincible-agent.neo4jUsername" -}}
{{- if .Values.neo4j.enabled -}}
{{ .Values.neo4j.auth.username }}
{{- else -}}
{{ .Values.externalNeo4j.username }}
{{- end -}}
{{- end }}

{{/*
Neo4j Password
*/}}
{{- define "invincible-agent.neo4jPassword" -}}
{{- if .Values.neo4j.enabled -}}
{{ .Values.neo4j.auth.password }}
{{- else -}}
{{ .Values.externalNeo4j.password }}
{{- end -}}
{{- end }}

{{/*
Weaviate URL
*/}}
{{- define "invincible-agent.weaviateUrl" -}}
{{- if .Values.weaviate.enabled -}}
http://{{ .Release.Name }}-weaviate{{ include "invincible-agent.svcDomain" . }}:8080
{{- else -}}
{{ .Values.externalWeaviate.url }}
{{- end -}}
{{- end }}

{{/*
Fuseki URL
*/}}
{{- define "invincible-agent.fusekiUrl" -}}
{{- if .Values.fuseki.enabled -}}
http://{{ .Release.Name }}-fuseki{{ include "invincible-agent.svcDomain" . }}:3030
{{- else -}}
{{ .Values.externalFuseki.url }}
{{- end -}}
{{- end }}

{{/*
Dagster webserver URL — uses in-chart deployment or external.

Used by prime-substrate-job for --trigger-ingest.

When using the chart's bundled Dagster, returns the FQDN form
(<release>-dagster-webserver.<release-ns>.svc.cluster.local:80) so a
NO_PROXY entry of ".svc.cluster.local" suffix-matches and the corporate
proxy doesn't intercept the in-cluster call.

When using an external (BYO) Dagster, returns externalDagster.url
verbatim — operators set the FQDN themselves there.
*/}}
{{- define "invincible-agent.dagsterUrl" -}}
{{- if .Values.dagster.webserver.enabled -}}
http://{{ .Release.Name }}-dagster.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.dagster.webserver.port }}
{{- else -}}
{{ .Values.externalDagster.url }}
{{- end -}}
{{- end }}
