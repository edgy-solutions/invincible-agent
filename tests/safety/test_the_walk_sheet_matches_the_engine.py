"""The safety walk sheet's captured payloads are what the engine actually returns.

**A SHEET AGES AGAINST ITS ENGINE, AND A STALE FIGURE READS AS A CHECKED ONE.** The runbook's
pre-walk step 1 is "re-capture every payload" — a human instruction, which means it is followed
until the week somebody is in a hurry. This asserts the load-bearing claims instead, so a drift
reds at commit time rather than sending a walker to look for a defect the sheet invented.

**AND THE SHEET IS ALREADY LOAD-BEARING SOURCE.** `walk-census.yaml` derives its questions from
the prompts here, both directions. This adds the other half: the census checks the sheet's
QUESTIONS against itself, and nothing checked the sheet's ANSWERS against the engine.

── WHAT IS ASSERTED AND WHAT IS DELIBERATELY NOT ───────────────────────────────────────────────
`days_open`, `contribution` and `share_of_total` are computed from `date.today()`, so the
integers move daily and the ORDER does not. Pinning the numbers would make this file red every
morning for no defect — the shape that teaches a team to ignore a seal. So the ORDER, the
IDENTITIES and the REASONS are asserted, and the arithmetic is asserted only as a relation
(`rank 2 carries the largest bar`), which is the claim the sheet actually makes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._engine_extra import requires_rdflib

_SHEET = Path(__file__).resolve().parents[2] / "docs" / "measurements" / "safety-walk-sheet.md"
_PROMPT_RE = re.compile(r'^> \*\*"(?P<q>[^"]+)"\*\*', re.MULTILINE)


@pytest.fixture(scope="module")
def sheet() -> str:
    return _SHEET.read_text(encoding="utf-8")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    with TestClient(main.app) as c:
        yield c


def _measure(client, verb: str, params: dict):
    r = client.post(f"/measure/{verb}", json={"query": "", "params": params})
    assert r.status_code == 200, f"{verb} answered {r.status_code}: {r.text[:200]}"
    return r.json()


def test_the_parser_finds_the_sheets_three_prompts(sheet):
    """THE POSITIVE CONTROL THE RUNBOOK DEMANDS. If the heading style changes the regex matches
    nothing, every assertion below quantifies over an empty list, and the file goes green while
    checking a sheet it can no longer read."""
    prompts = _PROMPT_RE.findall(sheet)
    assert prompts == [
        "draft a risk assessment for HAZ-1003",
        "what hazards are unattended",
        "risk of deferring this work order",
    ], f"the sheet's prompts have changed or the parser cannot read them: {prompts}"


def test_every_prompt_is_a_declared_synonym_of_the_verb_it_names():
    """The runbook's rule, asserted: *the phrasing is the routing signal, so prefer the engine's
    own declared synonyms*. A question invented for the sheet tests a path no user takes, and the
    sheet would keep passing while the routing it claims to walk had drifted away from it."""
    from agent_fleet.safety_agent import main

    declared = {s.lower() for v in main.VERBS for s in v["synonyms"]}
    for prompt in _PROMPT_RE.findall(_SHEET.read_text(encoding="utf-8")):
        # The HAZ-1003 prompt carries an instance the synonym cannot; compare the stem.
        stem = prompt.lower().split(" for ")[0]
        assert stem in declared, (
            f"{prompt!r} is not one of the engine's declared synonyms — the sheet is walking a "
            f"phrasing nothing routes on. Declared: {sorted(declared)}"
        )


# ---------------------------------------------------------------------------
# Q1 — the drafted assessment
# ---------------------------------------------------------------------------

@requires_rdflib
def test_Q1s_captured_level_and_audience_are_what_the_engine_returns(client, sheet):
    """The two fields the sheet tells a walker to check, and the two that would send them to the
    wrong component if stale: a wrong `risk_level` reads as a grant defect, not a matrix one."""
    body = _measure(client, "draft_risk_assessment", {"hazard_id": "HAZ-1003"})
    assert body["risk_level"] == "Medium", body["risk_level"]
    assert body["acceptance_audience"] == "risk_acceptance_medium:SUSTAINMENT"
    assert body["acceptance_status"] == "drafted"
    assert body["review_request"]["kind"] == "risk_acceptance_medium"
    for claim in ("risk_acceptance_medium:SUSTAINMENT", '"risk_level": "Medium"'):
        assert claim in sheet, f"the sheet no longer carries {claim!r}"


@requires_rdflib
def test_Q1s_level_is_CITED_to_the_matrix_not_to_the_engine(client):
    """The sheet's distinguishing check. Severity II x probability D is Medium in Table III; if
    the level stopped citing the file, the engine would be deciding it."""
    body = _measure(client, "draft_risk_assessment", {"hazard_id": "HAZ-1003"})
    assert body["citations"]["risk_level"] == "safety_risk_matrix.ttl"
    assert "safety_risk_matrix.ttl" in body["derived_from"]


# ---------------------------------------------------------------------------
# Q2 — the ranking
# ---------------------------------------------------------------------------

def test_Q2s_captured_ORDER_and_identities_hold(client, sheet):
    """ORDER, not arithmetic. The integers move daily; the ranking does not."""
    rows = _measure(client, "find_orphaned_hazards", {})["rows"]
    assert [r["entity_id"] for r in rows] == ["HAZ-1001", "HAZ-1003", "HAZ-1002"], rows
    for hz in ("HAZ-1001", "HAZ-1003", "HAZ-1002"):
        assert hz in sheet, f"the sheet's capture no longer names {hz}"


def test_Q2s_THREE_ORPHANS_AND_ONE_NOT_ASSESSED(client):
    """The sheet's loudest check: a count of 6 means not-assessed hazards were folded in, which
    is the conflation this verb exists to refuse."""
    body = _measure(client, "find_orphaned_hazards", {})
    assert body["orphan_count"] == 3, body["orphan_count"]
    assert body["not_assessed_count"] == 1
    ids = {r["entity_id"] for r in body["rows"]}
    assert len(ids) == 3 and not (ids & {n["hazard_id"] for n in body["not_assessed"]})


def test_Q2s_THREE_REASONS_ARE_ALL_DIFFERENT(client):
    """The sheet says the third reason is the one that hides — a mitigation that exists and is
    owned reads as handled. Three identical reasons would mean the field is being defaulted."""
    rows = _measure(client, "find_orphaned_hazards", {})["rows"]
    reasons = [r["orphan_reason"] for r in rows]
    assert len(set(reasons)) == 3, f"orphan reasons are not distinct: {reasons}"
    assert any("never verified" in r for r in reasons), reasons


def test_Q2s_NON_MONOTONIC_BAR_IS_STILL_TRUE(client, sheet):
    """**THE SHEET'S SHARPEST CLAIM, AND THE ONE MOST LIKELY TO GO STALE INTO A LIE.**

    It tells a walker that rank 2 carrying the LONGEST bar is correct — severity orders the rows,
    days-open sizes them. If the fixture ever changed so the bars were monotonic, that paragraph
    would be teaching a walker to accept a real sorting bug as a designed feature. Asserted as a
    RELATION, so it survives the daily arithmetic.
    """
    rows = _measure(client, "find_orphaned_hazards", {})["rows"]
    longest = max(rows, key=lambda r: r["contribution"])
    assert longest["rank"] != 1, (
        "the longest bar is now at rank 1 — the sheet's 'a longer bar in second place is CORRECT' "
        "paragraph has become a lie, and a walker following it would wave through a real sorting "
        "defect. Re-capture and rewrite that section."
    )
    assert "rank 2" in sheet and "LONGEST" in sheet


def test_Q2_carries_the_axis_legend_that_keeps_the_bar_honest(client):
    """`value_label` is the only defence against a reader taking the bar for the rank."""
    body = _measure(client, "find_orphaned_hazards", {})
    assert body["value_label"] == "days open"
    assert body["value_unit"] == "days"
    assert all("favourable" not in r for r in body["rows"]), (
        "a direction has appeared on rows the sheet says carry none"
    )


# ---------------------------------------------------------------------------
# Q3 — the designed refusal
# ---------------------------------------------------------------------------

def test_Q3_REFUSES_and_names_the_slot(client, sheet):
    """The refusal IS the pass, so the sheet's claim about it has to be true."""
    body = _measure(client, "assess_deferral_risk", {})
    assert body["refused"] is True
    assert body["missing"] == ["work_order_id"]
    assert body["slots"][0]["kind"] == "spoken-mandatory"
    assert "slot_required" in sheet


