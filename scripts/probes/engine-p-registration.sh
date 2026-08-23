#!/usr/bin/env bash
# Did Engine P's twelve verbs actually register? Read-only.
#
# SIX CHECKS, STRICTLY ORDERED — each later one is meaningless unless the earlier ones hold.
#
#   1. INPUT CLASSES   idp# 6 -> 11   (Portfolio, Site, Capability, BusinessProcess, Technology)
#   2. DOMAIN TAG      PORTFOLIO_PLANNING 0 -> 5
#   3. PREDICATE ROWS  52 -> 64        (twelve verb edges)
#   4. VERBS BY NAME   12              (a count and an identity must agree)
#   5. REFUSALS        0
#   6. INCOMPLETE      0               (accepted-but-never-finished rows COUNT toward 3)
#
# Contract D (ADR-0019) refuses a verb edge whose INPUT class does not pre-exist as an
# :OntologyClass. Measured 2026-08-22: all twelve registrations were refused 422 naming
# exactly those five URIs while the engine served /health normally. Re-registering before the
# classes land does not fail differently — it re-earns the same refusal, healthily.
#
# Baselines are MEASURED (2026-08-22, pre-prime), not assumed.
set -uo pipefail

CS="kubectl exec -n sandbox iagent-neo4j-0 -- cypher-shell -u neo4j -p changeme-neo4j-sandbox --format plain"

# ── AN INSTRUMENT THAT ERRORS MUST NOT REPORT A COUNT ────────────────────────────────────
#
# This probe printed "0 planning verbs" against 64 correctly-registered rows, because the
# query named a Weaviate field (`verb`) that does not exist: GraphQL returned an error body,
# `grep -c` counted zero matching lines, and zero was printed as though it were a measurement.
#
# ZERO-BECAUSE-FAILED and ZERO-BECAUSE-EMPTY have OPPOSITE repairs — a broken query versus a
# real absence — and collapsing them is what let a lying instrument survive being read. This
# is the provider-empty split applied to probes.
#
# THE FIRST FIX WAS NOT ENOUGH, and that is worth keeping. Making `wv` return 1 and warn on
# stderr still left `wv ... | grep -c` printing 0 on stdout: the warning and the lie went to
# different streams and the lie was the one that looked like the answer. A non-zero exit does
# not stop a pipeline that has already started. So counts are NEVER computed inside a pipe
# from `wv` — the body is captured first, the failure is checked, and only then is anything
# counted. `count_or_unknown` is the only sanctioned way to turn a query into a number.
wv() {
  local out
  out=$(kubectl run "wvprobe-$RANDOM" --rm -i --restart=Never -n sandbox \
    --image=curlimages/curl:latest --quiet -- \
    sh -c "curl -s -X POST http://iagent-weaviate:8080/v1/graphql -H 'Content-Type: application/json' -d '{\"query\":\"$1\"}'" 2>/dev/null)

  if [ -z "$out" ]; then
    echo "EMPTY RESPONSE — the query did not reach Weaviate" >&2
    return 1
  fi
  if printf '%s' "$out" | grep -q '"errors"'; then
    printf 'GRAPHQL ERROR: %s\n' "$(printf '%s' "$out" | head -c 300)" >&2
    return 1
  fi
  printf '%s' "$out"
}

# count_or_unknown <label> <query> <grep-pattern> [filter]
# Prints "<label>: N" on success, or "<label>: UNKNOWN (query failed)" — never a bare number
# for a query that did not run.
count_or_unknown() {
  local label="$1" query="$2" pattern="$3" filter="${4:-}"
  local body n
  if ! body=$(wv "$query"); then
    echo "  ${label}: UNKNOWN — query failed, NOT zero"
    return 1
  fi
  if [ -n "$filter" ]; then
    n=$(printf '%s' "$body" | grep -o "$pattern" | grep -ci "$filter")
  else
    n=$(printf '%s' "$body" | grep -oc "$pattern")
  fi
  echo "  ${label}: ${n}"
}

echo "=== 1. Engine P input classes (expect 5 of 5) ==="
$CS "MATCH (c:OntologyClass) WHERE c.uri IN [
  'http://invincible-agent/idp#Portfolio','http://invincible-agent/idp#Site',
  'http://invincible-agent/idp#Capability','http://invincible-agent/idp#BusinessProcess',
  'http://invincible-agent/idp#Technology'] RETURN count(c) AS input_classes;" 2>/dev/null | tail -2

echo
echo "=== 2. PORTFOLIO_PLANNING domain tag (expect 5) ==="
# The domain is what the RESOLVER queries with. A class that lands with the wrong domain is
# present and unroutable, which reads as "declared" to every check that only counts classes.
$CS "MATCH (c:OntologyClass) WHERE c.domain='PORTFOLIO_PLANNING' RETURN count(c) AS tagged;" 2>/dev/null | tail -2

echo
echo "=== 3. Predicate rows (expect 64) ==="
if body=$(wv '{ Aggregate { Predicate { meta { count } } } }'); then
  printf '%s' "$body" | grep -o '"count":[0-9]*' | head -1 | sed 's/^/  /'
else
  echo "  rows: UNKNOWN — query failed, NOT zero"
fi

echo
echo "=== 4. Engine P verbs present BY NAME (expect 12) ==="
# COUNTING ROWS IS NOT ENOUGH — 64 could be reached by twelve rows from anywhere. This check
# exists to DISAGREE with check 3, and that disagreement is what caught the broken field.
# The property is `verb_iri`; `verb` does not exist.
if body=$(wv '{ Get { Predicate(limit:300){ verb_iri } } }'); then
  printf '%s' "$body" | grep -o '"verb_iri":"[^"]*"' | grep -i plan | sort | sed 's/^/    /'
fi
count_or_unknown "planning verbs" '{ Get { Predicate(limit:300){ verb_iri } } }' '"verb_iri":"[^"]*"' 'plan'

echo
echo "=== 5. Rows accepted but never completed (expect 0) ==="
# registration_complete=false is a row that was ACCEPTED and then not finished. It COUNTS
# toward check 3, so a clean row total can hide it.
count_or_unknown "incomplete rows" '{ Get { Predicate(limit:300){ registration_complete } } }' '"registration_complete":false'

echo
echo "=== 6. Registration refusals in the engine log (expect NONE) ==="
POD=$(kubectl get pods -n sandbox --no-headers 2>/dev/null | grep engine-p | grep Running | awk '{print $1}' | head -1)
if [ -n "$POD" ]; then
  n=$(kubectl logs "$POD" -n sandbox --tail=200 2>/dev/null | grep -c "UNREGISTERED")
  echo "  pod=$POD  UNREGISTERED lines=$n  (expect 0)"
else
  echo "  NO RUNNING engine-p POD — every number above is about a fleet without it."
fi
