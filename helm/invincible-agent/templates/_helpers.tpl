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
{{/*
TAG PRECEDENCE: a component's own `tag`, then `global.imageTag`, then `global.defaultImageTag`,
then `Chart.Version`. A tag is only the fallback: an image renders BY DIGEST whenever one is known,
and `scripts/seal_image_digests.py` fails any rendered image that is left on a tag.

DIGEST RESOLUTION: the call site's own `digest` wins; otherwise the helper reads
`global.imageDigests[<registry>/<repository>]`, keyed by the full reference WITHOUT its tag. That
map is the whole pin: base `values.yaml` holds every image this repo does not build, and the
release workflow writes `values-release-<version>.yaml` carrying every image it does (from the
build) and re-confirms the rest (read from the registry), attaching it to the chart release as the
artifact of record. A roll renders with that file and never resolves a tag.

WHY THE TAG CHAIN NO LONGER NEEDS SCOPING. MEASURED 2026-09-09: a commit-sha pin was global over
every image the chart renders, so a sha reached `cortex-ui/frontend`, `dag-tools/central-gateway`,
`dag-tools/user-deployment` and `pub-tools` — repositories that have never built it — and four
deployments went into ImagePullBackOff on a live cluster; changing the floor from `latest` to
`Chart.Version` then broke the same four through the fallback. The fix was to scope the pin and the
floor to repositories under `global.imagePrefix`. The protection is now the digest map plus the
seal: a cross-repo image is named by a digest that repository really holds, and a render that
still carries a tag for ANY image fails the seal, wherever the repository sits. Nothing here tests
a prefix.

THE MAP IS KEYED BY REPOSITORY, NOT BY TAG. A component tag override on an image the map holds
therefore renders the mapped digest and the tag is ignored; change the row to move the image.

EVERY LINE INSIDE THE DEFINE IS DASH-TRIMMED. It renders inline as `image: {{ include ... }}`,
so a single untrimmed newline produces `could not find expected ':'` in a file that has nothing
wrong with it. Comments belong out here, not in there.
*/}}
{{- define "invincible-agent.image" -}}
{{- $repo := .repository | default (printf "%s/%s" .root.Values.global.imagePrefix .name) -}}
{{- $tag := .tag | default .root.Values.global.imageTag | default .root.Values.global.defaultImageTag | default .root.Chart.Version -}}
{{- $registry := .registry | default .root.Values.global.imageRegistry -}}
{{- $digest := .digest | default (get (.root.Values.global.imageDigests | default dict) (printf "%s/%s" $registry $repo)) -}}
{{- if $digest -}}
{{ $registry }}/{{ $repo }}@{{ $digest }}
{{- else -}}
{{ $registry }}/{{ $repo }}:{{ $tag }}
{{- end -}}
{{- end }}

{{/*
Stateful-core spread group — shared label + preferred pod anti-affinity.

The stateful core is EVERY StatefulSet that claims a volume (spec.volumeClaimTemplates):
Keycloak, Restate, Weaviate, PostgreSQL, Neo4j and Fuseki. Each runs a single replica backed by
a `local-path` PVC. Until 0.4.29 only the first three were in the set; roll #16 then left Neo4j
Pending once the node holding its volume was labelled, because the other three carried the
avoid rule below. tests/test_stateful_core_resources_and_spread.py derives the set from the
render, so a new claiming StatefulSet outside it reds. MEASURED 2026-10-02, four such PVs
(Keycloak, Restate, Weaviate plus MinIO) were pinned to the SAME node —
local-path has no cross-node migration, so whichever node first provisioned the PV is the only
node that can ever mount it again. A REQUIRED pod anti-affinity on this label would therefore
leave every pod after the first one scheduled permanently Pending: the scheduler would be asked
to avoid a node that is the ONLY node any of them can run on. So this is
`preferredDuringSchedulingIgnoredDuringExecution` ONLY, and must stay that way until the
volumes themselves are migrated off local-path (a separate decision) — a requirement would be a
regression here, not a hardening.

MinIO (`iagent-minio`) is deployed EXTERNALLY to this chart (see the `minioBucketInit` comment
block in values.yaml — "a separate manifest, not chart dependencies") and has no pod template in
this repo, so it cannot carry this label or affinity from here; it is not part of this group.

Toggle: global.statefulSpread.enabled (default true). Weight: global.statefulSpread.weight
(default 100). Both return empty when disabled, so the call sites below render a harmless blank
line — never add the label to a StatefulSet's spec.selector.matchLabels (selectors are
immutable; changing one breaks `helm upgrade` on an existing release), only to pod template
metadata.
*/}}
{{- define "invincible-agent.statefulSpreadLabel" -}}
{{- if .Values.global.statefulSpread.enabled -}}
iagent.io/spread-group: stateful-core
{{- end -}}
{{- end }}

{{- define "invincible-agent.statefulSpreadAffinity" -}}
{{- if .Values.global.statefulSpread.enabled -}}
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: {{ .Values.global.statefulSpread.weight | default 100 }}
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels:
              iagent.io/spread-group: stateful-core
{{- end -}}
{{- end }}

