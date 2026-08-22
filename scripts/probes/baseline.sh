#!/usr/bin/env bash
# Read-only baseline for the prime. Establishes the BEFORE so the AFTER is measurable.
#
# TWO PREDICTIONS, DIFFERENT SUBSTRATES, STRICTLY ORDERED. They were briefly confused for one
# number; they are not, and both are falsifiable:
#
#   1. PRIME       -> mesh# OntologyClass NODES IN NEO4J:  29 -> 49
#                     (20 new declarations: 12 planning output types + 4 review archetypes +
#                      PeriodSeries, ThresholdGrid, MatrixGrid, DeltaSet)
#   2. RE-REGISTER -> cortex registration ROWS IN WEAVIATE: 44 -> 48, zero refusals
#                     (the four previously-refused review archetypes landing)
#
# The second is MEANINGLESS UNTIL THE FIRST HOLDS — Contract D refuses a rendersAs triple whose
# object end does not pre-exist, so re-registering before the prime just re-earns the refusal.
# Run this script after EACH step.
set -uo pipefail
CS="kubectl exec -n sandbox iagent-neo4j-0 -- cypher-shell -u neo4j -p changeme-neo4j-sandbox --format plain"

echo "=== mesh# OntologyClass nodes currently in Neo4j ==="
$CS "MATCH (c:OntologyClass) WHERE c.uri STARTS WITH 'http://invincible-agent/mesh#' RETURN count(c) AS mesh_classes;" 2>/dev/null | tail -2

echo
echo "=== which of the 20 NEW declarations are already present? (expect ZERO — TTLs are inert) ==="
$CS "
WITH [
 'PeriodCostSeries','FundingGapSet','LoadThresholdGrid','ConstraintViolationSet','MaturityMatrix',
 'ContributionSequence','PlateauTimeline','FootprintSet','IntervalSchedule','ChangeLog',
 'EffectSet','CoverageGapSet',
 'PeriodSeries','ThresholdGrid','MatrixGrid','DeltaSet',
 'GroupedReview','ApprovalTask','WorkflowObservation','InstancesByProperty'
] AS want
UNWIND want AS w
OPTIONAL MATCH (c:OntologyClass {uri: 'http://invincible-agent/mesh#' + w})
RETURN sum(CASE WHEN c IS NULL THEN 0 ELSE 1 END) AS already_present, count(*) AS expected_total;
" 2>/dev/null | tail -2

echo
echo "=== the four review archetypes specifically (B was blocked on these) ==="
$CS "
WITH ['GroupedReview','ApprovalTask','WorkflowObservation','InstancesByProperty'] AS want
UNWIND want AS w
OPTIONAL MATCH (c:OntologyClass {uri: 'http://invincible-agent/mesh#' + w})
RETURN w AS archetype, CASE WHEN c IS NULL THEN 'ABSENT' ELSE 'present' END AS state
ORDER BY archetype;
" 2>/dev/null | tail -6
