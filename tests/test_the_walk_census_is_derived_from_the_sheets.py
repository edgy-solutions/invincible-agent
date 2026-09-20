"""The walk census asks what the sheets ask — checked BOTH ways, on a fixture that can fail.

The census stores each question's text and so does the sheet. That is a MIRROR, and a mirror is
the shape that has cost this tree the most: two declarations, each complete and correct on its
own side, with the relation between them asserted nowhere. A row in one and not the other is
invisible to every per-side check.

So the seals below quantify in both directions, and — the part that matters more — each is run
against a FIXTURE THAT BREAKS IT. A reconciliation that silently compares nothing reports the
same clean result as one that compares everything and finds no drift; those two states are
distinguishable only by making it fail on demand.

Run: uv run --frozen pytest tests/test_the_walk_census_is_derived_from_the_sheets.py -v
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.walk_census import (  # noqa: E402
    DISPOSITIONS, DRIFTED, FAIL, MISSING_ROW, PASS, ROW_KEY, CensusError, CensusRow,
    judge, load_rows, partition, reconcile, routing_of, sheet_prompts, verb_names,
)

CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"
COST_SHEET = "docs/measurements/cost-card-walk-sheet.md"


@pytest.fixture(scope="module")
def rows():
    return load_rows(CENSUS)


def test_the_census_loads_and_is_not_empty(rows):
    """THE FLOOR. Every seal below quantifies over these rows; zero of them is a green suite
    that asserted nothing, which is the exact silence the census was built to end."""
    assert len(rows) >= 5, f"only {len(rows)} census rows"


def test_THE_PARSER_FINDS_THE_COST_SHEETS_PROMPTS():
    """A POSITIVE CONTROL ON THE PARSER, not on the fleet.

    `PROMPT_RE` is shared with `tests/cost/test_the_walk_sheet_resolves_to_cost_lots.py`, which
    has parsed this sheet since 2026-09-11. If the sheet's heading style changed, this regex
    would find NOTHING, `reconcile` would compare NOTHING, and every derivation seal here would
    pass while asserting nothing at all.
    """
    prompts = sheet_prompts(_REPO / COST_SHEET)
    assert len(prompts) == 5, (
        f"expected the cost sheet's five prompts, parsed {len(prompts)}: {prompts}. This count "
        f"is stated rather than `>=` because a merge changed this sheet under a seal derived "
        f"from it once already, and the count is what said so."
    )


def test_the_census_matches_the_sheets_in_both_directions(rows):
    """The real assertion: no drift, and no sheet prompt without a row."""
    rec = reconcile(rows, _REPO)
    assert rec.ok, "census/sheet reconciliation failed:\n  " + "\n  ".join(
        f"{k}: {who}: {d}" for k, who, d in rec.problems
    )
    assert rec.compared >= 5, (
        f"only {rec.compared} row(s) were actually compared against a sheet. A reconciliation "
        f"that compares nothing is indistinguishable from one that finds nothing wrong."
    )


def test_A_DRIFTED_QUESTION_IS_CAUGHT(rows, tmp_path):
    """THE CONTROL FOR THE DIRECTION 'census drifted from sheet'.

    Mutating the census's text must red. Without this, a `reconcile` that compared nothing —
    or compared and never looked at the text — would sail through the seal above.
    """
    doc = yaml.safe_load(CENSUS.read_text(encoding="utf-8"))
    target = next(r for r in doc["rows"] if r["sheet"] == COST_SHEET)
    target["question"] = target["question"] + " and also the weather"
    p = tmp_path / "drifted.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")

    rec = reconcile(load_rows(p), _REPO)
    assert not rec.ok, "a reworded census question was NOT caught — the text is not being compared"
    assert any(k == DRIFTED for k, _, _ in rec.problems), (
        f"caught something, but not as drift: {rec.problems}"
    )


def test_A_SHEET_PROMPT_WITH_NO_ROW_IS_CAUGHT(rows, tmp_path):
    """THE CONTROL FOR THE OTHER DIRECTION, and the one a per-row loop structurally cannot see.

    Deleting a row must red, because the sheet still asks that question and now nobody runs it.
    This is the half that makes the mirror safe: iterating the census can never discover a
    prompt the census does not contain.
    """
    doc = yaml.safe_load(CENSUS.read_text(encoding="utf-8"))
    before = len(doc["rows"])
    doc["rows"] = [r for r in doc["rows"] if r["sheet_index"] != 4 or r["sheet"] != COST_SHEET]
    assert len(doc["rows"]) == before - 1, "fixture removed nothing — it cannot fail"
    p = tmp_path / "missing.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")

    rec = reconcile(load_rows(p), _REPO)
    assert not rec.ok, "a sheet prompt with no census row was NOT caught"
    assert any(k == MISSING_ROW for k, _, _ in rec.problems), (
        f"caught something, but not as a missing row: {rec.problems}"
    )


def _the_blocked_row_rules(runnable, blocked):
    """What a blocked row must satisfy, lifted out of the partition test so that a FIXTURE can
    exercise it when no real row is blocked.

    It is a helper rather than inline code for exactly one reason: at zero blocked rows an inline
    loop asserts nothing and still reports green.
    """
    for r in blocked:
        assert len(r.blocked) > 20, (
            f"{r.id}: blocked reason is {r.blocked!r}. A bare or empty reason reads as a "
            f"considered negative, and it is not one."
        )
        assert r.sheet not in {x.sheet for x in runnable}, (
            f"{r.id} is blocked on {r.sheet}, but another row runs against that same sheet — "
            f"so the sheet exists and this reason is stale"
        )


def test_every_row_is_runnable_or_blocked_WITH_A_REASON(rows):
    """THE PARTITION. Every row is in exactly one state and nothing is undecided.

    A row that can't draw yet is a RED WITH ITS NAMED REASON, not an exclusion — the architect's
    words, and the reason is load-bearing: a blocked row with an empty reason reads as
    deliberate, and `unsupported`/`none` is the most trusted wrong answer there is.
    """
    runnable, blocked = partition(rows)
    assert len(runnable) + len(blocked) == len(rows)
    assert runnable, "no runnable rows — the census would run nothing and report success"
    # `assert blocked` RETIRED 2026-09-19, and it retired exactly the way it said it would. It
    # read: "no blocked rows. Three sheets (safety, finance, docs) do not exist yet; if they now
    # do, their rows should be runnable and THIS ASSERTION SHOULD BE THE THING THAT CHANGES."
    # All three landed — safety `0f1f2cb`, finance `d84bba5`, docs `76706e9` — so the state it
    # asserted is over, and keeping it would red on the sheets ARRIVING, which is the single
    # event it was put there to wait for.
    #
    # ITS DEPARTURE TAKES THE RULES BELOW WITH IT, AND THAT IS THE REAL COST. With nothing
    # blocked the loop body never runs, so the reason-quality rules stay green however far they
    # rot — a ratchet blind precisely BECAUSE its register is accurate. The unconditional
    # fixture arm below exercises them in both directions so they keep firing at zero.
    _the_blocked_row_rules(runnable, blocked)


def test_THE_BLOCKED_ROW_RULES_FIRE_EVEN_WITH_NOTHING_BLOCKED(rows):
    """THE UNCONDITIONAL ARM, and it is the half that survives the census going all-green.

    `test_every_row_is_runnable_or_blocked_WITH_A_REASON` iterates the REAL blocked rows, so the
    day the last one clears it starts asserting nothing and reporting success — the failure mode
    an empty register always has. This arm owns the rules instead, against a fixture, so
    deleting or weakening one of them reds here whatever the census happens to contain today.

    BOTH DIRECTIONS, because an arm that only shows the rules passing cannot tell a live rule
    from a deleted one.
    """
    runnable, _ = partition(rows)
    assert runnable, "no runnable row to build the fixture from — the fixture cannot fail"
    sample = runnable[0]
    elsewhere = [r for r in runnable if r.sheet != sample.sheet]

    # PASSES: a real reason, naming a sheet no runnable row uses.
    _the_blocked_row_rules(
        elsewhere,
        [replace(sample, blocked="the sheet this row needs has not been written yet")],
    )

    # REDS: a bare reason. `none`/`unsupported` is the most trusted wrong answer there is.
    with pytest.raises(AssertionError):
        _the_blocked_row_rules(elsewhere, [replace(sample, blocked="none")])

    # REDS: a STALE reason — the sheet it claims is absent is the same one a runnable row draws
    # against, which is how a blocker outlives the thing that justified it.
    with pytest.raises(AssertionError):
        _the_blocked_row_rules(
            runnable,
            [replace(sample, blocked="the sheet this row needs has not been written yet")],
        )


def test_a_blocked_row_names_a_sheet_that_really_is_absent(rows):
    """A stale blocker is pre-authenticated: it was true when written and reads as true now.

    So the reason is CHECKED rather than trusted. The moment 74, 91 or 5f lands a sheet, the row
    blocked on it must stop being blocked — and this is what makes that fail loudly instead of
    leaving a question permanently unasked behind a reason that has expired.
    """
    _, blocked = partition(rows)
    for r in blocked:
        prompts = sheet_prompts(_REPO / r.sheet)
        assert not prompts, (
            f"{r.id} is blocked with reason {r.blocked!r}, but {r.sheet} now exists and parses "
            f"{len(prompts)} prompt(s). The sheet landed; derive the row and unblock it."
        )


def test_EVERY_ARCHETYPE_A_ROW_PUTS_A_FLOOR_ON_IS_KEYED(rows):
    """The question the overlap seal below cannot ask, and the one that actually bit.

    `test_the_row_key_map_agrees_with_engine_costs_own_table` compares `set(theirs) &
    set(ROW_KEY)`. It asserts the SHARED archetypes agree and is silent about an archetype
    missing from `ROW_KEY` altogether — which is the only way the defect could occur. It ran,
    its premise held, and it answered a weaker question than the one it was written for.

    WHAT THAT COST, 2026-09-19: three finance rows — variance-decomposition, funding-status and
    eac-comparison — were saved into the lexical baseline as "0 row(s) under None", under a
    partition headed "FOUR finance rows fail on payload shape or row count". All three had drawn
    correctly at exactly their floor (1, 18 and 3 rows, confirmed against the live fleet and
    against engine-fin's own wire). The `None` in that message was this table's missing key.

    DERIVED FROM THE CENSUS, never a list kept beside it: a new row naming a new archetype reds
    on the commit that adds it, which is one commit before anyone runs it against a fleet and
    reads the gap as a defect.
    """
    need = {r.expect_archetype for r in rows if r.expect_archetype and r.min_rows}
    assert need, "no row puts a floor on an archetype — this seal is asserting nothing"
    missing = sorted(a for a in need if a not in ROW_KEY)
    assert not missing, (
        f"{len(missing)} archetype(s) carry a row floor with no ROW_KEY entry: {missing}. "
        f"judge() cannot find their rows, counts zero, and files a healthy card as an empty "
        f"one. Add each to ROW_KEY with the payload key its projector actually emits."
    )


def test_AN_UNKEYED_ARCHETYPE_IS_REPORTED_AS_AN_INSTRUMENT_FAILURE():
    """BOTH DIRECTIONS, on a fixture this test owns — the rule above must be able to fail.

    A seal that only ever sees a satisfied table proves nothing about what happens when the
    table is short. So: judge a FULL card whose archetype is deliberately absent from ROW_KEY,
    and assert the runner says it could not measure — not that the card was empty. The two are
    opposite findings and the old message could not tell them apart.
    """
    unkeyed = "ARCHETYPE_THAT_IS_NOT_KEYED"
    assert unkeyed not in ROW_KEY, "fixture archetype leaked into the real table"

    def _row(archetype):
        return CensusRow(
            id="fixture", sheet=COST_SHEET, sheet_index=0, question="q", user="alice",
            persona="COST_ANALYST", domains=("PRODUCTION_COST",), expect_verb="",
            expect_archetype=archetype, min_rows=3, dispositions=("drawn",),
            frontend_id="cortex-ui-desktop",
        )

    def _card(archetype):
        return {
            "final": {"components": [
                {"archetype": archetype,
                 "payload": {"rows": [{"i": 0}, {"i": 1}, {"i": 2}]}}]},
            "events": [{"event": "route_decision",
                        "data": {"route_status": "matched",
                                 "handled_by": {"endpoint_url": "x/v"}}}],
        }

    state, why = judge(_row(unkeyed), _card(unkeyed))
    assert state == FAIL, "an archetype the runner cannot measure must not pass silently"
    joined = " ".join(why)
    assert "NO ROW_KEY ENTRY" in joined, f"expected an instrument failure, got: {why}"
    assert "INSTRUMENT failure" in joined, f"the report must name itself as one: {why}"
    assert "0 row(s) under None" not in joined, (
        "the old message is back: a card with three rows must never be reported as empty"
    )

    # AND THE POSITIVE HALF: the identical card, under a KEYED archetype, passes its floor.
    # Without this the assertions above would also hold for a fixture that was simply broken.
    state2, why2 = judge(_row("CONTRIBUTION_RANKING"), _card("CONTRIBUTION_RANKING"))
    assert state2 == PASS, f"the control that must pass did not: {why2}"


def test_the_row_key_map_agrees_with_engine_costs_own_table():
    """TWO MIRRORS AGAIN, so it gets the same treatment.

    `ROW_KEY` says where a card's rows live. engine-cost's card conformance test says the same
    thing for its four archetypes. Two tables of one fact drift silently, so the overlap is
    asserted rather than assumed — `DELTA_SET` calls them `effects`, and that is its contract's
    word rather than a synonym either file chose.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_cost_cards", _REPO / "tests" / "cost" / "test_cost_cards_conform.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    theirs = getattr(mod, "_ROW_KEY", None)
    assert theirs, "engine-cost's _ROW_KEY is gone or renamed — this seal is comparing nothing"
    overlap = set(theirs) & set(ROW_KEY)
    assert len(overlap) >= 4, f"only {len(overlap)} shared archetype(s): {sorted(overlap)}"
    for a in sorted(overlap):
        assert ROW_KEY[a] == theirs[a], (
            f"{a}: census says rows live under {ROW_KEY[a]!r}, engine-cost says {theirs[a]!r}"
        )


def test_a_row_accepting_every_disposition_is_refused(tmp_path):
    """A row that accepts everything asserts nothing and stays green through any change.

    This is the vacuum in its row-shaped form, and it is refused at LOAD time so it cannot be
    written by someone trying to quiet a red.
    """
    doc = yaml.safe_load(CENSUS.read_text(encoding="utf-8"))
    doc["rows"][0]["dispositions"] = list(DISPOSITIONS)
    p = tmp_path / "permissive.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(CensusError, match="asserts nothing"):
        load_rows(p)


def _result(events, final=None):
    return {"events": events, "final": final}


def _route_decision(verb_iri, endpoint, status="matched", fallback=False):
    return {"event": "route_decision", "data": {
        "action": {"iri": verb_iri},
        "handled_by": {"endpoint_url": endpoint},
        "route_status": status, "fallback": fallback,
    }}


def test_ROUTING_IS_READ_FROM_THE_route_decision_EVENT():
    """The defect this runner shipped with for one run, sealed at the shape the fleet emits.

    MEASURED 2026-09-19: `final_payload` carries exactly `components` and
    `presentation_provenance`. There is no routing on it. The first reader looked there, got
    `{}`, and every census row reported `verb ''` — which read as a fleet that had stopped
    routing. It had not: it was matching at 0.92 to the right engine the whole time.
    """
    r = _result([_route_decision("mesh:costSupplierConcentration",
                                 "http://engine-cost:8097/measure/cost_supplier_concentration")])
    assert routing_of(r).get("route_status") == "matched"
    assert "cost_supplier_concentration" in verb_names(routing_of(r))


def test_A_MISSING_ROUTING_PROJECTION_IS_AN_INSTRUMENT_FAILURE_not_an_empty_verb(rows):
    """A BROKEN MATCHER RETURNS ZERO, AND ZERO READS AS A FINDING.

    This is the single most expensive habit in this tree, and it just cost a wrong reading of a
    healthy fleet. So the absent case is asserted to name ITSELF — the runner must say it could
    not see, rather than report what it did not see as a miss.
    """
    row = next(r for r in rows if r.expect_verb and r.runnable)
    state, why = judge(row, _result([]))
    assert state == FAIL
    joined = " ".join(why)
    assert "INSTRUMENT" in joined, f"missing routing was not named as an instrument failure: {why}"
    assert "lacks" not in joined, (
        f"reported a verb mismatch for an answer whose routing could not be read at all — that "
        f"is the false finding this seal exists to prevent: {why}"
    )


def test_a_verb_matches_either_spelling():
    """`mesh:costSupplierConcentration` on the wire, `cost_supplier_concentration` on the sheet.

    Asserting one spelling would fail on naming convention rather than on behaviour — and a red
    that means "the convention differs" is indistinguishable, in a morning report, from one that
    means "the question reached the wrong engine".
    """
    rd = _route_decision("mesh:costSupplierConcentration", "")
    names = verb_names(rd["data"])
    assert {"costSupplierConcentration", "cost_supplier_concentration"} <= names, names


def test_an_empty_census_is_refused(tmp_path):
    """A loader returning an empty list hands its caller a green light and nothing to run."""
    p = tmp_path / "empty.yaml"
    p.write_text("version: 1\nrows: []\n", encoding="utf-8")
    with pytest.raises(CensusError):
        load_rows(p)