{{/*
"Not stateful nodes" — a REQUIRED nodeAffinity that keeps every pod EXCEPT the stateful core
(every volume-claiming StatefulSet — see invincible-agent.statefulSpreadLabel/Affinity above)
off any node carrying global.statefulNodes.labelKey. The label is applied to nodes OUT OF
CHART (the operator labels whichever node(s) hold the stateful-core's local-path PVs); this
define is the reservation's other half, and REQUIRED (unlike the spread affinity above) is
correct here because the condition is the opposite shape: avoiding ONE specific node (or small
labelled set) is always satisfiable by the many other nodes in the pool, whereas the spread
affinity above has to avoid pods pinned to each other with nowhere else for any of them to go.
A cordon would do the same job, but has to be reapplied by hand after every cluster change;
this is the no-cordon-needed equivalent, expressed as a chart default.

DoesNotExist, not a value match — ANY value on the label key reserves the node, so a node can
be marked reserved without the chart needing to agree on what the value should be.

Rendered only when global.statefulNodes.enabled (default true), and renders the WHOLE
`affinity:` key, same convention as statefulSpreadAffinity above — a call site simply includes
this with no wrapping. AT THIS CHART'S HEAD no non-stateful-core pod template has an affinity
of its own, so every call site is a straight include; if one ever gains its own affinity block,
that template must MERGE this nodeAffinity into its existing `affinity:` key by hand (a document
may carry only one `affinity:` key, and an existing `required.nodeSelectorTerms` needs this
matchExpression appended into EACH existing term, since terms are OR'd together) rather than
including this verbatim.
*/}}
{{- define "invincible-agent.avoidStatefulNodes" -}}
{{- if .Values.global.statefulNodes.enabled -}}
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: {{ .Values.global.statefulNodes.labelKey }}
              operator: DoesNotExist
{{- end -}}
{{- end }}

