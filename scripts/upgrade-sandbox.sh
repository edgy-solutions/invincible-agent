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
# MUST EXCEED primeSubstrate.ingestTimeout (3600s = 60m), which blocks inside this
# window. 40m was smaller than the 45-min queue and made helm the binding constraint;
# 75m leaves the inner bound room to be the thing that actually fails, which is the one
# that can say WHY. tests/test_prime_timeout_bounds_agree.py asserts the ordering.
HELM_TIMEOUT="${HELM_TIMEOUT:-75m}"

# KILLED-CLIENT TRAP. ${HELM_TIMEOUT} above protects against helm giving up early; it does
# NOT protect against something killing this process from outside — a wrapper timeout, a
# Ctrl-C, a CI step budget. Measured 2026-09-02: this script was invoked as
# `timeout 600 bash scripts/upgrade-sandbox.sh` and SIGTERMed at ten minutes against a
# 51-minute prime. THE HELM DEFAULT WAS CORRECT AND IRRELEVANT — an outer kill wins.
#
# The cost is not the lost wait. The hooks keep running in-cluster and complete, so the
# substrate looks fine, while TWO THINGS GO WRONG SILENTLY:
#   1. the release is left `pending-upgrade`, and the NEXT upgrade is refused with
#      "another operation (install/upgrade/rollback) is in progress"
#   2. every hook scheduled AFTER the long one is never CREATED — the post-prime
#      reregister job simply does not exist, so engines keep whatever registration they
#      had. The only evidence is a pod age that never changed.
#
# This trap cannot prevent any of that. It exists so the operator LEARNS IT AT THE MOMENT
# IT HAPPENS instead of at the next upgrade, days later, from a refusal message that names
# none of it.
_on_kill() {
  echo "" >&2
  echo "!! helm client KILLED (signal) — the upgrade did NOT finalize." >&2
  echo "   The in-cluster hooks are still running and will complete on their own." >&2
  echo "   TWO CONSEQUENCES, neither of which will announce itself:" >&2
  echo "     1. release ${RELEASE} is left pending-upgrade; the next upgrade will be REFUSED." >&2
  echo "        Fix: the release Secret's status field. NOT a rollback — see" >&2
  echo "        docs/plans/helm-release-stuck-pending-upgrade-97.md" >&2
  echo "     2. hooks scheduled after the long one were never created. If a prime ran, the" >&2
  echo "        post-prime reregister job does NOT exist — engines hold stale registrations" >&2
  echo "        and the tell is a pod age that never changed." >&2
  exit 143
}
trap _on_kill TERM INT
exec helm upgrade "${RELEASE}" "${CHART}" -n "${NAMESPACE}" "${ARGS[@]}"      --timeout "${HELM_TIMEOUT}" "$@"
