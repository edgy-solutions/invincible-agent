"""The seeded acceptance ladder IS DoDI 5000.88 PARA 3.6.e.(1)(b)1, level for level.

**THE SIBLING OF THE TABLE III SEAL, AND IT EXISTS FOR THE SAME REASON ONE DOCUMENT ALONG.**
`test_matrix_matches_mil_std_882e_table_iii.py` pins the severity×probability table because seal 4
proved only that the engine FOLLOWS the file — and it passed green over five wrong cells. The
ladder had the identical exposure and no seal at all: the engine resolves a level to an
`acceptanceAudience`, every test agreed the resolution worked, and **nothing compared the ladder to
its source** because until 2026-09-14 there was no source to compare it to. It was attributed to
DoDI 5000.02 via 882E §4.3.7 — which defers by name and assigns nobody — and marked a FIXTURE.

**SOURCE, READ 2026-09-14:** DoDI 5000.88 PARA 3.6.e.(1)(b)1, Directives Division PDF, November 18
2020 issue. 882E §4.3.7 verbatim: "the risks shall be accepted by the appropriate authority as
defined in DoDI 5000.02" — so the matrix's citation can never cover the ladder, and the TTL records
the two under different predicates for exactly that reason.

    High         CAE (or DAE)              the Component, or Defense, Acquisition Executive
    Serious      program executive         a LEVEL, not necessarily the PEO in person
                 officer-LEVEL
    Medium       PM                        the Program Manager
    Low          PM

── WHY THE TIER IS ASSERTED AND NOT THE AUDIENCE KEY ───────────────────────────────────────────
`safety:acceptanceAudience` says which QUEUE an acceptance lands in here. `safety:acceptanceAuthorityTier`
says which OFFICE the instruction REQUIRES. A seal over the audience keys could only assert that
four strings are spelled consistently with themselves — **the fixture-that-cannot-fail, one field
short of the fact under test.** A deployment re-points an audience constantly and the tier almost
never, so collapsing them would make a legitimate tailoring indistinguishable from a transcription
error.

── AND THE DIRECTIONAL HALF, STATED SEPARATELY ─────────────────────────────────────────────────
Equality catches any difference. The directional assertion names the DANGEROUS one: a level whose
authority is MORE JUNIOR than the instruction requires. That is the direction the matrix already
drifted in — all five wrong cells were too permissive — and it is the failure with no symptom,
because the queue works, the card renders, and the wrong person signs. The two are separate
assertions because "the table changed" and "a High risk is now signable by a program manager" are
not the same report.
"""
from __future__ import annotations

import pytest

from ._engine_extra import requires_rdflib

#: DoDI 5000.88 PARA 3.6.e.(1)(b)1 — the TRANSCRIPTION, written here as the seal's own copy of the
#: instruction. Deliberately NOT read from the TTL: a seal that takes its expectation from its
#: subject agrees with any edit, including one that demotes an authority.
_INSTRUCTION = {
    "High": "CAE_OR_DAE",
    "Serious": "PEO_LEVEL",
    "Medium": "PM",
    "Low": "PM",
}

#: Seniority, 1 most senior. The instruction's own ordering of the offices it names.
_SENIORITY = {"CAE_OR_DAE": 1, "PEO_LEVEL": 2, "PM": 3}


def _ladder() -> dict:
    """level label -> (tier, authority rank), read from the primed matrix TTL."""
    import rdflib

    from agent_fleet.safety_agent import matrix

    g = rdflib.Graph()
    g.parse(str(matrix.matrix_path()), format="turtle")
    rows = g.query(
        """
        PREFIX safety: <http://internal/sustainment/safety#>
        PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?label ?tier ?rank WHERE {
            ?lvl a safety:RiskLevel ;
                 rdfs:label ?label ;
                 safety:acceptanceAuthorityTier ?tier ;
                 safety:authorityRank ?rank .
        }
        """
    )
    return {str(r.label): (str(r.tier), int(r.rank)) for r in rows}


@requires_rdflib
def test_every_risk_level_declares_a_tier_so_nothing_below_is_vacuous():
    """THE FLOOR. A level missing its tier drops silently out of a dict comparison, and the
    remaining three would still match — which is how a transcription seal passes over a ladder
    that lost its most senior rung."""
    ladder = _ladder()
    assert set(ladder) == set(_INSTRUCTION), (
        f"the TTL declares tiers for {sorted(ladder)} and the instruction names "
        f"{sorted(_INSTRUCTION)} — a level with no tier is unasserted, not compliant"
    )


@requires_rdflib
@pytest.mark.parametrize("level", sorted(_INSTRUCTION))
def test_the_tier_matches_the_instruction(level):
    """THE TRANSCRIPTION, level by level so a failure names one rather than printing a diff."""
    tier, _rank = _ladder()[level]
    assert tier == _INSTRUCTION[level], (
        f"{level} is seeded to {tier!r}; DoDI 5000.88 PARA 3.6.e.(1)(b)1 assigns "
        f"{_INSTRUCTION[level]!r}"
    )