{{/*
Validates .Values.keycloak.serviceClients CONCATENATED WITH .Values.keycloak.extraServiceClients
— ONE check, called by BOTH consumers (keycloak-configmap.yaml's first-boot import and
realm-reconcile-job.yaml's reconcile), so the rule lives in exactly one place rather than
drifting between two copies. The two lists share one schema: extraServiceClients exists so an
environment overlay can APPEND clients without replacing the base serviceClients list (a Helm
overlay replaces a list wholesale).

  - kind (optional, default "service") must be "service" or "delegate".
  - onBehalfOf is allowed only when kind is delegate.
  - each onBehalfOf.user must name a keycloak.nonInteractiveUsers entry (same pattern as
    meshRegistrar.onBehalfOfUser in mesh-registrar.yaml).
  - each onBehalfOf.role must be "operator" or "supervisor".

Emits nothing on success; `fail`s the render on the first violation.
*/}}
{{- define "invincible-agent.validateServiceClients" -}}
{{- range $c := concat .Values.keycloak.serviceClients (.Values.keycloak.extraServiceClients | default list) }}
{{- $kind := $c.kind | default "service" }}
{{- if not (or (eq $kind "service") (eq $kind "delegate")) }}
{{- fail (printf "keycloak.serviceClients/extraServiceClients: client %q has kind %q; must be \"service\" or \"delegate\"" $c.clientId $kind) }}
{{- end }}
{{- if and $c.onBehalfOf (ne $kind "delegate") }}
{{- fail (printf "keycloak.serviceClients/extraServiceClients: client %q declares onBehalfOf but kind is %q; onBehalfOf is allowed only on a delegate client" $c.clientId $kind) }}
{{- end }}
{{- range $o := $c.onBehalfOf }}
{{- $found := false }}
{{- range $u := $.Values.keycloak.nonInteractiveUsers }}
{{- if eq $u.username $o.user }}{{- $found = true }}{{- end }}
{{- end }}
{{- /* A principal is a DECLARATION: it is named whether or not the broker is rendered. */}}
{{- range $bn, $b := ($.Values.keycloak.brokers | default dict) }}
{{- range $p := $b.principals }}
{{- if eq $p.username $o.user }}{{- $found = true }}{{- end }}
{{- end }}
{{- end }}
{{- if not $found }}
{{- fail (printf "keycloak.serviceClients/extraServiceClients: client %q onBehalfOf user %q is neither a keycloak.nonInteractiveUsers entry nor a principal of a declared keycloak.brokers entry" $c.clientId $o.user) }}
{{- end }}
{{- if not (or (eq $o.role "operator") (eq $o.role "supervisor")) }}
{{- fail (printf "keycloak.serviceClients/extraServiceClients: client %q onBehalfOf user %q has role %q; must be \"operator\" or \"supervisor\"" $c.clientId $o.user $o.role) }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Validates keycloak.publicClients (PKCE browser clients; see values.yaml). A public client has no
secret, so its redirect URIs are its only protection: the render `fail`s on
  - an empty or repeated clientId;
  - a clientId that is cortex-ui or any serviceClients/extraServiceClients clientId;
  - empty redirectUris, a redirectUri that is "*" or does not start with https://;
  - a webOrigin that is "*".
Emits nothing on success.
*/}}
{{- define "invincible-agent.validatePublicClients" -}}
{{- $seen := dict }}
{{- $svc := dict }}
{{- range $s := concat .Values.keycloak.serviceClients (.Values.keycloak.extraServiceClients | default list) }}
{{- $_ := set $svc $s.clientId true }}
{{- end }}
{{- range $c := (.Values.keycloak.publicClients | default list) }}
{{- if not $c.clientId }}
{{- fail "keycloak.publicClients: an entry has an empty clientId" }}
{{- end }}
{{- if hasKey $seen $c.clientId }}
{{- fail (printf "keycloak.publicClients: clientId %q is declared more than once" $c.clientId) }}
{{- end }}
{{- $_ := set $seen $c.clientId true }}
{{- if or (eq $c.clientId "cortex-ui") (hasKey $svc $c.clientId) }}
{{- fail (printf "keycloak.publicClients: clientId %q collides with cortex-ui or a serviceClients/extraServiceClients client" $c.clientId) }}
{{- end }}
{{- if not $c.redirectUris }}
{{- fail (printf "keycloak.publicClients: client %q has no redirectUris" $c.clientId) }}
{{- end }}
{{- range $r := $c.redirectUris }}
{{- /* https, and a literal host: "https://*" passes a prefix test and is still a wildcard */}}
{{- if not (regexMatch "^https://[^/*]+(/.*)?$" (toString $r)) }}
{{- fail (printf "keycloak.publicClients: client %q redirectUri %q must be https:// with a literal host (no \"*\" before the path)" $c.clientId (toString $r)) }}
{{- end }}
{{- end }}
{{- range $w := ($c.webOrigins | default list) }}
{{- if eq (toString $w) "*" }}
{{- fail (printf "keycloak.publicClients: client %q webOrigin %q may not be \"*\"" $c.clientId (toString $w)) }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
The cortex-ui client's redirect set (see keycloak.cortexUiClient in values.yaml). Renders a JSON
object with keys redirectUris, webOrigins, postLogoutRedirectUris; call sites use `fromJson`.
Each key is the declared list when non-empty, else derived from cortexUi.ingress (only when the
ingress is enabled): for each TLS host h, "https://h" then "https://h/" (origin: "https://h";
post-logout: "https://h/"), else []. The RESULT is validated: a redirect or post-logout URI must be
https with a literal host and carry no "*" anywhere; a web origin must be https://host with no path.
Call: include "invincible-agent.cortexUiRedirects" . | fromJson
*/}}
{{- define "invincible-agent.cortexUiRedirects" -}}
{{- $d := (.Values.keycloak.cortexUiClient | default dict) }}
{{- $ing := (.Values.cortexUi.ingress | default dict) }}
{{- $hosts := list }}
{{- if $ing.enabled }}
{{- range $t := ($ing.tls | default list) }}
{{- range $h := ($t.hosts | default list) }}
{{- if not (has $h $hosts) }}{{- $hosts = append $hosts $h }}{{- end }}
{{- end }}
{{- end }}
{{- end }}
{{- $redir := list }}
{{- $orig := list }}
{{- $logout := list }}
{{- range $h := $hosts }}
{{- $redir = concat $redir (list (printf "https://%s" $h) (printf "https://%s/" $h)) }}
{{- $orig = append $orig (printf "https://%s" $h) }}
{{- $logout = append $logout (printf "https://%s/" $h) }}
{{- end }}
{{- if $d.redirectUris }}{{- $redir = $d.redirectUris }}{{- end }}
{{- if $d.webOrigins }}{{- $orig = $d.webOrigins }}{{- end }}
{{- if $d.postLogoutRedirectUris }}{{- $logout = $d.postLogoutRedirectUris }}{{- end }}
{{- range $r := $redir }}
{{- if or (not (regexMatch "^https://[^/*]+(/.*)?$" (toString $r))) (contains "*" (toString $r)) }}
{{- fail (printf "keycloak.cortexUiClient.redirectUris: cortex-ui redirect %q must be https:// with a literal host and no \"*\" anywhere" (toString $r)) }}
{{- end }}
{{- end }}
{{- range $r := $logout }}
{{- if or (not (regexMatch "^https://[^/*]+(/.*)?$" (toString $r))) (contains "*" (toString $r)) }}
{{- fail (printf "keycloak.cortexUiClient.postLogoutRedirectUris: cortex-ui post-logout redirect %q must be https:// with a literal host and no \"*\" anywhere" (toString $r)) }}
{{- end }}
{{- end }}
{{- range $w := $orig }}
{{- if not (regexMatch "^https://[^/*]+$" (toString $w)) }}
{{- fail (printf "keycloak.cortexUiClient.webOrigins: cortex-ui web origin %q must be https://host with a literal host and no path or \"*\"" (toString $w)) }}
{{- end }}
{{- end }}
{{- dict "redirectUris" $redir "webOrigins" $orig "postLogoutRedirectUris" $logout | toJson }}
{{- end }}

{{/*
A broker is RENDERED only when enabled AND its client secret has a source: an existingSecret, or a
clientSecret value (set only in a gitignored *.secret.yaml; secrets.yaml puts it in the release
Secret). Enabled with neither renders nothing (the reconcile job carries a NOTE) and never fails.
Call: include "invincible-agent.brokerActive" $b  -> "true" or "".
*/}}
{{- define "invincible-agent.brokerActive" -}}
{{- if and .enabled (or .existingSecret .clientSecret) }}true{{- end }}
{{- end }}

