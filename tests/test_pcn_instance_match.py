"""pcn resolveInstance matcher sealed deterministically (PCN/PDN, ADR-0031 ladder).

Pins the banked admission decision (docs/plans/pcn-pdn-bulk-resolve.md §6a): notice/part are
descriptors (strippable prose), pcn/pdn/ptn are identifier fragments (never stripped), and the
deterministic IRIs land on the REAL live instances (verified against the ingested IPCN25300X notice
and its ON-Semi parts).

Run:  cd agent_fleet/ontology_service && uv run --frozen --with pytest pytest ../../tests/test_pcn_instance_match.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_EO = _REPO / "agent_fleet" / "ontology_service"
for p in (str(_EO), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.ontology_service.pcn_instance_match import (  # noqa: E402
    _PCN_DESCRIPTOR_TOKENS, strip_descriptor_tokens, name_score,
    component_iri, notice_iri,
)


# ---------------------------------------------------------------------------
# The admission rule — pcn/pdn are NOT descriptors (the banked trap)
# ---------------------------------------------------------------------------

def test_pcn_pdn_ptn_are_not_descriptors():
    """The whole point: they look like entity-type nouns but are identifier fragments."""
    for frag in ("pcn", "pdn", "ptn"):
        assert frag not in _PCN_DESCRIPTOR_TOKENS
    # while the genuine descriptors ARE in the set
    for desc in ("notice", "part", "component", "the", "for"):
        assert desc in _PCN_DESCRIPTOR_TOKENS


def test_strip_keeps_the_notice_type_prefix():
    """"PCN 23_0120" -> "PCN 23_0120": stripping the type prefix would turn a resolvable id into a
    bare ambiguous number. This is the trap the frozen-set admission rule exists to avoid."""
    assert strip_descriptor_tokens("PCN 23_0120") == "PCN 23_0120"
    assert strip_descriptor_tokens("the PDN for 23_0120") == "PDN 23_0120"


def test_strip_removes_prose_around_the_identifier():
    assert strip_descriptor_tokens("the discontinuation notice for NSR01L30NXT5G") == "discontinuation NSR01L30NXT5G"
    assert strip_descriptor_tokens("part NSR01L30NXT5G") == "NSR01L30NXT5G"


def test_strip_never_touches_an_mpn_verbatim():
    """MPNs carry '#', slashes, dashes — they are identifiers, never normalized."""
    for mpn in ("LTC6226HDC#TRMPBF", "BYVB32-200-E3/81", "090-44310-31"):
        assert strip_descriptor_tokens(mpn) == mpn


# ---------------------------------------------------------------------------
# Deterministic exact-match IRIs — land on the REAL live nodes
# ---------------------------------------------------------------------------

def test_component_iri_matches_live_instance():
    # Verified live: <http://internal/components/NSR01L30NXT5G> exists in SUSTAINMENT_INSTANCES.
    assert component_iri("NSR01L30NXT5G") == "http://internal/components/NSR01L30NXT5G"


def test_notice_iri_matches_live_instance():
    # Verified live: <http://internal/sustainment/doc/IPCN25300X> is the ingested ProcessChangeNotification.
    assert notice_iri("IPCN25300X") == "http://internal/sustainment/doc/IPCN25300X"


def test_iri_construction_matches_doc_tools_transforms():
    """Spaces -> '_' (both), quotes dropped (notice) — must equal SustainmentPlugin's safe_* forms."""
    assert notice_iri('PCN 23_0120') == "http://internal/sustainment/doc/PCN_23_0120"
    assert notice_iri('PDN "X 1"') == "http://internal/sustainment/doc/PDN_X_1"
    assert component_iri("A B C") == "http://internal/components/A_B_C"


# ---------------------------------------------------------------------------
# name_score — honest scores, descriptor words don't win
# ---------------------------------------------------------------------------

def test_exact_mpn_scores_one():
    assert name_score("NSR01L30NXT5G", "NSR01L30NXT5G") == 1.0
    assert name_score("nsr01l30nxt5g", "NSR01L30NXT5G") == 1.0  # case-insensitive


def test_mpn_as_contiguous_subrun_scores_high():
    assert name_score("PDN 23_0120", "23_0120") == 0.9  # the id inside the wrapped phrase


def test_lone_descriptor_gets_no_boost():
    """"notice" must not score 0.9 against "discontinuation notice" — it would tie the real hit and
    force an abstain. It falls through to the low fuzzy ratio."""
    assert name_score("notice", "discontinuation notice") < 0.9


def test_empty_scores_zero():
    assert name_score("", "NSR01L30NXT5G") == 0.0
    assert name_score("NSR01L30NXT5G", "") == 0.0