def test_Q3s_REFERENT_IS_THE_STANDARDS_REAL_CLASS(client, sheet):
    """ADR-0007's ruling, visible on the wire — and **this seal caught its own sheet going stale
    on the first real drift**, which is the whole reason it exists.

    The referent was `mro:MaintenanceWorkOrder`, cited from `iof_mro.ttl`, whose own header calls
    itself a *"Dummy IOF / MIMOSA Maintenance Reference Ontology extract"*. The REAL upstream
    (`Maintenance.rdf`, already manifested as `IOF_MRO`) declares
    `iof-constr:MaintenanceWorkOrderRecord` and no `MaintenanceWorkOrder` at all.

    **`endswith("...Record")` rather than `endswith("MaintenanceWorkOrder")`, deliberately**: the
    dummy's local name is a PREFIX of the standard's, so the loose form passes on BOTH and cannot
    tell them apart — a check unable to distinguish the two things it was written to distinguish.
    The namespace is asserted separately because the local name alone is not the identity.
    """
    body = _measure(client, "assess_deferral_risk", {})
    referent = body["slots"][0]["referent"]
    assert referent.endswith("MaintenanceWorkOrderRecord"), referent
    assert referent.startswith("https://spec.industrialontologies.org/ontology/construct/"), (
        f"the referent is not in the standard's `construct` namespace: {referent}"
    )
    assert "internal/maintenance#WorkOrder" not in referent
    assert "MaintenanceReferenceOntology/MaintenanceWorkOrder" not in referent, (
        "the dummy file's IRI is back — that class exists in no published IOF ontology"
    )
    assert "MaintenanceWorkOrderRecord" in sheet


def test_the_sheet_still_marks_the_iof_manifest_gap_as_a_RESIDUAL(sheet):
    """An unnamed residual gets scored as a defect by the first honest walker, and the second one
    learns to ignore the sheet. This keeps the marker present while the gap is — and it is the
    marker, not the gap, that this seal is about."""
    assert "KNOWN RESIDUAL" in sheet
    assert "iof_mro.ttl" in sheet and "prime manifest" in sheet