{{/*
The authz_id a LOCAL user gets: the user's email unless the values give an explicit authzId.
Only meaningful when keycloak.authzClaim is not "email" (then the email IS the claim).
Call: include "invincible-agent.localAuthzId" (dict "root" $ "username" u "email" e)
*/}}
{{- define "invincible-agent.localAuthzId" -}}
{{- $id := .email -}}
{{- if ne (.root.Values.keycloak.authzClaim | default "email") "email" -}}
{{- range $u := concat (.root.Values.keycloak.localHumanUsers | default list) (.root.Values.keycloak.nonInteractiveUsers | default list) -}}
{{- if and (eq $u.username $.username) $u.authzId -}}{{- $id = $u.authzId -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- $id -}}
{{- end }}

{{/*
Fail the render on a broker that cannot work. Called wherever the broker is consumed.
*/}}
{{- define "invincible-agent.validateBrokers" -}}
{{- range $bn, $b := ($.Values.keycloak.brokers | default dict) }}
{{- if $b.enabled }}
{{- if not $b.issuer }}
{{- fail (printf "keycloak.brokers.%s is enabled but issuer is empty; set the upstream realm issuer URL" $bn) }}
{{- end }}
{{- if eq ($.Values.keycloak.authzClaim | default "email") "email" }}
{{- fail (printf "keycloak.brokers.%s is enabled but keycloak.authzClaim is \"email\"; a brokered principal's authz identity is its upstream sub and cannot ride the email claim" $bn) }}
{{- end }}
{{- if not $.Values.keycloak.reconcileClients.enabled }}
{{- fail (printf "keycloak.brokers.%s is enabled but keycloak.reconcileClients.enabled is false; the broker is created only by the realm-reconcile job" $bn) }}
{{- end }}
{{- if and (hasPrefix "https:" $b.issuer) (not $b.publicCA) (not (($.Values.keycloak.truststore | default dict).enabled)) }}
{{- fail (printf "keycloak.brokers.%s is enabled with an https issuer but keycloak.truststore.enabled is false: Keycloak would not trust a private-CA issuer. Enable keycloak.truststore (caPem or existingConfigMap), or set keycloak.brokers.%s.publicCA: true if the issuer's certificate is publicly trusted" $bn $bn) }}
{{- end }}
{{- end }}
{{- end }}
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
Weaviate URL (scheme-ful form, for consumers that want a URL)
*/}}
{{- define "invincible-agent.weaviateUrl" -}}
{{- if .Values.weaviate.enabled -}}
http://{{ .Release.Name }}-weaviate{{ include "invincible-agent.svcDomain" . }}:8080
{{- else -}}
{{ .Values.externalWeaviate.url }}
{{- end -}}
{{- end }}

{{/*
Weaviate HOST:PORT — what the fleet actually reads (WEAVIATE_HTTP_HOST /
WEAVIATE_GRPC_HOST are host:port, NOT URLs; the client adds the scheme).

These exist because the ConfigMap previously hardcoded a BARE
`<release>-weaviate:8080`, which had two consequences:
  1. cross-namespace was impossible — `externalWeaviate` was declared but
     nothing consumed it, so setting it changed nothing (dead config);
  2. a bare name has no dots, so it does NOT suffix-match a NO_PROXY entry of
     ".svc.cluster.local" — the same corporate-proxy trap documented on
     svcDomain above, which killed supervisor verb dispatch once already.
Routing these through svcDomain fixes both. In-namespace resolution is
unchanged (the FQDN resolves identically), so this is safe for existing
releases.

The gRPC port is the literal 50051 to MATCH the Service in
infrastructure.yaml, which also hardcodes it. `weaviate.grpcServicePort` is
declared in values.yaml but consumed by nothing — deliberately not wired in
here, because doing so would let a changed value point the fleet at a port
the Service does not expose. Fix the Service first if that knob should live.
*/}}
{{- define "invincible-agent.weaviateHttpHost" -}}
{{- if .Values.weaviate.enabled -}}
{{ .Release.Name }}-weaviate{{ include "invincible-agent.svcDomain" . }}:8080
{{- else if .Values.externalWeaviate.httpHost -}}
{{ .Values.externalWeaviate.httpHost }}
{{- else -}}
{{ .Values.externalWeaviate.url | trimPrefix "https://" | trimPrefix "http://" | trimSuffix "/" }}
{{- end -}}
{{- end }}

{{- define "invincible-agent.weaviateGrpcHost" -}}
{{- if .Values.weaviate.enabled -}}
{{ .Release.Name }}-weaviate-grpc{{ include "invincible-agent.svcDomain" . }}:50051
{{- else -}}
{{ .Values.externalWeaviate.grpcHost }}
{{- end -}}
{{- end }}

{{/*
Keycloak realm URL — in-chart deployment or external.

`keycloak.enabled: false` removes the DEPLOYMENT but the realm URL used to be
rendered unconditionally against `<release>-keycloak`, leaving a dangling
in-namespace reference with no override. Two escape hatches, in precedence
order: `externalKeycloak.realmUrl` (full override, for an issuer whose path
isn't /realms/<realm>) then `externalKeycloak.url` (base, realm appended from
`keycloak.realm` — the realm NAME is independent of where keycloak runs).
*/}}
{{- define "invincible-agent.keycloakRealmUrl" -}}
{{- if .Values.keycloak.enabled -}}
http://{{ .Release.Name }}-keycloak{{ include "invincible-agent.svcDomain" . }}:8080/realms/{{ .Values.keycloak.realm }}
{{- else if .Values.externalKeycloak.realmUrl -}}
{{ .Values.externalKeycloak.realmUrl }}
{{- else -}}
{{ .Values.externalKeycloak.url | trimSuffix "/" }}/realms/{{ .Values.keycloak.realm }}
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

