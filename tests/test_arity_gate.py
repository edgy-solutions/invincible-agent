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
resolved to a class with no instance = SET query. The gate removes verbs
that positively declare arity="single" BEFORE the classifier sees them, so
a set-query never resolves to a single-asset verb. Composes with the
domain scope into (domain ∩ arity) — the eligibility intersection
enforcement extends with permission.

Safety by construction: only POSITIVELY-single verbs are dropped; set/any/
null are kept (null = unclassified → never over-excluded during backfill).

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
def test_set_query_drops_single_keeps_set():
    verbs = [
        _v("mesh:enumerateCatalog", "set"),
        _v("mesh:describeAsset", "single"),
    ]
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=True)
    kept_iris = {v["verb_iri"] for v in kept}
    assert kept_iris == {"mesh:enumerateCatalog"}, (
        "a set-query must drop the single-asset verb from candidacy so the "
        "classifier can't pick it — describeAsset was the 0-asset defect"
    )
    assert [v["verb_iri"] for v in dropped] == ["mesh:describeAsset"]


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
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert {v["verb_iri"] for v in kept} == {
        "mesh:enumerateCatalog", "mesh:genericDescribe", "mesh:unclassified",
    }
    assert [v["verb_iri"] for v in dropped] == ["mesh:describeAsset"]


def test_instance_query_keeps_all():
    """An instance/single query (subject resolved to a specific instance)
    keeps every verb — single-asset verbs are the point, and the gate only
    constrains the set-query direction (conservative)."""
    verbs = [_v("mesh:describeAsset", "single"), _v("mesh:enumerateCatalog", "set")]
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=False)
    assert len(kept) == 2 and dropped == []


def test_arity_case_insensitive():
    verbs = [_v("mesh:describeAsset", "SINGLE")]
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert kept == [] and len(dropped) == 1


def test_empty_input_safe():
    assert _filter_verbs_by_arity([], True) == ([], [])
    assert _filter_verbs_by_arity(None, True) == (None, [])
