#!/usr/bin/env bash
# Read-only baseline for the morning's prime. Establishes the BEFORE so the AFTER is measurable.
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