{{/*
  invincible-agent.networkPolicyStores — THE ONE store -> ports table.

  Returns a JSON list of {component, ports}: every store that gets an ingress policy
  (templates/networkpolicy-stores.yaml) AND the ports an engine's egress rule opens to it
  (templates/networkpolicy-engines.yaml, for a `networkPolicy.directCallers` entry). Both
  templates read THIS define, so the two halves of a direct caller's admission cannot disagree
  about a port. Duplicating the table in either template is the defect this define removes.

  A component belongs here only if the chart renders it with the standard
  `app.kubernetes.io/component` label. Redis and MinIO are NOT chart components (measured by
  rendering values-sandbox.yaml), so a policy for either would select no pod while looking right.
  Topaz is one: 9393 is the directory port TOPAZ_DIRECTORY_URL names.

  Consume with: fromJsonArray (include "invincible-agent.networkPolicyStores" .)
*/}}
{{- define "invincible-agent.networkPolicyStores" -}}
{{- list
  (dict "component" "postgresql" "ports" (list 5432))
  (dict "component" "keycloak" "ports" (list 8080))
  (dict "component" "weaviate" "ports" (list 8080 50051))
  (dict "component" "neo4j" "ports" (list 7474 7687))
  (dict "component" "restate" "ports" (list 8080 9070))
  (dict "component" "fuseki" "ports" (list 3030))
  (dict "component" "topaz" "ports" (list 9393))
| toJson -}}
{{- end }}{{- /*
keycloak.retiredUsers guard: every entry is a plain username (letters, digits, . _ -), and none is
still declared as a local user the chart creates (nonInteractiveUsers / localHumanUsers) -- a name
both created and deleted on every run is a contradiction, so the render fails.
*/}}
{{- define "invincible-agent.validateRetiredUsers" -}}
{{- range $r := (.Values.keycloak.retiredUsers | default list) }}
{{- if not (regexMatch "^[A-Za-z0-9][A-Za-z0-9._-]*$" (toString $r)) }}
{{- fail (printf "keycloak.retiredUsers: %q is not a plain username" (toString $r)) }}
{{- end }}
{{- range $u := concat ($.Values.keycloak.nonInteractiveUsers | default list) ($.Values.keycloak.localHumanUsers | default list) }}
{{- if eq $u.username $r }}
{{- fail (printf "keycloak.retiredUsers: %q is also declared in keycloak.nonInteractiveUsers/localHumanUsers" $r) }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}



{{/*
Keycloak's extra-CA truststore (a pinned self-signed leaf; there is no lab CA). Enabled needs EXACTLY ONE
of existingSecret / existingConfigMap; caPem was removed. Called from keycloak.yaml.
*/}}
{{- define "invincible-agent.validateTruststore" -}}
{{- $t := $.Values.keycloak.truststore | default dict -}}
{{- if hasKey $t "caPem" }}
{{- fail "caPem was removed: the cert is not a secret and does not go in the secret values file; create a Secret and set keycloak.truststore.existingSecret" }}
{{- end }}
{{- if and $t.enabled (eq (not $t.existingSecret) (not $t.existingConfigMap)) }}
{{- fail "keycloak.truststore.enabled is true but not exactly one of existingSecret / existingConfigMap is set (zero or both); set one of them" }}
{{- end }}
{{- end }}

{{/*
  invincible-agent.networkPolicyEgressOnlyTargets -- components an engine may be a direct caller
  of that are NOT stores (no ingress policy is rendered for them, so nothing else is cut) and
  NOT engines (no `.port` value to read). Only networkpolicy-engines.yaml reads this: it makes the
  component nameable as a `directCallers` store, rendering the engine's egress rule and no ingress
  policy. Added because DAGSTER_WEBSERVER_URL (iagent-config, every engine) is a flow no other
  table could express; a store table entry would have fenced dagster-webserver's ingress for
  every other caller. Port 3000 is the container port the Service's `http` targetPort resolves to.
*/}}
{{- define "invincible-agent.networkPolicyEgressOnlyTargets" -}}
{{- list
  (dict "component" "dagster-webserver" "ports" (list 3000))
| toJson -}}
{{- end }}

