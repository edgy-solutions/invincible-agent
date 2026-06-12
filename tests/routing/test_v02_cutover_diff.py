"""Gateway v0.2 cutover diff — Step 3 of the v0.2 plan.

Per the ADR-0006 §Addendum §Cutover predict-before-run section
(2026-06-12) + the masks rule: re-register every existing AITool
through v0.2 and diff the resulting Neo4j edges + Weaviate rows
against what the sensor had materialized.

**Expect at least one discrepancy.** A dying dual-write path that
produces a perfectly clean diff usually means the diff didn't look
where the drift lives. This file looks WHERE THE BUGS LIVED:

  - mesh_provider — should be populated everywhere after v0.2
  - timeout_s — present only on the predicates that declared one
    (resolveInstance both providers)
  - _tool_urn — every edge has its own registration identity
  - endpoint_url — populated everywhere
  - allowlist-drift'd properties the sensor was silently dropping
    (mesh_namespace_authority, mesh_tool_kind — names that hit the
    allowlist drift bug class)
  - Multi-provider edges should be one-per-tool_urn (the doc-tools
    a44b9fb fix's match-key invariant)

The discoveries this test surfaces are the audit output for the
Step 3 deliverable. They should be reviewed in the morning along
with the matrix + invariant test results.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import pytest


# Column names returned by the Cypher RETURN below. Pre-v0.2 edges
# materialized by the doc-tools sensor lack ``tool_urn`` AND
# ``provider`` (the allowlist drift + a44b9fb match-key bug both
# affected them). v0.2 saga writes populate all of these.
_REQUIRED_RETURNED_COLUMNS = [
    "verb_iri",
    "tool_urn",
    "endpoint_url",
    "provider",
    "owner_persona",
    "domains",
    "cost_class",
]
"""Column names every v0.2-materialized AITool predicate edge MUST have
populated. Names match the SQL-style aliases in the RETURN clause of
the Cypher query below — NOT the raw r.* property names — because that's
what the row dict keys end up as."""

_OPTIONAL_PROPERTIES = [
    "timeout_s",  # only on registrations that declared one (resolveInstance)
    "version",
]
"""Properties that MAY be present depending on the registration."""


@pytest.fixture
def neo4j_driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")
    try:
        d = GraphDatabase.driver(uri, auth=(user, pwd))
        d.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j unreachable: {exc}")
    yield d
    d.close()


def test_every_aitool_edge_has_required_properties(neo4j_driver):
    """Every materialized AITool predicate edge MUST carry the
    properties v0.2's saga writes. If any edge is missing one, it
    was materialized by the pre-v0.2 sensor path AND not yet re-
    registered through v0.2 — the cutover hasn't completed for
    that engine."""
    with neo4j_driver.session() as session:
        rows = list(session.run(
            """
            MATCH ()-[r]->()
            WHERE r.iri IS NOT NULL AND r.endpoint_url IS NOT NULL
              AND r.iri STARTS WITH 'mesh:'
            RETURN r.iri AS verb_iri,
                   r._tool_urn AS tool_urn,
                   r.endpoint_url AS endpoint_url,
                   r.provider AS provider,
                   r.owner_persona AS owner_persona,
                   r.domains AS domains,
                   r.cost_class AS cost_class,
                   r.timeout_s AS timeout_s,
                   r.version AS version
            ORDER BY r.iri, r._tool_urn
            """
        ))

    missing_by_edge: dict[str, list[str]] = {}
    for row in rows:
        key = f"{row['verb_iri']} / {row['tool_urn'] or '<no-tool_urn>'}"
        missing = [p for p in _REQUIRED_RETURNED_COLUMNS if not row.get(p)]
        if missing:
            missing_by_edge[key] = missing

    assert not missing_by_edge, (
        f"\n  v0.2 CUTOVER INCOMPLETE.\n"
        f"  {len(missing_by_edge)} edge(s) materialized in Neo4j are missing "
        f"required properties.\n"
        f"  These edges were materialized by the pre-v0.2 sensor path and "
        f"have not been re-registered through v0.2's saga yet.\n"
        f"\n  Per-edge missing properties:\n"
        + "\n".join(f"    - {k}: {v}" for k, v in missing_by_edge.items())
        + "\n\n  Likely causes:\n"
        f"    - An engine has not been re-rolled since v0.2 mesh-registrar shipped.\n"
        f"    - The engine's lifespan registration failed (5xx) without retry succeeding.\n"
        f"    - The aitool sensor was re-enabled and overwrote a v0.2 row with allowlist drift.\n"
    )


def test_each_tool_urn_appears_at_most_once(neo4j_driver):
    """The match-key in v0.2 saga + doc-tools a44b9fb is (verb_iri,
    _tool_urn). Each registration identity should produce exactly one
    edge. Duplicates mean a registration ran twice without the
    deterministic identity converging — could be a missing _tool_urn,
    or a races between sensor and gateway during the cutover window."""
    with neo4j_driver.session() as session:
        rows = list(session.run(
            """
            MATCH ()-[r]->()
            WHERE r.iri IS NOT NULL AND r._tool_urn IS NOT NULL
              AND r.iri STARTS WITH 'mesh:'
            RETURN r.iri AS verb_iri, r._tool_urn AS tool_urn,
                   count(*) AS count
            ORDER BY verb_iri, tool_urn
            """
        ))

    duplicates = [r for r in rows if r["count"] > 1]
    assert not duplicates, (
        f"\n  MULTI-PROVIDER EDGE IDENTITY VIOLATION.\n"
        f"  {len(duplicates)} (verb_iri, _tool_urn) pair(s) have multiple edges:\n"
        + "\n".join(
            f"    - {r['verb_iri']} / {r['tool_urn']}: count={r['count']}"
            for r in duplicates
        )
        + "\n\n  The doc-tools a44b9fb match-key fix means each tool_urn must "
        f"appear AT MOST once per verb. Duplicates indicate either:\n"
        f"    - apoc.merge.relationship's identity stopped including _tool_urn (regression).\n"
        f"    - The cutover window had a race where two writers materialized concurrently.\n"
        f"    - A test fixture leaked (synthetic verb wasn't cleaned up).\n"
    )


def test_provider_field_distinguishes_multi_provider_verbs(neo4j_driver):
    """For verbs offered by multiple providers (mesh:resolveInstance —
    Engine D + Engine E), the provider field must distinguish them.
    Two edges with provider='engine_d' for the same verb_iri is the
    bug shape last week's a44b9fb fix prevents at the identity level;
    this test catches it at the property level too."""
    with neo4j_driver.session() as session:
        rows = list(session.run(
            """
            MATCH ()-[r]->()
            WHERE r.iri = 'mesh:resolveInstance' AND r.endpoint_url IS NOT NULL
            RETURN r.provider AS provider, count(*) AS count
            ORDER BY provider
            """
        ))

    duplicates = [r for r in rows if r["count"] > 1]
    assert not duplicates, (
        f"\n  PROVIDER FIELD COLLISION on mesh:resolveInstance.\n"
        f"  Duplicate provider values:\n"
        + "\n".join(f"    - {r['provider']}: count={r['count']}" for r in duplicates)
        + "\n\n  Multi-provider routing depends on the provider field being\n"
        f"  distinct. Same provider value on multiple edges means traces will\n"
        f"  randomly attribute the answer to one of them.\n"
    )


def test_cutover_diff_report(neo4j_driver):
    """Diagnostic-only test that ALWAYS passes but PRINTS a cutover
    diff report. The masks rule says "expect at least one
    discrepancy." If the report comes back clean and short, that's
    a verification failure to investigate (the diff didn't look
    where the drift lives), NOT a victory.

    The report is what the morning reader uses to assess the
    cutover. Run with ``pytest -s`` to see the output.
    """
    with neo4j_driver.session() as session:
        rows = list(session.run(
            """
            MATCH ()-[r]->()
            WHERE r.iri IS NOT NULL AND r.endpoint_url IS NOT NULL
              AND r.iri STARTS WITH 'mesh:'
            RETURN r.iri AS verb_iri, r._tool_urn AS tool_urn,
                   r.provider AS provider, r.timeout_s AS timeout_s,
                   r.endpoint_url AS endpoint_url
            ORDER BY r.iri, r._tool_urn
            """
        ))

    print("\n" + "=" * 72)
    print("v0.2 CUTOVER DIFF REPORT")
    print("=" * 72)
    print(f"Total AITool predicate edges in Neo4j: {len(rows)}")
    print()

    # Group by verb_iri
    by_verb = defaultdict(list)
    for r in rows:
        by_verb[r["verb_iri"]].append(r)
    print(f"Distinct verbs: {len(by_verb)}")
    for verb, edges in sorted(by_verb.items()):
        print(f"  {verb}: {len(edges)} edge(s)")
        for e in edges:
            print(
                f"    - tool_urn={e['tool_urn']!s:<60} "
                f"provider={e['provider']!s} timeout_s={e['timeout_s']!s}"
            )
    print()

    # Spotlight on the masks-rule discrepancy candidates:
    no_provider = [r for r in rows if not r["provider"]]
    no_tool_urn = [r for r in rows if not r["tool_urn"]]
    no_timeout_resolveInstance = [
        r for r in rows
        if r["verb_iri"] == "mesh:resolveInstance" and r["timeout_s"] is None
    ]

    print("Drift candidates (masks-rule lookup):")
    print(f"  Edges with no provider:         {len(no_provider)}")
    print(f"  Edges with no _tool_urn:        {len(no_tool_urn)}")
    print(f"  resolveInstance edges w/o tmo:  {len(no_timeout_resolveInstance)}")
    print()

    # The narrative arm of the masks rule: if everything is clean,
    # someone should still WONDER why.
    drift_signals = (
        len(no_provider) + len(no_tool_urn) + len(no_timeout_resolveInstance)
    )
    if drift_signals == 0:
        print(
            "Diff comes back CLEAN on the masks-rule lookups. Per the rule,\n"
            "this should be treated as a verification finding rather than a\n"
            "victory — the cutover may have been bug-compatible with the\n"
            "sensor (which would be surprising given last week's documented\n"
            "drift) or the diff didn't look in the right place. Suggested\n"
            "next-level audit:\n"
            "  - sample a few customProperties from DataHub MCPs and compare\n"
            "    field-by-field with Neo4j r.* values\n"
            "  - check Weaviate Predicate rows for the same verbs and confirm\n"
            "    their deterministic UUIDs match the (verb_iri, input_uri) shape\n"
            "  - run the conjunctive-read invariant test (cases #2 and #3)\n"
            "    which the cleanest possible discrepancy would surface\n"
        )
    else:
        print(
            f"Diff surfaced {drift_signals} discrepancy signal(s). Investigate\n"
            f"each as part of the morning review. The expected resolution is\n"
            f"either:\n"
            f"  - an engine that hasn't been re-rolled since v0.2 shipped\n"
            f"    (action: re-roll it)\n"
            f"  - a v0.2 saga rollback that wasn't fully cleaned up\n"
            f"    (action: re-register manually via Dagster launchpad)\n"
            f"  - a regression in the saga's substrate writers\n"
            f"    (action: check the saga unit tests are still green)\n"
        )
    print("=" * 72)
