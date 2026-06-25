"""Pin Engine F's capability lookup against compact-vs-full IRI drift.

This guards a **recurring** bug class: compact-form (``mesh:Foo``) and
full-IRI form (``http://invincible-agent/mesh#Foo``) being treated as
distinct strings by lookups that should treat them as the same logical
identifier. The same hazard has bitten this project at least five
boundaries:

  1. Neo4j compact-form OntologyClass duplication (test_substrate_invariants.py
     ``test_no_compact_form_for_migrated_subjects``).
  2. Storage-form duplicates in the Weaviate Predicate collection
     (Step 3 dedup guard, ``test_predicate_collection_dedup.py``).
  3. The Step 1 sweep's deletion-predicate canonicalization
     (``test_compensate_on_rescope_sweep.py::test_canonical_iri_handles_both_directions``).
  4. The sandbox seed's pre-vs-post-migration input_uri drift
     (commit 5da2da2).
  5. Engine F's ``_lookup_capability`` exact-match miss (commit cd55111
     — the bug this test is for).

Five separate instances of the same class — string-form drift between
two components that store/produce the same logical URI in different
forms. Each instance was a separate manual debug. This test pins the
specific case from #5; the standing rule it codifies is
**"any lookup that compares URIs MUST canonicalize before compare,
because compact-vs-full drift is a recurrent failure mode in this
codebase."**

When this test fires, the fix is the same shape it's been four prior
times: expand both sides to canonical full-IRI before compare, or
update the capability table to a single canonical form. The test
guards the lookup's invariant; the architectural follow-up (Hole 4 —
UI publishes the contract) is what makes the lookup unnecessary
because the contract becomes single-sourced.
"""

from __future__ import annotations

import pytest

from agent_fleet.presentation_agent.capabilities import (
    canonical_iri_for_lookup as _canonical_iri_for_lookup,
    lookup_capability as _lookup_capability,
)


# ---------------------------------------------------------------------------
# _canonical_iri_for_lookup — the helper
# ---------------------------------------------------------------------------


def test_canonical_iri_expands_mesh_compact_to_full():
    assert (
        _canonical_iri_for_lookup("mesh:DatasetAnalysisReport")
        == "http://invincible-agent/mesh#DatasetAnalysisReport"
    )


def test_canonical_iri_expands_idp_compact_to_full():
    assert (
        _canonical_iri_for_lookup("idp:Dataset")
        == "http://invincible-agent/idp#Dataset"
    )


def test_canonical_iri_is_idempotent_on_full_form():
    """Already-canonical full IRIs pass through unchanged. Without this
    property, ``compare(canonicalize(a), canonicalize(b))`` would behave
    differently depending on which side was already full — exactly the
    string-form bug the helper exists to prevent."""
    full = "http://invincible-agent/mesh#DatasetAnalysisReport"
    assert _canonical_iri_for_lookup(full) == full


def test_canonical_iri_passes_through_unknown_prefix():
    """We won't expand prefixes we don't know about. An unknown CURIE
    (``ex:Thing``) is returned verbatim so a lookup against it still
    has a stable comparison key — just not one that matches its
    hypothetical full form (which we don't know)."""
    assert _canonical_iri_for_lookup("ex:Thing") == "ex:Thing"


def test_canonical_iri_handles_empty_input():
    """Empty input maps to empty string so dict-lookup keys stay stable
    on optional / missing URIs."""
    assert _canonical_iri_for_lookup("") == ""


# ---------------------------------------------------------------------------
# _lookup_capability — the consumer
# ---------------------------------------------------------------------------


# The capability table stores ``mesh:`` compact form (presentation_agent
# main.py:127). The supervisor injects the matched predicate's output_uri,
# which the seed records in full-IRI form. So both forms MUST resolve to
# the same row. Anchoring the test on a known-present archetype
# (DatasetAnalysisReport → CHART_WIDGET) — if that mapping changes, this
# test fails loudly with the right error message rather than silently
# accepting a missing row.
_DATASET_ANALYSIS_REPORT_FULL = "http://invincible-agent/mesh#DatasetAnalysisReport"
_DATASET_ANALYSIS_REPORT_COMPACT = "mesh:DatasetAnalysisReport"


def test_lookup_resolves_compact_form():
    """Lookup against compact form returns the CHART_WIDGET capability."""
    cap = _lookup_capability(_DATASET_ANALYSIS_REPORT_COMPACT)
    assert cap is not None, "compact-form lookup returned None"
    assert cap.get("archetype") == "CHART_WIDGET"


def test_lookup_resolves_full_iri_form():
    """Lookup against full-IRI form (what the supervisor actually
    sends) returns the SAME capability. This is the specific bug
    cd55111 fixed: the supervisor injects ``http://.../mesh#Foo`` from
    the seed, but the capability table stores ``mesh:Foo`` — exact
    ``==`` missed the match, render_ui fell through to legacy
    DesignUI, and the architecturally-correct path never fired."""
    cap = _lookup_capability(_DATASET_ANALYSIS_REPORT_FULL)
    assert cap is not None, "full-IRI lookup returned None — the bug from cd55111"
    assert cap.get("archetype") == "CHART_WIDGET"


def test_compact_and_full_resolve_to_identical_capability():
    """Both forms must return the SAME row, not just both non-None.
    A capability table with two entries for the same logical
    archetype (one compact, one full) would let this pass with two
    distinct rows — that's a different bug we should also catch.
    Comparing the resolved dicts pins the identity."""
    cap_compact = _lookup_capability(_DATASET_ANALYSIS_REPORT_COMPACT)
    cap_full = _lookup_capability(_DATASET_ANALYSIS_REPORT_FULL)
    assert cap_compact is cap_full or cap_compact == cap_full, (
        "compact and full forms resolve to different capability rows — "
        "either there are duplicate rows in the table, or the "
        "canonicalization is asymmetric. Both are bugs."
    )


def test_lookup_returns_none_for_unknown_output_uri():
    """An archetype that isn't registered MUST return None so
    /render_ui knows to fall through to legacy DesignUI rather than
    pretending to dispatch to an empty match."""
    assert _lookup_capability("http://invincible-agent/mesh#NonExistentArchetype") is None
    assert _lookup_capability("mesh:NonExistentArchetype") is None
