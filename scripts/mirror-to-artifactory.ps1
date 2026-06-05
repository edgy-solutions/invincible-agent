<#
.SYNOPSIS
  Mirror every container image the cortex/iagent (invincible-agent +
  cortex-ui + datahub) stack references from its upstream registry
  (ghcr.io / Docker Hub / Quay / Redpanda registry) into a single
  Artifactory (or any other) registry under one base path.

  Hash-aware: each image is checked against the destination first. If
  the destination tag already points at the source's desired digest, the
  image is logged as UNCHANGED and no bytes are transferred. Saves
  bandwidth and gives a clear "what changed since last run" report at
  the end (UPDATE / NEW / UNCHANGED counts).

  Mirrors two image groups, controlled by `-IncludeExternal`:

    1. iagent-owned (always mirrored)
       ghcr.io/edgy-solutions/invincible-agent/* — the 12 engine fleet
         images, dagster runtimes, cortex-bff
       ghcr.io/edgy-solutions/cortex-ui/* — the React frontend
       ghcr.io/edgy-solutions/dag-tools/* — the central-gateway

    2. external dependencies (only with -IncludeExternal)
       DataHub stack (acryldata/datahub-*), OpenSearch, Redpanda,
       Keycloak, Restate, Neo4j, Weaviate, Postgres, Fuseki, Topaz,
       MinIO, Tika, ClickHouse, utilities. These change rarely — once
       seeded into Artifactory you typically don't need to re-mirror
       on a regular cadence.

.DESCRIPTION
  Two copy engines, selectable with -Method:

    buildx  (DEFAULT) -- uses 'docker buildx imagetools', which ships
            with Docker Desktop. No extra tool to install or get
            approved.
    crane             -- uses 'crane' (github.com/google/go-containerregistry).
            Slightly simpler internally, but requires installing crane.

  WHY this is not just 'docker pull / tag / push':
  Every invincible-agent + cortex-ui GHA workflow uses
  docker/build-push-action, which adds a provenance attestation as an
  extra manifest entry with platform unknown/unknown. Docker Desktop
  with the containerd image store keeps that full OCI index locally
  even after 'docker pull --platform', and a subsequent 'docker push'
  sends the index, which Artifactory rejects:
    image with reference X was found but does not provide any platform

  Both engines here avoid that:
    buildx -- inspects the source index, resolves the single
              <Platform> child manifest by digest, and copies ONLY that
              child. The attestation entry is never referenced.
    crane  -- streams blobs registry-to-registry and honours --platform
              to copy exactly one architecture.

  Auth: both engines reuse Docker's credential store
  (~/.docker/config.json), so the standard logins set up credentials:
    docker login ghcr.io
    docker login docker.io   # for acryldata/* and a few others
    docker login quay.io     # for keycloak
    docker login artifactory.mycorp.com

  Destination naming: registry host stripped, rest of the path
  preserved under -RepoBase:
    ghcr.io/edgy-solutions/invincible-agent/cortex-bff:latest
      -> <RepoBase>/edgy-solutions/invincible-agent/cortex-bff:latest
    docker.io/acryldata/datahub-gms:v1.6.0
      -> <RepoBase>/acryldata/datahub-gms:v1.6.0
    postgres:16  (= docker.io/library/postgres:16)
      -> <RepoBase>/library/postgres:16

.PARAMETER RepoBase
  Destination registry + path prefix. Examples:
    artifactory.mycorp.com/docker-cortex
    cbm-containers-dev-and.artifactory-and.rmd.ray.com
  Trailing slashes get trimmed.

.PARAMETER Method
  Copy engine: 'buildx' (default, no install) or 'crane'.

.PARAMETER Platform
  Architecture to copy. Default linux/amd64 (the typical enterprise
  destination). The invincible-agent + cortex-ui CI publishes
  linux/amd64 + linux/arm64 multi-arch images so either platform works
  as a source. Most third-party images (DataHub, Keycloak, Redpanda)
  are amd64-only — selecting linux/arm64 will fail at the upstream
  resolve step for those.

.PARAMETER IncludeExternal
  Also mirror the external dependencies (DataHub stack, OpenSearch,
  Redpanda, Keycloak, Restate, Neo4j, Weaviate, Postgres, Fuseki,
  Topaz, MinIO, Tika, ClickHouse, utilities). Omit to mirror only the
  iagent-owned images (the things that change every CI build).

.PARAMETER DryRun
  Print the commands without executing.

.EXAMPLE
  # Default: mirror only iagent-owned images (12 engines + cortex-ui + central-gateway = 14)
  .\mirror-to-artifactory.ps1 -RepoBase cbm-containers-dev-and.artifactory-and.rmd.ray.com

.EXAMPLE
  # First-time seed of a fresh Artifactory: include the external deps too
  .\mirror-to-artifactory.ps1 -RepoBase artifactory.mycorp.com/docker-cortex -IncludeExternal

.EXAMPLE
  # Test the inventory + naming without transferring bytes
  .\mirror-to-artifactory.ps1 -RepoBase artifactory.mycorp.com/docker-cortex -IncludeExternal -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$RepoBase,

    [ValidateSet('buildx','crane')]
    [string]$Method = 'buildx',

    [string]$Platform = 'linux/amd64',

    [switch]$IncludeExternal,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$RepoBase = $RepoBase.TrimEnd('/')

# -----------------------------------------------------------------------
# Prereq check for the selected engine.
# -----------------------------------------------------------------------
if ($Method -eq 'crane') {
    if (-not (Get-Command crane -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: -Method crane selected but 'crane' is not on PATH." -ForegroundColor Red
        Write-Host "Install crane, or use the default -Method buildx (no install)." -ForegroundColor Yellow
        exit 1
    }
} else {
    & docker buildx version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: 'docker buildx' is not available." -ForegroundColor Red
        Write-Host "buildx ships with Docker Desktop; update Docker Desktop if missing." -ForegroundColor Yellow
        exit 1
    }
}

# -----------------------------------------------------------------------
# Image inventory — iagent-owned (always mirrored).
#
# All :latest because CI rebuilds these on every push. If you want a
# specific SHA pinned, switch the tag in this script and in
# values-artifactory.yaml together.
# -----------------------------------------------------------------------
$IagentImages = @(
    # Engine fleet (12) — built by invincible-agent's build-containers.yml
    @{ src='ghcr.io/edgy-solutions/invincible-agent/cortex-bff:latest';            dst='edgy-solutions/invincible-agent/cortex-bff:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/dagster-server:latest';        dst='edgy-solutions/invincible-agent/dagster-server:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/dagster-control-plane:latest'; dst='edgy-solutions/invincible-agent/dagster-control-plane:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/ontology-service:latest';      dst='edgy-solutions/invincible-agent/ontology-service:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/restate-analyst:latest';       dst='edgy-solutions/invincible-agent/restate-analyst:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/langgraph-support:latest';     dst='edgy-solutions/invincible-agent/langgraph-support:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/swarms-scraper:latest';        dst='edgy-solutions/invincible-agent/swarms-scraper:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/datahub-wrapper:latest';       dst='edgy-solutions/invincible-agent/datahub-wrapper:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/neo4j-expert:latest';          dst='edgy-solutions/invincible-agent/neo4j-expert:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/presentation-agent:latest';    dst='edgy-solutions/invincible-agent/presentation-agent:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/weaviate-expert:latest';       dst='edgy-solutions/invincible-agent/weaviate-expert:latest' },
    @{ src='ghcr.io/edgy-solutions/invincible-agent/data-analyst:latest';          dst='edgy-solutions/invincible-agent/data-analyst:latest' },

    # cortex-ui (multi-arch as of cortex-ui commit 6312f31)
    @{ src='ghcr.io/edgy-solutions/cortex-ui/frontend:latest';                     dst='edgy-solutions/cortex-ui/frontend:latest' },

    # dag-tools — central gateway / aitool registration sensor
    @{ src='ghcr.io/edgy-solutions/dag-tools/central-gateway:latest';              dst='edgy-solutions/dag-tools/central-gateway:latest' }
)

# -----------------------------------------------------------------------
# Image inventory — external dependencies (only with -IncludeExternal).
#
# These are pinned to the exact tags currently running in the sandbox
# (or required by the helm charts). When you bump a chart version,
# update the corresponding entry here AND in values-artifactory.yaml.
# -----------------------------------------------------------------------
$ExternalImages = @(
    # DataHub stack (acryl-datahub chart, sandbox runs v1.6.0)
    @{ src='docker.io/acryldata/datahub-frontend-react:v1.6.0';        dst='acryldata/datahub-frontend-react:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-gms:v1.6.0';                   dst='acryldata/datahub-gms:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-mae-consumer:v1.6.0';          dst='acryldata/datahub-mae-consumer:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-mce-consumer:v1.6.0';          dst='acryldata/datahub-mce-consumer:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-upgrade:v1.6.0';               dst='acryldata/datahub-upgrade:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-elasticsearch-setup:v1.6.0';   dst='acryldata/datahub-elasticsearch-setup:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-kafka-setup:v1.2.0.1';         dst='acryldata/datahub-kafka-setup:v1.2.0.1' },
    @{ src='docker.io/acryldata/datahub-postgres-setup:v1.6.0';        dst='acryldata/datahub-postgres-setup:v1.6.0' },
    @{ src='docker.io/acryldata/datahub-system-update:v1.6.0';         dst='acryldata/datahub-system-update:v1.6.0' },

    # Backing search / streaming for DataHub. OpenSearch downgraded to
    # 2.18.0 because 3.x is incompatible with DataHub v1.6 (sandbox
    # session 2026-06-02 confirmed).
    @{ src='opensearchproject/opensearch:2.18.0';                      dst='opensearchproject/opensearch:2.18.0' },
    @{ src='docker.redpanda.com/redpandadata/redpanda:v24.3.1';        dst='redpandadata/redpanda:v24.3.1' },
    @{ src='clickhouse/clickhouse-server:24.8';                        dst='clickhouse/clickhouse-server:24.8' },

    # Identity, durable execution, ontology graph, vector store,
    # ontology triple store, FGA authorization.
    @{ src='quay.io/keycloak/keycloak:latest';                         dst='keycloak/keycloak:latest' },
    @{ src='docker.io/restatedev/restate:1.6.2';                       dst='restatedev/restate:1.6.2' },
    @{ src='neo4j:5.26.0';                                             dst='library/neo4j:5.26.0' },
    @{ src='semitechnologies/weaviate:1.27.0';                         dst='semitechnologies/weaviate:1.27.0' },
    @{ src='secoresearch/fuseki:latest';                               dst='secoresearch/fuseki:latest' },
    @{ src='ghcr.io/aserto-dev/topaz:0.33.13';                         dst='aserto-dev/topaz:0.33.13' },

    # Persistent state (deployed by the iagent chart as third-party
    # sidecars to engines that need them — clickhouse for analytics,
    # minio for object store, redis for cache).
    @{ src='postgres:16';                                              dst='library/postgres:16' },
    @{ src='redis:7-alpine';                                           dst='library/redis:7-alpine' },
    @{ src='minio/minio:latest';                                       dst='minio/minio:latest' },

    # Utility / sidecar. python is the runtime image for the
    # domain-broker pod (config-driven, not a custom CI image).
    @{ src='curlimages/curl:latest';                                   dst='curlimages/curl:latest' },
    @{ src='busybox:latest';                                           dst='library/busybox:latest' },
    @{ src='python:3.12-slim';                                         dst='library/python:3.12-slim' }
)

$Images = $IagentImages
if ($IncludeExternal) {
    $Images = $Images + $ExternalImages
}

# -----------------------------------------------------------------------
# Strip the :tag suffix from an image reference, leaving the repository.
# -----------------------------------------------------------------------
function Get-RepoOnly {
    param([string]$Ref)
    return ($Ref -replace ':[^:/]+$', '')
}

# -----------------------------------------------------------------------
# Resolve a reference to the digest we WANT the destination to point at.
# For multi-arch sources, this is the platform-specific child digest.
# For single-arch sources, it's the manifest's own digest.
# Returns $null on failure — caller treats null as "can't verify".
# -----------------------------------------------------------------------
function Resolve-DesiredDigest {
    param([string]$Ref, [string]$Platform)

    if ($Method -eq 'crane') {
        $out = & crane digest --platform $Platform $Ref 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
        return $null
    }

    # buildx path
    $plat  = $Platform -split '/'
    $os    = $plat[0]
    $arch  = $plat[1]

    $rawLines = & docker buildx imagetools inspect $Ref --raw 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $manifest = ($rawLines -join "`n") | ConvertFrom-Json

    if ($manifest.manifests) {
        $child = $manifest.manifests | Where-Object {
            $_.platform.os -eq $os -and $_.platform.architecture -eq $arch
        } | Select-Object -First 1
        if (-not $child) { return $null }
        return $child.digest
    }

    $top = & docker buildx imagetools inspect $Ref --format '{{.Manifest.Digest}}' 2>$null
    if ($LASTEXITCODE -eq 0 -and $top) {
        return $top.Trim()
    }
    return $null
}

# -----------------------------------------------------------------------
# buildx engine: inspect the source, resolve the <Platform> child by
# digest, copy ONLY that child via 'imagetools create'. Drops the
# provenance attestation (it is a different, unreferenced child).
# -----------------------------------------------------------------------
function Copy-WithBuildx {
    param([string]$Src, [string]$Dst, [string]$Platform, [string]$SrcDigest)

    if ($SrcDigest) {
        $srcByDigest = (Get-RepoOnly $Src) + '@' + $SrcDigest
        if ($DryRun) {
            Write-Host "[dry-run] docker buildx imagetools create --tag $Dst $srcByDigest" -ForegroundColor Yellow
        } else {
            & docker buildx imagetools create --tag $Dst $srcByDigest
            if ($LASTEXITCODE -ne 0) { throw "buildx create failed for $Dst" }
        }
        return
    }

    if ($DryRun) {
        Write-Host "[dry-run] docker buildx imagetools create --tag $Dst $Src" -ForegroundColor Yellow
    } else {
        & docker buildx imagetools create --tag $Dst $Src
        if ($LASTEXITCODE -ne 0) { throw "buildx create failed for $Dst" }
    }
}

# -----------------------------------------------------------------------
# crane engine: one-shot registry-to-registry copy with --platform.
# -----------------------------------------------------------------------
function Copy-WithCrane {
    param([string]$Src, [string]$Dst, [string]$Platform)
    if ($DryRun) {
        Write-Host "[dry-run] crane copy --platform $Platform $Src $Dst" -ForegroundColor Yellow
    } else {
        & crane copy --platform $Platform $Src $Dst
        if ($LASTEXITCODE -ne 0) { throw "crane copy failed for $Dst" }
    }
}

Write-Host "Mirroring $($Images.Count) images to $RepoBase" -ForegroundColor Cyan
Write-Host "Method: $Method   Platform: $Platform   IncludeExternal: $IncludeExternal" -ForegroundColor Cyan
Write-Host ""

$failed     = @()
$mirrored   = @()
$unchanged  = @()

foreach ($img in $Images) {
    $src = $img.src
    $dst = "$RepoBase/$($img.dst)"

    Write-Host "==> $src" -ForegroundColor Green
    Write-Host "    -> $dst"

    try {
        $srcDigest = Resolve-DesiredDigest -Ref $src -Platform $Platform
        if (-not $srcDigest) {
            throw "could not resolve source digest for $src (image missing / not logged in?)"
        }
        $dstDigest = Resolve-DesiredDigest -Ref $dst -Platform $Platform

        if ($dstDigest -eq $srcDigest) {
            Write-Host "    UNCHANGED: destination already at $srcDigest" -ForegroundColor DarkGray
            $unchanged += $src
            Write-Host ""
            continue
        }

        if ($dstDigest) {
            Write-Host "    UPDATE  src=$srcDigest" -ForegroundColor Yellow
            Write-Host "            dst=$dstDigest (will be replaced)" -ForegroundColor Yellow
        } else {
            Write-Host "    NEW     src=$srcDigest (destination tag absent)" -ForegroundColor Yellow
        }

        if ($Method -eq 'crane') {
            Copy-WithCrane  -Src $src -Dst $dst -Platform $Platform
        } else {
            Copy-WithBuildx -Src $src -Dst $dst -Platform $Platform -SrcDigest $srcDigest
        }
        $mirrored += $src
    } catch {
        Write-Host "    FAILED: $_" -ForegroundColor Red
        $failed += $src
    }
    Write-Host ""
}

Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host ("  unchanged : {0,3}" -f $unchanged.Count) -ForegroundColor DarkGray
Write-Host ("  mirrored  : {0,3}" -f $mirrored.Count)  -ForegroundColor Green
$failColor = if ($failed.Count -gt 0) { 'Red' } else { 'DarkGray' }
Write-Host ("  failed    : {0,3}" -f $failed.Count)    -ForegroundColor $failColor
Write-Host ""

if ($mirrored.Count -gt 0) {
    Write-Host "Newly mirrored / updated images:" -ForegroundColor Green
    $mirrored | ForEach-Object { Write-Host "  + $_" -ForegroundColor Green }
    Write-Host ""
}

if ($failed.Count -gt 0) {
    Write-Host "Failed images:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

if ($mirrored.Count -eq 0) {
    Write-Host "All images already up to date at $RepoBase -- no bytes transferred." -ForegroundColor Cyan
} else {
    Write-Host "Mirror complete: $($mirrored.Count) updated, $($unchanged.Count) skipped." -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Next step: substitute the source registries in your" -ForegroundColor White
Write-Host "values-artifactory.yaml overlay with ${RepoBase}, then helm upgrade." -ForegroundColor White
Write-Host ""
Write-Host "Re-run periodically with the default flags (no -IncludeExternal) to" -ForegroundColor White
Write-Host "pick up new CI builds of the iagent / cortex-ui images. Re-run with" -ForegroundColor White
Write-Host "-IncludeExternal when bumping chart versions for datahub, opensearch," -ForegroundColor White
Write-Host "redpanda, keycloak, etc." -ForegroundColor White