{{/*
  policyOverlay -- an initContainer gives NAMED pods NAMED dirs of the private policy repo, at a
  pinned ref (ruled 2026-11-02: "an initContainer that clones the policy repo at a pinned ref into
  the pods"). Contract: docs/contracts/finance-overlays.md section 4. Values: `policyOverlay`.

  Five helpers, all taking (dict "root" $ "component" "<component>"). All but the first render
  NOTHING and are called only behind the first:
    policyOverlayActive   "true" or "" -- enabled AND the component has a row; the render-time
                          `fail`s live here
    policyOverlayInit     the initContainer list item
    policyOverlayVolumes  the volumes list items
    policyOverlayMounts   the main container's volumeMounts list item
    policyOverlayEnv      the main container's env list items

  The repo, image, credential and CA are the SEED's (`topazSeed.policySource.git`): one repo, one
  credential. The clone lives in `overlay-src`, mounted ONLY in the init container; the main
  container gets `policy-overlay`, read-only, holding only the dirs its component names -- never
  the repo's users or grants.
*/}}
{{- define "invincible-agent.policyOverlayActive" -}}
{{- $po := .root.Values.policyOverlay | default (dict) -}}
{{- if $po.enabled -}}
{{- if not $po.ref -}}
{{- fail "policyOverlay.ref is required when policyOverlay.enabled: a full commit sha or a tag (a branch name is refused at clone)" -}}
{{- end -}}
{{- if not .root.Values.topazSeed.policySource.git.repoUrl -}}
{{- fail "topazSeed.policySource.git.repoUrl is required when policyOverlay.enabled: the overlay is cloned from it" -}}
{{- end -}}
{{- if index ($po.components | default (dict)) .component -}}true{{- end -}}
{{- end -}}
{{- end -}}

{{- define "invincible-agent.policyOverlayInit" -}}
{{- $po := .root.Values.policyOverlay -}}
{{- $git := .root.Values.topazSeed.policySource.git -}}
{{- $gitImg := $git.image -}}
{{- if not (kindIs "string" $gitImg) -}}
{{- $gitImg = include "invincible-agent.image" (dict "registry" ($gitImg.registry | default "docker.io") "repository" ($gitImg.repository | default "alpine/git") "tag" ($gitImg.tag | default "v2.45.2") "root" .root) -}}
{{- end -}}
{{- $mount := $po.mountPath | default "/policy-overlay" | trimSuffix "/" -}}
{{- $sub := $po.path | default "" | trimAll "/" -}}
{{- $base := ternary (printf "/overlay-src/repo/%s" $sub) "/overlay-src/repo" (ne $sub "") -}}
- name: fetch-policy-overlay
  image: {{ $gitImg | quote }}
  env:
    - name: GIT_REPO_URL
      value: {{ $git.repoUrl | quote }}
    - name: GIT_REF
      value: {{ $po.ref | quote }}
    {{- if $git.caSecretName }}
    # Verification stays ON against the mounted bundle; there is no skip-verify.
    - name: GIT_SSL_CAINFO
      value: /git-ca/ca.crt
    {{- end }}
    {{- if $git.authSecretName }}
    - name: GIT_USERNAME
      valueFrom:
        secretKeyRef:
          name: {{ $git.authSecretName | quote }}
          key: username
    - name: GIT_PASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ $git.authSecretName | quote }}
          key: password
    {{- end }}
  command: ["sh", "-c"]
  args:
    - |
      set -e
      if [ -n "${GIT_USERNAME:-}" ]; then
        printf '#!/bin/sh\ncase "$1" in\n  Username*) echo "$GIT_USERNAME" ;;\n  Password*) echo "$GIT_PASSWORD" ;;\nesac\n' > /tmp/askpass.sh
        chmod +x /tmp/askpass.sh
        export GIT_ASKPASS=/tmp/askpass.sh
      fi
      git init -q /overlay-src/repo
      cd /overlay-src/repo
      # A full 40-hex sha is fetched as itself; anything else is a TAG. A branch has no
      # refs/tags/<name>, so a branch name fails at the fetch: the ref is pinned, not tracked.
      sha=0
      if printf '%s' "$GIT_REF" | grep -Eq '^[0-9a-f]{40}$'; then
        sha=1
        want="$GIT_REF"
      else
        want="refs/tags/$GIT_REF"
      fi
      git fetch -q --depth 1 -- "$GIT_REPO_URL" "$want"
      git checkout -q --detach 'FETCH_HEAD^{commit}'
      if [ "$sha" = 1 ] && [ "$(git rev-parse HEAD)" != "$GIT_REF" ]; then
        echo "policy overlay: fetched commit $(git rev-parse HEAD) is not the pinned $GIT_REF" >&2
        exit 1
      fi
      echo "policy overlay at commit: $(git rev-parse HEAD)"
      {{- range index $po.components .component }}
      {{- if not (regexMatch "^[A-Za-z0-9_.-]+$" .dir) }}
      {{- fail (printf "policyOverlay.components dir %q must be a plain directory name" .dir) }}
      {{- end }}
      if [ -d "{{ $base }}/{{ .dir }}" ]; then
        cp -R "{{ $base }}/{{ .dir }}" "{{ $mount }}/{{ .dir }}"
        echo "policy overlay: delivered {{ .dir }}"
      {{- if .optional }}
      else
        echo "policy overlay: {{ .dir }} is absent in the repo (optional); nothing created"
      {{- else }}
      else
        echo "policy overlay: required directory {{ .dir }} is missing from the repo at {{ $base }}" >&2
        exit 1
      {{- end }}
      fi
      {{- end }}
  volumeMounts:
    - name: overlay-src
      mountPath: /overlay-src
    - name: policy-overlay
      mountPath: {{ $mount | quote }}
    {{- if $git.caSecretName }}
    - name: git-ca
      mountPath: /git-ca
      readOnly: true
    {{- end }}
{{- end -}}