@requires_rdflib
@pytest.mark.parametrize("level", sorted(_INSTRUCTION))
def test_NO_LEVEL_NAMES_A_MORE_JUNIOR_AUTHORITY_THAN_THE_INSTRUCTION(level):
    """THE DIRECTIONAL ASSERTION — the failure with no symptom.

    Stated separately from equality because it is the one that matters: a ladder demoted by one
    rung routes a High acceptance to a PEO or a PM, the queue works, the card renders, and the
    wrong person signs. Nothing complains, because the person who WOULD complain never sees it.
    """
    tier, _rank = _ladder()[level]
    seeded = _SENIORITY.get(tier)
    required = _SENIORITY[_INSTRUCTION[level]]
    assert seeded is not None, f"{level} names an office outside the instruction's set: {tier!r}"
    assert seeded <= required, (
        f"{level} is seeded to {tier!r}, which is MORE JUNIOR than the {_INSTRUCTION[level]!r} "
        "the instruction requires — a risk acceptance would be signed by someone the instruction "
        "does not authorise, and nothing else in this suite would say so"
    )


@requires_rdflib
def test_the_declared_rank_agrees_with_the_tier_it_sits_beside():
    """`authorityRank` is a SECOND spelling of the tier's seniority, and two spellings of one fact
    disagree eventually. The directional assertion above reads the seal's own table, so a wrong
    rank in the TTL would not break it — it would break anything else that ordered by rank, which
    is the invariant-between-declarations shape."""
    for level, (tier, rank) in _ladder().items():
        assert rank == _SENIORITY[tier], (
            f"{level}: tier {tier!r} implies rank {_SENIORITY[tier]} and the TTL declares {rank}"
        )


@requires_rdflib
def test_the_audience_key_still_matches_the_level_it_belongs_to():
    """THE CONTROL, and it is the assertion this seal REPLACES rather than the one it makes.

    Checking that `risk_acceptance_high:SUSTAINMENT` sits on High is a spelling check: it cannot
    fail while the four keys are generated from the four labels, and it says nothing about whether
    the right office holds them. Kept as a control so the tier assertions above are visibly the
    load-bearing ones — and so a key/level mismatch, which WOULD misroute, is still caught.
    """
    import rdflib

    from agent_fleet.safety_agent import matrix

    g = rdflib.Graph()
    g.parse(str(matrix.matrix_path()), format="turtle")
    rows = g.query(
        """
        PREFIX safety: <http://internal/sustainment/safety#>
        PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?label ?aud WHERE {
            ?lvl a safety:RiskLevel ; rdfs:label ?label ; safety:acceptanceAudience ?aud .
        }
        """
    )
    got = {str(r.label): str(r.aud) for r in rows}
    assert got == {
        "High": "risk_acceptance_high:SUSTAINMENT",
        "Serious": "risk_acceptance_serious:SUSTAINMENT",
        "Medium": "risk_acceptance_medium:SUSTAINMENT",
        "Low": "risk_acceptance_low:SUSTAINMENT",
    }, f"an audience key does not belong to its level: {got}"


@requires_rdflib
def test_mutation_demoting_High_to_the_PM_is_caught(tmp_path, monkeypatch):
    """THE MUTATION, RUN — and it is the exact edit the directional assertion exists for.

    Rewrites the real TTL in a copy and re-parses through the same path the seal reads by, so what
    is shown discriminating is the whole instrument rather than a patched dict.
    """
    from agent_fleet.safety_agent import matrix

    src = matrix.matrix_path().read_text(encoding="utf-8")
    anchor = 'safety:acceptanceAuthorityTier "CAE_OR_DAE" ; safety:authorityRank 1 ;'
    assert anchor in src, "the mutation's anchor is gone — the mutation would be a no-op"
    dst = tmp_path / "safety_risk_matrix.ttl"
    dst.write_text(
        src.replace(anchor, 'safety:acceptanceAuthorityTier "PM" ; safety:authorityRank 3 ;', 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("SAFETY_RISK_MATRIX_TTL", str(dst))
    matrix.reset_cache()
    try:
        with pytest.raises(AssertionError, match="MORE JUNIOR"):
            test_NO_LEVEL_NAMES_A_MORE_JUNIOR_AUTHORITY_THAN_THE_INSTRUCTION("High")
        with pytest.raises(AssertionError, match="PARA 3.6"):
            test_the_tier_matches_the_instruction("High")
        # THE CONTROL FOR THE MUTATION: the audience key is untouched, so the seal that checks
        # spelling stays GREEN on a ladder that now lets a PM sign a High risk. That is the
        # whole argument for asserting the tier — the key check cannot see this edit.
        test_the_audience_key_still_matches_the_level_it_belongs_to()
    finally:
        matrix.reset_cache()
