#!/usr/bin/env bash
# Did Engine P's twelve verbs actually register? Read-only.
#
# THREE NUMBERS, STRICTLY ORDERED — the third is meaningless unless the second holds.
#
#   1. INPUT CLASSES   idp# 6 -> 11   (Portfolio, Site, Capability, BusinessProcess, Technology)
#   2. DOMAIN TAG      PORTFOLIO_PLANNING 0 -> 5
#   3. PREDICATE ROWS  52 -> 64        (twelve verb edges)
#
# Contract D (ADR-0019) refuses a verb edge whose INPUT class does not pre-exist as an
# :OntologyClass. Measured 2026-08-22: all twelve registrations were refused 422 naming
# exactly those five URIs, while the engine served /health normally the entire time. So
# re-registering before the classes land does not fail differently — it re-earns the same
# refusal, and the engine still looks healthy.
#
# Baselines above are MEASURED (2026-08-22, pre-prime), not assumed.
set -uo pipefail

CS="kubectl exec -n sandbox iagent-neo4j-0 -- cypher-shell -u neo4j -p changeme-neo4j-sandbox --format plain"

# Weaviate has no in-cluster CLI, so every query is a throwaway curl pod.
# NO `eval`, and the query arrives as a positional arg: the payload is already three quoting
# levels deep, and routing it through eval ate it silently — checks 3 and 4 returned empty
# while 1, 2 and 5 reported correctly. A probe that is partly right is worse than one that
# is plainly broken, because the working half lends the broken half credibility.
wv() {
  kubectl run "wvprobe-$RANDOM" --rm -i --restart=Never -n sandbox \
    --image=curlimages/curl:latest --quiet -- \
    sh -c "curl -s -X POST http://iagent-weaviate:8080/v1/graphql -H 'Content-Type: application/json' -d '{\"query\":\"$1\"}'" 2>/dev/null
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
wv '{ Aggregate { Predicate { meta { count } } } }' | grep -o '"count":[0-9]*' | head -1

echo
echo "=== 4. Engine P verbs present BY NAME (expect 12) ==="
# COUNTING ROWS IS NOT ENOUGH — 64 could be reached by twelve rows from anywhere. Filtering
# client-side rather than with a GraphQL `where` keeps the quoting sane AND leaves an
# unexpected verb name visible instead of filtered away.
wv '{ Get { Predicate(limit:300){ verb } } }' \
  | grep -o '"verb":"[^"]*"' | grep -i plan | sort | sed 's/^/    /'
wv '{ Get { Predicate(limit:300){ verb } } }' \
  | grep -o '"verb":"[^"]*"' | grep -ci plan | sed 's/^/  planning verbs: /'

echo
echo "=== 5. Registration refusals in the engine log (expect NONE) ==="
POD=$(kubectl get pods -n sandbox --no-headers 2>/dev/null | grep engine-p | grep Running | awk '{print $1}' | head -1)
if [ -n "$POD" ]; then
  n=$(kubectl logs "$POD" -n sandbox --tail=200 2>/dev/null | grep -c "UNREGISTERED")
  echo "  pod=$POD  UNREGISTERED lines=$n  (expect 0)"
else
  echo "  NO RUNNING engine-p POD — every number above is about a fleet without it."
fi