{{- define "invincible-agent.policyOverlayVolumes" -}}
{{- $git := .root.Values.topazSeed.policySource.git -}}
- name: overlay-src
  emptyDir: {}
- name: policy-overlay
  emptyDir: {}
{{- if $git.caSecretName }}
- name: git-ca
  secret:
    secretName: {{ $git.caSecretName | quote }}
    items:
      - key: ca.crt
        path: ca.crt
{{- end }}
{{- end -}}

{{- define "invincible-agent.policyOverlayMounts" -}}
- name: policy-overlay
  mountPath: {{ .root.Values.policyOverlay.mountPath | default "/policy-overlay" | trimSuffix "/" | quote }}
  readOnly: true
{{- end -}}

{{- define "invincible-agent.policyOverlayEnv" -}}
{{- $po := .root.Values.policyOverlay -}}
{{- $mount := $po.mountPath | default "/policy-overlay" | trimSuffix "/" -}}
{{- range $i, $row := index $po.components .component -}}
{{- if $i }}{{ "\n" }}{{ end -}}
- name: {{ $row.env }}
  value: {{ printf "%s/%s" $mount $row.dir | quote }}
{{- end -}}
{{- end -}}

{{/*
  The BFF's accepted issuers / audiences as ONE comma-joined string: `cortexBff.auth.<key>`, each
  entry through tpl, trimmed. Empty list -> "" (an empty value refuses every token). Called with
  (dict "root" $ "key" "acceptedIssuers"). The BFF (frontend.yaml) and the engines
  (engineTokenEnv) both read it, so there is no second copy of the list.
*/}}
{{- define "invincible-agent.acceptedList" -}}
{{- $root := .root -}}
{{- $auth := ($root.Values.cortexBff.auth | default dict) -}}
{{- $out := list -}}
{{- range (index $auth .key | default list) }}{{- $out = append $out (tpl (toString .) $root | trim) }}{{- end -}}
{{- join "," $out -}}
{{- end -}}

{{/*
  The central gateway's accepted issuers / audiences (dag-tools v0.14.0+), the BFF's lists via
  acceptedList, so the gateway admits exactly the tokens the BFF admits. The gateway reads each list
  as the PLURAL name then the SINGULAR one, de-duplicated, so a hand-set name would widen it: the
  plurals and GATEWAY_JWT_AUDIENCE may not be set in centralGateway.env or agentFleet.env, and a
  singular GATEWAY_JWT_ISSUER must already be one of the BFF's issuers (acceptedIssuers quotes it in
  the sandbox). Rendered LAST in the gateway container's env. Called with the root context.
*/}}
{{- define "invincible-agent.gatewayTokenEnv" -}}
{{- $issuers := include "invincible-agent.acceptedList" (dict "root" . "key" "acceptedIssuers") -}}
{{- range $src := list "centralGateway.env" "agentFleet.env" }}
{{- $env := ternary ($.Values.centralGateway.env | default dict) ($.Values.agentFleet.env | default dict) (eq $src "centralGateway.env") }}
{{- range $name := list "GATEWAY_JWT_ISSUERS" "GATEWAY_JWT_AUDIENCES" "GATEWAY_JWT_AUDIENCE" }}
{{- if hasKey $env $name }}{{- fail (printf "%s.%s is rendered from cortexBff.auth; a hand-set value would widen the gateway's list" $src $name) }}{{- end }}
{{- end }}
{{- if and $issuers (hasKey $env "GATEWAY_JWT_ISSUER") (not (has (toString (index $env "GATEWAY_JWT_ISSUER")) (splitList "," $issuers))) }}
{{- fail (printf "%s.GATEWAY_JWT_ISSUER must be one of cortexBff.auth.acceptedIssuers, or the gateway accepts an issuer the BFF refuses" $src) }}
{{- end }}
{{- end -}}
- name: GATEWAY_JWT_ISSUERS
  value: {{ $issuers | quote }}
- name: GATEWAY_JWT_AUDIENCES
  value: {{ include "invincible-agent.acceptedList" (dict "root" . "key" "acceptedAudiences") | quote }}
{{- end -}}

{{/*
  The token-check env every engine pod serves (read by the SDK's transport_auth, v0.9.20+). THE ONLY
  PLACE the MESH_JWT_* / REQUIRE_TRANSPORT_AUTH names are written. Rendered LAST in each engine
  container's env, so it beats the configmap's envFrom (agentFleet.env) and any per-engine env entry
  above it (last duplicate wins). JWKS = the effective KEYCLOAK_REALM_URL (agentFleet.env wins, as in
  configmap.yaml) + /protocol/openid-connect/certs. Called with the root context.
*/}}
{{- define "invincible-agent.engineTokenEnv" -}}
{{- $realm := include "invincible-agent.keycloakRealmUrl" . -}}
{{- $fleet := (.Values.agentFleet.env | default dict) -}}
{{- if hasKey $fleet "KEYCLOAK_REALM_URL" }}{{- $realm = toString (index $fleet "KEYCLOAK_REALM_URL") }}{{- end -}}
- name: MESH_JWT_ACCEPTED_ISSUERS
  value: {{ include "invincible-agent.acceptedList" (dict "root" . "key" "acceptedIssuers") | quote }}
- name: MESH_JWT_ACCEPTED_AUDIENCES
  value: {{ include "invincible-agent.acceptedList" (dict "root" . "key" "acceptedAudiences") | quote }}
