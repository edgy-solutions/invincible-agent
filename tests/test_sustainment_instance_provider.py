"""pcn resolveInstance provider candidate-producer sealed deterministically.

The SPARQL executor is injected, so matching is tested against live-shaped rows (the real IPCN25300X
notice + its ON-Semi parts) without a Jena — exact MPN/notice resolution, descriptor-wrapped
identifiers, and honest abstain.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_sustainment_instance_provider.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_EO = _REPO / "agent_fleet" / "ontology_service"
for p in (str(_EO), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.ontology_service.sustainment_instance_provider import resolve_sustainment_candidates  # noqa: E402

# Live-shaped rows (from the ingested IPCN25300X notice + its parts).
_ROWS = [
    {"s": "http://internal/sustainment/doc/IPCN25300X", "type": "http://internal/sustainment/pcn#ProcessChangeNotification"},
    {"s": "http://internal/components/NSR01L30NXT5G", "type": "http://internal/sustainment/pcn#Component"},
    {"s": "http://internal/components/NSR01F30NXT5G", "type": "http://internal/sustainment/pcn#Component"},
]




def test_exact_mpn_resolves_to_its_component_node():
    cands = resolve_sustainment_candidates("NSR01L30NXT5G", rows=_ROWS)
    assert cands[0]["instance_id"] == "http://internal/components/NSR01L30NXT5G"
    assert cands[0]["class_uri"].endswith("#Component") and cands[0]["score"] == 1.0


def test_descriptor_wrapped_mpn_resolves():
    """'the part NSR01L30NXT5G' -> strip prose -> exact MPN."""
    cands = resolve_sustainment_candidates("the part NSR01L30NXT5G", rows=_ROWS)
    assert cands[0]["label"] == "NSR01L30NXT5G" and cands[0]["score"] == 1.0


def test_exact_notice_resolves_to_its_typed_node():
    cands = resolve_sustainment_candidates("IPCN25300X", rows=_ROWS)
    assert cands[0]["instance_id"].endswith("/doc/IPCN25300X")
    assert cands[0]["class_uri"].endswith("#ProcessChangeNotification") and cands[0]["score"] == 1.0


def test_pcn_prefixed_notice_keeps_the_fragment_and_resolves():
    """'PCN IPCN25300X' — 'PCN' is an identifier fragment (not stripped); the id still resolves."""
    cands = resolve_sustainment_candidates("PCN IPCN25300X", rows=_ROWS)
    assert cands and cands[0]["label"] == "IPCN25300X" and cands[0]["score"] >= 0.9


def test_unknown_identifier_abstains():
    assert resolve_sustainment_candidates("SOME_OTHER_PART_9999", rows=_ROWS) == []


def test_lone_descriptor_abstains():
    """'notice' strips to nothing and matches nothing — honest abstain, never a least-bad match."""
    assert resolve_sustainment_candidates("notice", rows=_ROWS) == []


def test_candidates_sorted_best_first():
    cands = resolve_sustainment_candidates("NSR01", rows=_ROWS, floor=0.1)  # fuzzy, multiple
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
