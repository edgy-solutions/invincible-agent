"""B-2 substrate sibling — every :DataModule in Neo4j carries a canonical DMC.

Pairs with [test_b3_canonicalizer_drift.py](test_b3_canonicalizer_drift.py)
to close the B-2 gap surfaced by the 2026-06-17 guard-sibling audit
(see [GUARD_SIBLING_AUDIT.md](GUARD_SIBLING_AUDIT.md) §B-2):

| Layer | Property | Existing guard | What this guard adds |
|---|---|---|---|
| Source | Two `dmc_canonicalizer.py` copies (agent_fleet + doc-tools) are byte-identical | `test_dmc_canonicalizer_copies_are_byte_identical` | — |
| Substrate | Every `:DataModule` instance's stored `dmc` IS already the canonical form | **THIS GUARD** | catches a write-path that bypassed the canonicalizer, OR a canonicalizer change that left old data un-renormalized |

Same shape as the legacy-DNS class:
- Source check enforces "the two implementations agree right now."
- Substrate check enforces "the data on disk reflects the current
  implementation's canonical form."

Without the substrate check, a divergence between writes and the current
canonicalizer would silently produce :DataModule rows with non-canonical
`dmc` values that Engine E's `/resolve_dmc` (which canonicalizes its
INPUT before MATCH) would never find — reproducing the same
`n_candidates=0`-when-it-should-match failure shape that
49a3fdb (B2 DMC string-form fix) closed at the write layer. The source
guard's byte-identical check would PASS while substrate carries the
residue.

Run requires Neo4j credentials. Defaults are sandbox values; CI sets via
env.

    pytest tests/routing/test_dmc_substrate_canonical.py

Skips cleanly when:
- the `neo4j` driver isn't installed (CI without runtime deps),
- Neo4j is unreachable (transport failure ≠ green per the standing
  baseline-regression-gate rule),
- there are zero `:DataModule` rows (corpus not ingested yet — the
  invariant is vacuously held; a positive control on a known-good
  test DMC could be added later, but absence of data is NOT a regression).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

try:
    from neo4j import GraphDatabase
except ImportError:
    pytest.skip("neo4j driver not installed", allow_module_level=True)

# Import the canonicalizer from the agent_fleet copy. The source-side
# byte-identical guard ensures this is identical to the doc-tools copy;
# importing either one is correct.
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
try:
    from agent_fleet.utils.dmc_canonicalizer import canonicalize_dmc
except ImportError as e:  # pragma: no cover - environmental
    pytest.skip(
        f"agent_fleet.utils.dmc_canonicalizer not importable: {e}",
        allow_module_level=True,
    )


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")


@pytest.fixture(scope="module")
def driver():
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        drv.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j unreachable at {NEO4J_URI}: {e}")
    yield drv
    drv.close()


def test_every_datamodule_dmc_is_canonical(driver):
    """Every `:DataModule` node in the substrate stores its `dmc` in the
    canonical form.

    Pass condition: for every (:DataModule) node, the stored `dmc`
    property equals `canonicalize_dmc(stored_dmc)`. This is the
    idempotency-of-canonicalization check applied at the substrate
    layer.

    Failure modes this catches (each a real, observed-once class of
    bug):

    1. A NEW write path is introduced that bypasses the shared
       canonicalizer (e.g., a hot-fix Cypher MERGE that took the raw
       DMC string from a parser without normalizing). The substrate
       acquires a row whose `dmc` is uppercase-but-prefixed, or
       lowercase, or DMC-prefixed. Engine E's `/resolve_dmc` canonicalizes
       its input, so subsequent lookups land 0 candidates — n_candidates=0
       when it should match, the exact 49a3fdb failure shape.

    2. The canonicalizer is INTENTIONALLY changed (e.g., to allow a new
       MIC pattern). Existing rows written under the old canonical form
       become stale. Same `n_candidates=0` symptom for the affected
       MICs.

    3. A SQL-level edit or one-off migration writes a DMC directly.
       Same symptom class.

    The substrate is the single source of truth post-write; this guard
    asserts the property an `_input_uri`-style ingest contract assumes
    is universally upheld.

    Skips when:
    - corpus is unseeded (0 :DataModule rows). The invariant is
      vacuously held; a positive-control test on a known-good seeded
      DMC could be added later but is out of scope here.
    - the `dmc` property is missing on some/all nodes (schema bug at
      write time — not the failure mode this guard names). The query
      filters them OUT rather than failing here.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dm:DataModule)
            WHERE dm.dmc IS NOT NULL
            RETURN dm.dmc AS stored_dmc, dm.uri AS uri
            """
        )
        rows = [(rec["stored_dmc"], rec["uri"]) for rec in result]

    if not rows:
        pytest.skip(
            "No :DataModule rows with a `dmc` property in substrate. "
            "Either the corpus isn't ingested in this environment or "
            "the property is absent. Either way this guard has nothing "
            "to verify; not a regression. Run after B2 corpus ingest."
        )

    violations: list[tuple[str, str, str]] = []
    for stored_dmc, uri in rows:
        canonical = canonicalize_dmc(stored_dmc)
        if canonical is None:
            # The stored value isn't recognizable as a DMC AT ALL.
            # That's a substrate residue / write-path bug worth surfacing.
            violations.append((uri or "<no-uri>", stored_dmc, "<not-a-dmc>"))
            continue
        if canonical != stored_dmc:
            violations.append((uri or "<no-uri>", stored_dmc, canonical))

    assert not violations, (
        f"DMC canonical-form drift in substrate ({len(violations)} "
        f"violations out of {len(rows)} :DataModule rows).\n"
        f"\n"
        f"Each row's stored `dmc` was NOT equal to its canonicalized "
        f"form. The source-side byte-identical guard "
        f"(test_b3_canonicalizer_drift.py) only catches divergence "
        f"between the two python copies; this substrate-side guard "
        f"catches divergence between the canonicalizer and the data "
        f"on disk — exactly the 49a3fdb (n_candidates=0-when-it-"
        f"should-match) failure shape, but at a layer the source "
        f"guard cannot see.\n"
        f"\n"
        f"First 10 violations (uri, stored, expected-canonical):\n"
        + "\n".join(
            f"  {uri}\n    stored:   {stored}\n    expected: {expected}"
            for uri, stored, expected in violations[:10]
        )
        + (
            f"\n  ... and {len(violations) - 10} more"
            if len(violations) > 10
            else ""
        )
        + f"\n\nDiagnose: identify the write path that produced the "
        f"residue (grep for direct :DataModule MERGE/SET that bypass "
        f"canonicalize_dmc), fix it to route through the shared "
        f"canonicalizer, then re-canonicalize the affected rows."
    )
