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
_ID_TAIL = re.compile(r"^(?P<head>.+) (?P<id>PN-\d+|PLT-[A-Z]+)$")


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


def test_the_parser_finds_the_sheets_eleven_prompts(sheet):
    """THE POSITIVE CONTROL THE RUNBOOK DEMANDS. If the heading style changes the regex matches
    nothing, every assertion below quantifies over an empty list, and the file goes green while
    checking a sheet it can no longer read."""
    prompts = _PROMPT_RE.findall(sheet)
    assert prompts == [
        "draft a risk assessment for HAZ-1003",
        "what hazards are unattended",
        "risk of deferring this work order",
        "what failed on this part",
        "failure trend for this platform by month",
        "what failed on this part PN-8801",
        "failures per month on this platform PLT-ALPHA",
        "draft a risk assessment for HAZ-1001",
        "draft a risk assessment for HAZ-1005",
        "draft a risk assessment for HAZ-1007",
        "draft a risk assessment for HAZ-1006",
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
        # A synonym may itself contain " for " (Q5); the whole prompt matching exactly is
        # STRICTER than the stem, so it is accepted first.
        # A declared synonym FOLLOWED BY ONE ENGINE IDENTIFIER (a part number or a platform id) is
        # the populated twin of that synonym: the same phrasing plus the slot's value, as
        # "for HAZ-1003" is. The identifier must LOOK like one of the engine's, so this accepts
        # nothing a reworded question could slip through.
        m = _ID_TAIL.match(prompt)
        with_id = bool(m) and m.group("head").lower() in declared
        assert prompt.lower() in declared or stem in declared or with_id, (
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


# ---------------------------------------------------------------------------
# Q5 -- the failure trend's designed refusal
# ---------------------------------------------------------------------------

def test_Q5_REFUSES_and_names_the_platform_slot(client, sheet):
    body = _measure(client, "failure_trend_for_this_platform_by_month", {})
    assert body["refused"] is True
    assert body["missing"] == ["platform_id"]
    assert body["slots"][0]["kind"] == "spoken-mandatory"
    assert body["slots"][0]["referent"] == "http://internal/sustainment/safety#Platform"
    assert "slot_required" in sheet and "platform_id" in sheet


def test_Q5s_follow_on_capture_is_what_a_member_gets(sheet, monkeypatch):
    from agent_fleet.safety_agent import measures

    from . import _program_filter as pf

    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = measures.failure_trend_for_this_platform_by_month(platform_id="PLT-ALPHA")
    assert out["months"][0]["citations"] == ["sor-events-a:EVT-55101"]
    for claim in ('"month": "2026-03"', "sor-events-a:EVT-55101", "no_person"):
        assert claim in sheet, f"the sheet no longer carries {claim!r}"


# ---------------------------------------------------------------------------
# Q6 / Q7 -- the populated twins, walked as bob (a member of ALPHA only)
# ---------------------------------------------------------------------------

def test_Q6_and_Q7_captures_are_what_bob_gets(sheet, monkeypatch):
    from agent_fleet.safety_agent import measures

    from . import _program_filter as pf

    pf.install(monkeypatch, caller=pf.BOB, members={pf.BOB: {"SANDBOX_PROGRAM_ALPHA"}})
    q6 = measures.what_failed_on_this_part(part_number="PN-8801")
    assert len(q6["rows"]) == 1 and q6["failure_count"] == 1, "bob sees ONE program's record"
    assert q6["rows"][0]["citations"] == ["sor-events-a:EVT-55101"]
    q7 = measures.failure_trend_for_this_platform_by_month(platform_id="PLT-ALPHA")
    assert [r["period"] for r in q7["rows"]] == ["2026-03"]
    assert q7["series"] == [{"key": "failure_count", "label": "Failures", "unit": "failures"}]
    for claim in ('"value_unit": "failures"', '"scope_label": "PN-8801"', '"period": "2026-03"',
                  '"key": "failure_count"', "sor-events-a:EVT-55101"):
        assert claim in sheet, f"the sheet no longer carries {claim!r}"


# ---------------------------------------------------------------------------
# Q8 / Q9 - the draft at two other matrix cells
# ---------------------------------------------------------------------------

@requires_rdflib
@pytest.mark.parametrize("hazard,sev,prob,level,slug", [
    ("HAZ-1001", "I", "D", "Serious", "serious"),
    ("HAZ-1007", "I", "B", "High", "high"),
])
def test_Q8_and_Q10_captured_level_and_audience_are_what_the_engine_returns(
        client, sheet, hazard, sev, prob, level, slug):
    """The sheet's claim per hazard: the cell, the level the matrix yields for it, and the audience.
    The level is read from the engine (which reads the ratified matrix), not restated here."""
    body = _measure(client, "draft_risk_assessment", {"hazard_id": hazard})
    assert (body["severity"], body["probability"], body["risk_level"]) == (sev, prob, level)
    assert body["acceptance_audience"] == f"risk_acceptance_{slug}:SUSTAINMENT"
    assert body["acceptance_status"] == "drafted"
    assert body["review_request"]["kind"] == f"risk_acceptance_{slug}"
    assert body["citations"]["risk_level"] == "safety_risk_matrix.ttl"
    for claim in (f"risk_acceptance_{slug}:SUSTAINMENT", f'"risk_level": "{level}"',
                  f'"hazard_id": "{hazard}"'):
        assert claim in sheet, f"the sheet no longer carries {claim!r}"


@requires_rdflib
def test_Q1_Q8_Q10_reach_three_DIFFERENT_audiences_and_cells(client):
    """The reason these were picked: each differs from the others in cell AND audience. Without
    this a later fixture edit could collapse two rows onto one audience and the sheet would still
    read as covering three."""
    got = {}
    for h in ("HAZ-1003", "HAZ-1001", "HAZ-1007"):
        b = _measure(client, "draft_risk_assessment", {"hazard_id": h})
        got[h] = ((b["severity"], b["probability"]), b["acceptance_audience"])
    assert len({v[0] for v in got.values()}) == 3, got
    assert len({v[1] for v in got.values()}) == 3, got
    assert {v[1] for v in got.values()} >= {"risk_acceptance_high:SUSTAINMENT"}, got


@requires_rdflib
def test_Q10_the_fixture_cell_is_a_High_cell_of_the_ratified_matrix_and_not_typed_here():
    """The cell is DERIVED: every High cell is read from the ttl, and the fixture's pair must be
    one of them. A fixture edit that leaves the High cell reds here, not in a walk."""
    from rdflib import Graph, Namespace
    from agent_fleet.safety_agent import entities
    ttl = Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "safety_risk_matrix.ttl"
    g = Graph().parse(ttl)
    S = Namespace("http://internal/sustainment/safety#")
    high_cells = set()
    for cell in g.subjects(None, S.MatrixCell):
        lvl = g.value(cell, S.yieldsRiskLevel)
        if lvl is not None and str(lvl).endswith("High"):
            high_cells.add((str(g.value(cell, S.whenSeverity)), str(g.value(cell, S.whenProbability))))
    assert high_cells, "no High cell parsed: the namespace or predicate names moved; this is a blind test"
    h = entities.BY_HAZARD_ID["HAZ-1007"]
    assert (h.severity, h.probability) in high_cells, (h.severity, h.probability, high_cells)
    # and it is not an orphan, so Q2's count of three is undisturbed
    assert h.status == "mitigated" and all(m.owner and m.verified_in_field == "true" for m in h.mitigations)


@requires_rdflib
def test_Q9_a_closed_hazard_is_refused_hazard_closed_and_creates_no_task(client):
    body = _measure(client, "draft_risk_assessment", {"hazard_id": "HAZ-1005"})
    assert body["refused"] is True and body["outcome"] == "hazard_closed", body
    assert body["hazard_id"] == "HAZ-1005"
    assert "review_request" not in body and "risk_level" not in body and "acceptance_audience" not in body
    for claim in ('"outcome": "hazard_closed"', '"hazard_id": "HAZ-1005"'):
        assert claim in _SHEET.read_text(encoding="utf-8"), claim


@requires_rdflib
def test_Q9_CONTROL_the_same_hazard_reopened_drafts_its_task(client, monkeypatch):
    """Differs from the subject in ONE thing: status. Same hazard id, same severity/probability,
    same mitigation, same caller and route."""
    import dataclasses
    from agent_fleet.safety_agent import entities, measures
    reopened = dataclasses.replace(entities.BY_HAZARD_ID["HAZ-1005"], status="open")
    monkeypatch.setitem(measures.BY_HAZARD_ID, "HAZ-1005", reopened)
    body = _measure(client, "draft_risk_assessment", {"hazard_id": "HAZ-1005"})
    assert body["refused"] is False and body["risk_level"] == "Low", body
    assert body["review_request"]["kind"] == "risk_acceptance_low"


@requires_rdflib
def test_Q11_a_not_assessed_hazard_makes_no_task_and_invents_no_level(client):
    body = _measure(client, "draft_risk_assessment", {"hazard_id": "HAZ-1006"})
    assert body["assessment"] == "not_assessed" and body["severity"] is None and body["probability"] is None
    assert "severity" in body["gap"]
    for absent in ("review_request", "risk_level", "acceptance_audience"):
        assert absent not in body, absent
    assert '"assessment": "not_assessed"' in _SHEET.read_text(encoding="utf-8")
