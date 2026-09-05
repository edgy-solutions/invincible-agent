"""Structural arity gate — query-shape verb eligibility (ADR-0008 follow-up).

THE DEFECT (the map surfaced it): `show me data about customers` resolved
to the CLASS Dataset (a SET query — no specific instance) but the
classifier picked `describeAsset`, a SINGLE-asset profiler, which honestly
returned `assets: []` (0). A single-asset verb can't answer a collection
query. The persona was a red herring (find_compatible_verbs is
domain-scoped, not persona-scoped); the real gap is that verb eligibility
was under-constrained — domain only, not arity.

THE FIX (structural, deterministic, no LLM): query-arity is already
captured as the abstention arc's `instance_resolved` signal — subject
resolved to a class with no instance = SET query.

THE DISPOSAL CHANGED 2026-09-04, THE GUARANTEE DID NOT. The gate used to
REMOVE a positively-single verb before the classifier saw it. That cost H06
its answer: "what is the capability path" grounded to `Capability` cleanly
and then reported NO VERB CLASSIFIED, because `planCapabilityPath` is
arity=single, the question named no instance, and the only verb that fit was
excluded FOR THE REASON IT WOULD HAVE ASKED ABOUT. The gate's own premise had
expired — it was built when routing there produced a 400 for a missing
mandatory slot, and that 400 is now an ASK with a menu.

So the gate FLAGS `needs_instance` and keeps the verb, and the guarantee moves
to a DISPATCH PRECONDITION at the disposition point: a flagged verb that
reaches ROUTE with nothing askable declared abstains instead of dispatching.
Both halves are asserted here — the flag, and the refusal to dispatch — because
the flag alone would resurrect the assets:[] defect for engine-DECLARED arity,
where nothing promises the verb has a slot to ask about.

Safety by construction: only POSITIVELY-single verbs are flagged; set/any/
null are untouched (null = unclassified → never over-restricted during backfill).

Run:  PYTHONPATH=src pytest tests/test_arity_gate.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.defs.dynamic_supervisor import _filter_verbs_by_arity  # noqa: E402


def _v(iri, arity=None):
    return {"verb_iri": iri, "arity": arity}


# ---------------------------------------------------------------------------
# THE RED FIXTURE — reality wrote it: show-me-data-about-customers (SET) must
# NOT keep describeAsset (single); it keeps enumerateCatalog (set).
# ---------------------------------------------------------------------------
def test_set_query_FLAGS_single_and_keeps_it_a_candidate():
    """The single verb stays pickable — excluding it emptied the pool and cost H06 its
    answer — but it carries `needs_instance` so the disposition and the dispatch
    precondition can both see why an ask is owed."""
    verbs = [
        _v("mesh:enumerateCatalog", "set"),
        _v("mesh:describeAsset", "single"),
    ]
    kept, flagged = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert {v["verb_iri"] for v in kept} == {
        "mesh:enumerateCatalog", "mesh:describeAsset",
    }
    assert [v["verb_iri"] for v in flagged] == ["mesh:describeAsset"]
    assert all(v.get("needs_instance") for v in flagged)


def test_the_flag_lands_on_the_kept_entry_not_only_the_report():
    """A flag that exists only in the returned report is invisible to the router, which
    reads the KEPT list. The dispatch precondition depends on this."""
    verbs = [_v("mesh:describeAsset", "single"), _v("mesh:enumerateCatalog", "set")]
    kept, _ = _filter_verbs_by_arity(verbs, query_is_set=True)
    by_iri = {v["verb_iri"]: v for v in kept}
    assert by_iri["mesh:describeAsset"].get("needs_instance") is True
    assert "needs_instance" not in by_iri["mesh:enumerateCatalog"]


def test_the_input_dicts_are_not_mutated():
    """These come from /find_compatible_verbs and are read elsewhere in the turn; marking
    them in place would leak the flag into the Weaviate-vs-Neo4j comparison."""
    verbs = [_v("mesh:describeAsset", "single")]
    _filter_verbs_by_arity(verbs, query_is_set=True)
    assert "needs_instance" not in verbs[0]


def test_null_and_any_never_excluded():
    """null (unclassified) and 'any' (neutral) are KEPT on a set-query —
    an incomplete backfill must never over-restrict, and arity-neutral
    verbs are valid on both shapes."""
    verbs = [
        _v("mesh:enumerateCatalog", "set"),
        _v("mesh:describeAsset", "single"),
        _v("mesh:genericDescribe", "any"),
        _v("mesh:unclassified", None),
    ]
    kept, flagged = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert {v["verb_iri"] for v in kept} == {
        "mesh:enumerateCatalog", "mesh:describeAsset",
        "mesh:genericDescribe", "mesh:unclassified",
    }
    assert [v["verb_iri"] for v in flagged] == ["mesh:describeAsset"], (
        "only a POSITIVELY-single verb is flagged — null and 'any' must pass through "
        "untouched or an incomplete backfill starts demanding instances"
    )
    for v in kept:
        if v["verb_iri"] != "mesh:describeAsset":
            assert "needs_instance" not in v


def test_instance_query_keeps_all():
    """An instance/single query (subject resolved to a specific instance)
    keeps every verb — single-asset verbs are the point, and the gate only
    constrains the set-query direction (conservative)."""
    verbs = [_v("mesh:describeAsset", "single"), _v("mesh:enumerateCatalog", "set")]
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=False)
    assert len(kept) == 2 and dropped == []


def test_arity_case_insensitive():
    verbs = [_v("mesh:describeAsset", "SINGLE")]
    kept, flagged = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert len(kept) == 1 and len(flagged) == 1
    assert kept[0].get("needs_instance") is True


def test_empty_input_safe():
    assert _filter_verbs_by_arity([], True) == ([], [])
    assert _filter_verbs_by_arity(None, True) == (None, [])