- name: MESH_JWT_JWKS_URL
  value: {{ printf "%s/protocol/openid-connect/certs" ($realm | trimSuffix "/") | quote }}
{{- if (.Values.agentFleet.transportAuth | default dict).require }}
- name: REQUIRE_TRANSPORT_AUTH
  value: "true"
{{- end }}
{{- end -}}

{{/*
The overlay-directory variables the ENGINE PODS see, as shell `export` lines for a sync Job.

WHY: "which export profiles does this deployment know" is a question about the overlay the pods
load (the same variables the engines' loaders read). The sync Jobs run the image, which sees only
its base profiles, so capability_grant_sync could not tell a misspelt `can_export:<name>` from an
overlay profile (architect 2026-11-11). This gives the Job what the pods get, with no profile or
variable named here: every `*_OVERLAY_DIRS` entry of agentFleet.env (the shared pod config, which
is where the sandbox points at the sample overlay), then, when policyOverlay is on and the Job reads
the policy repo (mode git), every dir policyOverlay copies into any pod, at the path the pod's
variable would hold. policyOverlay is applied last, as it is on a pod: its variable replaces the
shared one. A dir the repo lacks is skipped (a pod whose required dir is missing refuses to start;
the Job only needs the names).

Call: {{ include "invincible-agent.podOverlayEnv" (dict "root" $ "mode" $mode) | nindent N }}
*/}}
{{- define "invincible-agent.podOverlayEnv" -}}
{{- $v := .root.Values -}}
{{- range $k, $val := ($v.agentFleet.env | default dict) }}
{{- if hasSuffix "_OVERLAY_DIRS" $k }}
export {{ $k }}={{ $val | toString | quote }}
{{- end }}
{{- end }}
{{- if and $v.policyOverlay.enabled (eq .mode "git") }}
{{- $repo := printf "/overlay-src/repo%s" (ternary (printf "/%s" ($v.policyOverlay.path | default "")) "" (ne ($v.policyOverlay.path | default "") "")) }}
{{- range $comp, $rows := $v.policyOverlay.components }}
{{- range $rows }}
if [ -d "{{ $repo }}/{{ .dir }}" ]; then export {{ .env }}="{{ $repo }}/{{ .dir }}"; fi
{{- end }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
The request body that creates one declared service client (POST /clients). One definition, two
callers: realm-reconcile-job.yaml puts it INLINE for a client with no secretRef, and in the
realm-reconcile-bodies Secret (a file the script sends with -d @file) for a client that carries a
"secret". Call: include "invincible-agent.realmReconcileSvcBody" (dict "c" $c "root" $ "claim" $claim "bffAud" $bffAud)
*/}}
{{- define "invincible-agent.realmReconcileSvcBody" -}}
{{- $c := .c }}{{- $claim := .claim }}{{- $bffAud := .bffAud }}
{{- $kind := $c.kind | default "service" }}
{{- $secret := "" }}
{{- if $c.secretRef }}{{- $secret = get .root.Values.keycloak $c.secretRef }}{{- end -}}
{
                    "clientId": {{ $c.clientId | quote }},
                    "enabled": true,
                    "publicClient": false,
                    "serviceAccountsEnabled": true,
                    "standardFlowEnabled": false,
                    "directAccessGrantsEnabled": false,
                    {{- if $c.secretRef }}
                    "secret": {{ $secret | quote }},
                    {{- end }}
                    "protocolMappers": [{
                      "name": "authz-id-svc",
                      "protocol": "openid-connect",
                      "protocolMapper": "oidc-hardcoded-claim-mapper",
                      "config": {
                        "claim.name": {{ $claim | quote }},
                        "claim.value": {{ $c.authzId | quote }},
                        "jsonType.label": "String",
                        "access.token.claim": "true",
                        "id.token.claim": "true",
                        "userinfo.token.claim": "true"
                      }
                    }{{ if eq $kind "delegate" }},{
                      "name": "initiator-kind-svc",
                      "protocol": "openid-connect",
                      "protocolMapper": "oidc-hardcoded-claim-mapper",
                      "config": {
                        "claim.name": "initiator_kind",
                        "claim.value": "delegate",
                        "jsonType.label": "String",
                        "access.token.claim": "true",
                        "id.token.claim": "true",
                        "userinfo.token.claim": "true"
                      }
                    }{{ end }}
                    {{- if $bffAud }},{
                      "name": "audience-bff",
                      "protocol": "openid-connect",
                      "protocolMapper": "oidc-audience-mapper",
                      "config": {
                        "included.custom.audience": {{ $bffAud | quote }},
                        "access.token.claim": "true",
                        "id.token.claim": "false"
                      }
                    }
                    {{- end }}]
                  }
{{- end }}

{{/*
The hook phase of the realm reconcile and the two objects it mounts. A fresh install creates Keycloak
in this very release, so the reconcile must run AFTER it (post-install). An upgrade has a running
Keycloak already, and the reconcile must land BEFORE any workload changes (pre-upgrade).
*/}}
{{- define "invincible-agent.realmReconcileHookPhase" -}}
{{- if .Release.IsInstall }}post-install{{- else }}pre-upgrade{{- end }}
{{- end }}
