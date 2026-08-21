#!/usr/bin/env bash
# Sandbox helm upgrade with EVERY values file baked in — omitting one is impossible.
#
# WHY THIS EXISTS. The sandbox release is rendered from TWO overlays, and which values a render
# receives has now twice been decided by what someone typed:
#
#   * A Langfuse audit was rendered WITHOUT values-sandbox.secret.yaml and reported a false
#     positive — a finding published about configuration that did not exist.
#   * Release rev 65 wedged on `invalid_grant` because the admin password it received was not
#     the one the database holds.
#
# Same class as `uv sync --frozen` and `pytest | tail`: a step whose correctness depends on a
# human remembering a flag. Twice-bitten makes the fix STRUCTURAL — the file list lives here,
# in version control, and every render gets all of it.
#
#   usage: scripts/upgrade-sandbox.sh [extra helm args...]
#          scripts/upgrade-sandbox.sh --dry-run
#
# NOTE ON `--reuse-values`: deliberately NOT used. It merges the PREVIOUS release's values with
# the new ones, so a value removed from a file survives in the release — which is precisely how
# a stale declaration outlives the commit that deleted it. Every render is computed from the
# files as they are now.
set -euo pipefail

RELEASE="${RELEASE:-iagent}"
NAMESPACE="${NAMESPACE:-sandbox}"
CHART="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/helm/invincible-agent"

VALUES=(
  "${CHART}/values-sandbox.yaml"
  "${CHART}/values-sandbox.secret.yaml"   # untracked: real credentials, incl. the keycloak admin password
)

ARGS=()
for f in "${VALUES[@]}"; do
  if [ ! -f "$f" ]; then
    # A MISSING OVERLAY IS A HARD STOP, never a silent skip. Skipping is what produced the false
    # audit and the wedged release: the render succeeds and is quietly built from partial input.
    echo "ERROR: required values file missing: $f" >&2
    case "$f" in
      *secret*) echo "       This file is gitignored and holds real credentials. Obtain it from" >&2
                echo "       the operator; do NOT proceed without it — the render would fall back" >&2
                echo "       to declared defaults and can wedge the release." >&2 ;;
    esac
    exit 1
  fi
  ARGS+=( -f "$f" )
done

echo "helm upgrade ${RELEASE} -n ${NAMESPACE}"
for f in "${VALUES[@]}"; do echo "  -f ${f##*/}"; done

# primeSubstrate.waitForIngest makes the prime hook BLOCK until every ontology
# ingest finishes, so the upgrade outlives helm's 5m default by a wide margin.
# The arm64 sandbox serializes those runs and a full chain has been observed
# past 30 minutes. Anything passed in "$@" comes after and therefore wins.
HELM_TIMEOUT="${HELM_TIMEOUT:-40m}"
exec helm upgrade "${RELEASE}" "${CHART}" -n "${NAMESPACE}" "${ARGS[@]}"      --timeout "${HELM_TIMEOUT}" "$@"
