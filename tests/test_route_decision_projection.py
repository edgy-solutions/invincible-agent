"""Render-seam projection — subtask_routing_decision → RouteDecision.

The decision-path visualizer (Part 1) is a READ-SIDE view over Part 0's
capture. "Render only what was captured" has a precondition that is easy
to miss: the capture must actually REACH the renderer.
``_project_route_decision`` is that seam (Dagster asset metadata → the
typed event cortex-ui consumes). Two gaps this file pins, both red-first:

1. **fallback_reason DISCARD.** The supervisor captures a STRUCTURED
   reason — the closed enum ``subject_unknown | instance_not_found |
   no_compatible_verbs | domain_scope_excluded | no_verb_classified |
   infra_error``. The projection RE-DERIVED a coarser vocabulary of its
   own (``no_subject`` / ``no_predicate_matched``), flattening
   ``instance_not_found`` → ``no_subject`` and ``domain_scope_excluded``
   → ``no_compatible_verbs``. A [[resolution-discard-pattern]] instance
   at the render boundary: the authoritative reason computed upstream,
   thrown away and re-guessed downstream. The visualizer would render the
   WRONG abstention reason (or lose the distinct one entirely) — exactly
   the two reasons the abstention arc and the PII-exploit made structural.

2. **LOSERS DROPPED.** ``subject_candidates`` (the resolver pool — winner
   AND losers with scores) is captured but never carried into the
   projection, so "losers first-class" is impossible in the UI.

Both are "make the capture reach the boundary." Hermetic: builds the
Dagster materialization shape, calls the pure projection. No cluster.

Run:  PYTHONPATH=src pytest tests/test_route_decision_projection.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.gateway import _project_route_decision  # noqa: E402


def _mat(**fields) -> dict:
    """Build a Dagster materialization dict from label→value, choosing
    each entry's shape by Python type (mirrors _metadata_dict's reader).
    bool is checked before int because bool is an int subclass."""
    entries = []
    for label, value in fields.items():
        if isinstance(value, bool):
            entries.append({"label": label, "boolValue": value})
        elif isinstance(value, float):
            entries.append({"label": label, "floatValue": value})
        elif isinstance(value, int):
            entries.append({"label": label, "intValue": value})
        else:
            entries.append({"label": label, "text": str(value)})
    return {"metadataEntries": entries}


# The resolver pool a losers-first-class view needs: winner + the
# candidates it beat, each with a score.
_CANDIDATE_POOL = [
    {"uri": "http://invincible-agent/idp#Table", "label": "Table", "score": 0.81},
    {"uri": "http://www.w3.org/ns/prov#Bundle", "label": "Bundle", "score": 0.66},
    {"uri": "http://invincible-agent/idp#Column", "label": "Column", "score": 0.60},
]


# ---------------------------------------------------------------------------
# GAP 1 — the structured fallback_reason must pass through, NOT be
# re-derived. These are the two reasons the abstention arc + PII exploit
# made structural; the visualizer must render them distinctly.
# ---------------------------------------------------------------------------
def test_instance_not_found_reason_passes_through():
    """A foo.bar.zzz_nope-class query: the supervisor captured
    fallback_reason=instance_not_found. The projection must carry THAT,
    not flatten it to the coarse 'no_subject' it used to re-derive from
    subject_uri==UNKNOWN."""
    mat = _mat(
        route_status="no_match",
        subject_uri="UNKNOWN",
        verb_iri="UNKNOWN",
        fallback_reason="instance_not_found",
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result["fallback"] is True
    assert result["fallback_reason"] == "instance_not_found", (
        "the structured instance_not_found reason (the honest, actionable "
        "abstention the arc made structural) must survive the render seam, "
        "not be discarded and re-guessed as 'no_subject'"
    )


def test_domain_scope_excluded_reason_passes_through():
    """The PII-exploit shape: verbs exist but the caller's entitled_domains
    excluded them all (the deny primitive's data shadow). The supervisor
    captured domain_scope_excluded; the projection must not flatten it to
    'no_compatible_verbs'."""
    mat = _mat(
        route_status="no_match",
        subject_uri="http://invincible-agent/idp#Table",
        verb_iri="UNKNOWN",
        fallback_reason="domain_scope_excluded",
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result["fallback_reason"] == "domain_scope_excluded", (
        "domain_scope_excluded is a DISTINCT fact from no_compatible_verbs "
        "(scope-exclusion vs genuine unsupportedness); the render seam must "
        "preserve the distinction the supervisor drew"
    )


@pytest.mark.parametrize("reason", [
    "subject_unknown",
    "instance_not_found",
    "no_compatible_verbs",
    "domain_scope_excluded",
    "no_verb_classified",
    "infra_error",
])
def test_all_structured_reasons_preserved(reason):
    """Every closed-enum value the supervisor can capture must round-trip
    through the projection verbatim — the render seam is not allowed its
    own private vocabulary."""
    mat = _mat(
        route_status="infra_error" if reason == "infra_error" else "no_match",
        subject_uri="UNKNOWN" if reason in ("subject_unknown", "instance_not_found") else "http://invincible-agent/idp#Table",
        verb_iri="UNKNOWN",
        fallback_reason=reason,
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result["fallback_reason"] == reason


def test_missing_structured_reason_falls_back_to_heuristic():
    """BACKWARD COMPAT: an OLD materialization written before Part 0 has no
    structured fallback_reason. The projection must still produce a
    non-empty reason (its heuristic), not crash or emit empty — new code
    reading old assets stays honest."""
    mat = _mat(
        route_status="no_match",
        subject_uri="UNKNOWN",
        verb_iri="UNKNOWN",
        # no fallback_reason entry at all
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result["fallback"] is True
    assert result["fallback_reason"], "must degrade to a heuristic reason, not empty"


# ---------------------------------------------------------------------------
# GAP 2 — the loser pool (subject_candidates) must reach the renderer.
# ---------------------------------------------------------------------------
def test_fallback_carries_subject_candidates():
    """The resolver pool (winner + losers, with scores) is captured; the
    projection must carry it so the visualizer can render losers
    first-class. Without this, 'losers first-class' is impossible in the
    UI regardless of frontend work."""
    mat = _mat(
        route_status="no_match",
        subject_uri="UNKNOWN",
        verb_iri="UNKNOWN",
        fallback_reason="instance_not_found",
        subject_candidates=json.dumps(_CANDIDATE_POOL),
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result.get("candidates") == _CANDIDATE_POOL, (
        "the captured candidate pool (with scores) must reach the render "
        "boundary so losers are first-class, not discarded"
    )


def test_specialist_carries_subject_candidates():
    """Even on a MATCHED route the pool matters — it's the candidates the
    winner beat, and the visualizer shows the contest, not just the
    winner."""
    mat = _mat(
        route_status="matched",
        subject_uri="http://invincible-agent/idp#Table",
        subject_confidence=0.81,
        verb_iri="mesh:describeAsset",
        verb_confidence=0.9,
        handler_endpoint="http://engine-d:8000/query_metadata",
        classify_called=True,
        candidate_count=3,
        subject_candidates=json.dumps(_CANDIDATE_POOL),
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result["fallback"] is False
    assert result.get("candidates") == _CANDIDATE_POOL


def test_missing_candidates_is_empty_list_not_crash():
    """An old materialization without subject_candidates must project to an
    empty pool, not crash or emit None — render-only-what-was-captured
    means an absent capture renders as 'no losers recorded', honestly."""
    mat = _mat(
        route_status="no_match",
        subject_uri="UNKNOWN",
        verb_iri="UNKNOWN",
        fallback_reason="subject_unknown",
    )
    result = _project_route_decision(mat)
    assert result is not None
    assert result.get("candidates") == []
