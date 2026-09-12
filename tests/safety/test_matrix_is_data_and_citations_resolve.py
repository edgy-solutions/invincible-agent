"""ADR-0051 seals 4, 10 and 11 — the matrix is data, provenance resolves, and figures are cited.

SEAL 4 IS THE WHOLE OF §2. "The matrix is ratifiable data" is an intention until something proves
the drafted level FOLLOWS THE FILE. So this mutates the TTL — not the code — and requires the
answer to change. Without it, §2 is a paragraph and the second customer is a fork of the engine.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ._engine_extra import requires_rdflib
from agent_fleet.safety_agent import entities, matrix, measures

_REPO = Path(__file__).resolve().parents[2]
_MATRIX = _REPO / "setup" / "ontologies" / "safety_risk_matrix.ttl"


@pytest.fixture(autouse=True)
def _clean_matrix_cache():
    """A module-level cache would make seal 4 pass against the first parse forever — a green
    that proves the cache works and nothing else."""
    matrix.reset_cache()
    yield
    matrix.reset_cache()


# ---------------------------------------------------------------------------
# SEAL 4 — the matrix is DATA
# ---------------------------------------------------------------------------

@requires_rdflib
def test_the_seeded_matrix_resolves_the_cell_the_file_declares():
    """Forward: I/D is Serious in the shipped file, so the draft says Serious."""
    level, audience, source = matrix.resolve_risk_level("I", "D")
    assert (level, audience) == ("Serious", "risk_acceptance_serious:SUSTAINMENT")
    assert source == "safety_risk_matrix.ttl"


@requires_rdflib
def test_changing_one_row_in_the_ttl_changes_the_drafted_level_with_no_code_edit(tmp_path, monkeypatch):
    """SEAL 4. The mutation is to the FILE. If the level does not move, the table is in the code.

    I/E is the row the matrix itself flags as most likely to be wrong — some programmes hold a
    catastrophic outcome never falls below Serious whatever the odds. Editing exactly that row is
    the ratifier's actual act, so it is the right one to prove is a data change.
    """
    before_level, before_aud, _ = matrix.resolve_risk_level("I", "E")
    assert (before_level, before_aud) == ("Medium", "risk_acceptance_medium:SUSTAINMENT")

    edited = tmp_path / "safety_risk_matrix.ttl"
    text = _MATRIX.read_text(encoding="utf-8")
    needle = '[] a safety:MatrixCell ; safety:whenSeverity "I"   ; safety:whenProbability "E" ; safety:yieldsRiskLevel safety:Medium .'
    assert needle in text, "the I/E row is not in the shape this seal edits — update the seal, not the claim"
    edited.write_text(text.replace(needle, needle.replace("safety:Medium", "safety:Serious")), encoding="utf-8")

    monkeypatch.setenv("SAFETY_RISK_MATRIX_TTL", str(edited))
    matrix.reset_cache()

    after_level, after_aud, _ = matrix.resolve_risk_level("I", "E")
    assert after_level == "Serious", (
        "editing the ratified matrix did not change the resolved level — the table is hardcoded "
        "somewhere and §2's claim that the second customer is an overlay rather than a fork is false"
    )
    # AND THE AUDIENCE MOVES WITH IT, which is the consequence that matters: a different set of
    # people can now dispose the acceptance. The level alone would be a label change.
    assert after_aud == "risk_acceptance_serious:SUSTAINMENT"


@requires_rdflib
def test_an_unrecognised_pair_refuses_loudly_and_names_the_file(tmp_path, monkeypatch):
    """SEAL 5, beside seal 4 because they share an instrument. Never coerced to a neighbour."""
    level, audience, source = matrix.resolve_risk_level("Z", "Q")
    assert level is None and audience is None
    assert source == "safety_risk_matrix.ttl", "a refusal must name the vocabulary it consulted"


@requires_rdflib
def test_an_empty_matrix_raises_rather_than_refusing_every_hazard(tmp_path, monkeypatch):
    """THE INSTRUMENT-FAILURE CONTROL. An empty parse must not flow into "not a cell".

    Without this, a broken path makes every draft refuse with a message blaming the HAZARD's
    data — an instrument failure wearing a finding's clothes, and one that would be filed against
    the fixture rather than against the loader.
    """
    empty = tmp_path / "empty.ttl"
    empty.write_text("@prefix safety: <http://internal/sustainment/safety#> .\n", encoding="utf-8")
    monkeypatch.setenv("SAFETY_RISK_MATRIX_TTL", str(empty))
    matrix.reset_cache()
    with pytest.raises(AssertionError, match="ZERO matrix cells"):
        matrix.resolve_risk_level("I", "A")


@requires_rdflib
def test_every_matrix_cell_is_present_so_a_gap_is_a_refusal_not_an_interpolation():
    """All twenty. A missing cell must be visible as a refusal, never filled by a neighbour."""
    cells = matrix.known_cells()
    expected = {(s, p) for s in ("I", "II", "III", "IV") for p in ("A", "B", "C", "D", "E")}
    assert set(cells) == expected, f"matrix is not complete: missing {sorted(expected - set(cells))}"


# ---------------------------------------------------------------------------
# SEAL 10 — provenance resolves
# ---------------------------------------------------------------------------

def _resolvable_ids() -> set[str]:
    """Everything a DERIVED_FROM entry may legitimately name, derived from the fixture."""
    ids = {h.hazard_id for h in entities.HAZARDS}
    ids |= {m.mitigation_id for h in entities.HAZARDS for m in h.mitigations}
    ids |= {c.csi_id for c in entities.CRITICAL_ITEMS}
    ids |= {w.work_order_id for w in entities.WORK_ORDERS}
    ids |= {w.write_up_id for w in entities.WRITE_UPS}
    ids |= {"safety_risk_matrix.ttl"}
    return ids


@requires_rdflib
def test_every_derived_from_entry_resolves_to_something_that_exists():
    """SEAL 10, across every hazard rather than one — a single-hazard check cannot see a source
    that only appears on the branch it did not take."""
    resolvable = _resolvable_ids()
    for h in entities.HAZARDS:
        draft = measures.draft_risk_assessment(hazard_id=h.hazard_id)
        if draft.get("refused"):
            continue
        dangling = [d for d in draft["derived_from"] if d not in resolvable]
        assert not dangling, f"{h.hazard_id}: DERIVED_FROM names things that do not exist: {dangling}"


@requires_rdflib
def test_a_fabricated_provenance_entry_is_caught(monkeypatch):
    """THE CONTROL FOR SEAL 10. A checker that has only seen real ids has not been shown able to
    reject a fabricated one."""
    resolvable = _resolvable_ids()
    fabricated = "HAZ-9999-DOES-NOT-EXIST"
    assert fabricated not in resolvable, "the resolvable set is not discriminating"


@requires_rdflib
def test_the_draft_cites_every_figure_it_states():
    """SEAL 11 — cite-or-omit. A figure without a citation is a claim the reader cannot trace."""
    draft = measures.draft_risk_assessment(hazard_id="HAZ-1001")
    assert draft["refused"] is False
    for field in ("severity", "probability", "risk_level", "acceptance_audience"):
        assert field in draft, f"{field} missing from the draft"
        assert draft["citations"].get(field), f"{field} is stated with no citation"


@requires_rdflib
def test_an_unassessed_hazard_states_the_gap_and_invents_nothing():
    """SEAL 11's other half, and the one a lazy implementation fails.

    HAZ-1006 has no severity and no probability. The draft must say so, resolve NO risk level and
    imply NO authority — not reach for the bottom of the matrix, which reads as assessed and
    negligible, and not borrow a neighbouring hazard's figures.
    """
    draft = measures.draft_risk_assessment(hazard_id="HAZ-1006")
    assert draft["assessment"] == "not_assessed"
    assert draft["severity"] is None and draft["probability"] is None
    assert "risk_level" not in draft, "a level was resolved for a hazard with no severity"
    assert "acceptance_audience" not in draft, "an authority was implied with no assessed risk"
    assert "severity" in draft["gap"]


@requires_rdflib
def test_the_draft_never_writes_an_acceptance_on_any_fixture_hazard():
    """§7's refusal, exercised rather than asserted from the source.

    Seal 2's AST half proves no code path writes it. This proves no OUTPUT carries it, across
    every hazard in the fixture — belt and braces, because the two could diverge through a helper.
    """
    for h in entities.HAZARDS:
        draft = measures.draft_risk_assessment(hazard_id=h.hazard_id)
        assert draft.get("acceptance_status", "drafted") == "drafted", (
            f"{h.hazard_id}: the engine emitted an acceptance status other than 'drafted'"
        )
