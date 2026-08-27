#!/usr/bin/env bash
# Open the port-forwards the test suite's integration tests expect.
#
# WHY THIS EXISTS. Enumerated 2026-08-26: the suite reported "1935 passed, 170
# skipped", and ~56 of those skips were not decisions — they were a hostname.
# Neo4j, Engine O, Weaviate and Postgres were all healthy in the cluster while
# the tests pointed at localhost and skipped themselves with an honest message
# nobody re-read.
#
# That is the LLM_BASE_URL shape again: a degraded default that looks like
# steady state because the fallback is polite. A skip is a test that has left
# the population, and nothing decided it should.
#
# Run this, then run the suite. The remaining skips are then DECISIONS —
# production surfaces that genuinely do not exist yet, a cross-repo image, and
# one deliberate env flag — which is a short list worth reading rather than a
# long one worth ignoring.
#
#   ./scripts/test-port-forwards.sh &        # or run in another terminal
#   uv run --frozen pytest tests/ -q
#
# Ctrl-C (or kill the process group) tears every forward down together.
set -euo pipefail

NS="${NS:-sandbox}"

# LOCAL:REMOTE per service. The local ports are NOT arbitrary — each is the
# literal port a test's default connection string names, so changing one here
# silently re-skips those tests. Verified against the skip messages, not guessed.
#
#   7687   bolt://localhost:7687      — most tests/routing/* (substrate invariants,
#                                        ingest guards, conjunctive read, cutover diff)
#   17687  bolt://localhost:17687     — tests/test_hop1_* use a SECOND local port for
#                                        the same service; both forwards are required
#   8084   http://localhost:8084      — Engine O (/resolve, ADR-0019 contract A)
#   8080   weaviate http              — predicate collection dedup
#   50051  weaviate grpc              — the v4 client needs BOTH or it fails init
#   15432  postgresql://...:15432     — tests/test_hop2_projector_apply
forward() {
  local svc="$1" map="$2"
  echo "  ${svc}  ${map}"
  kubectl port-forward -n "$NS" "svc/${svc}" "$map" >/dev/null 2>&1 &
}

echo "port-forwards (namespace: ${NS}):"
forward iagent-neo4j        7687:7687
forward iagent-neo4j        17687:7687
forward iagent-engine-o     8084:8084
forward iagent-weaviate     8080:8080
forward iagent-weaviate-grpc 50051:50051
forward iagent-postgresql   15432:5432

# Kill the whole group on exit, so a Ctrl-C does not leave orphans holding
# local ports — a stale forward is worse than none, because the next run
# connects to a tunnel pointing at a pod that no longer exists.
trap 'echo; echo "tearing down port-forwards"; kill 0' EXIT INT TERM

echo
echo "waiting for forwards to become ready..."
sleep 6
echo "ready. run:  uv run --frozen pytest tests/ -q"
wait
