"""AN ENGINE THAT ABSTAINS IS NOT MATCHED — both ends of a field that had no wire.

THE DEFECT, measured 2026-09-26 across three fires of the docs walk. `docs_agent.explain` has
always returned `abstained: True` — naming the subject, refusing honestly — when no page in the
corpus explains what was asked. A repo-wide search found exactly ONE site touching that field: the
producer. **Zero readers.** So the supervisor stamped `route_status: "matched"` ("the specialist
answered"), the turn drew an ordinary `KNOWLEDGE_DOCUMENT` card with no sections, and the walk
census scored census row `docs-how-do-i-roll-a-service-abstains` as `drawn` — the exact word that
row's own comment calls *"the defect here"*. Both ends correct, the wire empty.

WHAT THIS FILE ASSERTS, and why each arm is not its neighbour:

* the RULE is one function, `iagent_pure.engine_abstain`, and **both sides import it** rather than
  agreeing on a literal. Copied from the `pick_primary` precedent next door, which exists because
  two functions that agree in a docstring are not one rule.
* the rule is driven by the **REAL PRODUCER's payload** — `explain.abstain()` — not by a dict
  written here. A fixture written in this file would keep passing after the engine renamed the
  field, and would be a seal on my own typing.
* `is True` and never truthiness, controlled on the values that would break it.
* `judge` scores the abstain as `abstained`, **and an abstain that CAN offer verbs still scores
  `slot_required`** — the 2026-09-17 ruling, which the sheet's `slot_required` rows depend on. Their
  count is MEASURED below rather than stated: the first draft of this file said "four", which was
  true until the same change converted one of those four rows to `abstained`.
* THE NON-HIDING CONTROL. `judge` stopped naming `abstained` in its unexpected-route_status line,
  which could hide a wrong abstain. It does not, and that is fired rather than argued.
* THE WINDOW. The neighbouring seal finds a subtask return by searching back 1400 characters from
  `"expert_response"`. Writing this change's rationale INSIDE the dict literal pushed the site out
  of that window, and the seal went right on passing while covering one site fewer. That is a guard
  demoted by a comment, so the coverage is now asserted instead of assumed.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

from iagent_pure.engine_abstain import (  # noqa: E402
    ABSTAIN_FIELD,
    ABSTAINED,
    engine_abstained,
    route_status_for,
)
from iagent_pure.primary_selection import MATCHED, pick_primary  # noqa: E402
from iagent_pure.walk_census import (  # noqa: E402
    DISPOSITIONS,
    FAIL,
    PASS,
    CensusError,
    judge,
    load_rows,
)

_SUP_PATH = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_SUP = _SUP_PATH.read_text(encoding="utf-8")
_CENSUS_PATH = _REPO / "docs" / "measurements" / "walk-census.yaml"

_ROW_ID = "docs-how-do-i-roll-a-service-abstains"


@pytest.fixture(scope="module")
def rows():
    return load_rows(_CENSUS_PATH)


# ── the rule, driven by the REAL producer ────────────────────────────────────

def _real_abstain() -> dict:
    """The docs engine's own abstain payload. Imported, never retyped.

    If this import breaks, the seal is telling you the producer moved — which is worth a red,
    because the whole defect was the two ends never having been connected.
    """
    from agent_fleet.docs_agent.explain import abstain

    return abstain("mesh:rolling-a-service")


def test_the_real_engine_payload_is_read_as_an_abstain():
    """THE ASSERTION THIS FILE EXISTS FOR: the producer's actual output earns `abstained`."""
    assert route_status_for(_real_abstain()) == ABSTAINED


def test_the_abstain_still_names_its_subject():
    """A refusal that cannot be acted on is a different failure from one that can.

    The engine's docstring promises the subject by name. The census row wants "an abstain NAMING
    the subject", so the naming is asserted here rather than trusted — a docstring is not evidence.
    """
    payload = _real_abstain()
    assert payload.get("subject") == "mesh:rolling-a-service"
    assert "mesh:rolling-a-service" in (payload.get("body") or "")


def test_an_ordinary_answer_is_still_matched():
    """THE NEGATIVE CONTROL. Without the field, nothing changes — or this rule would restatus
    every answer in the fleet, and the seal above would pass for the wrong reason."""
    assert route_status_for({"archetype": "KNOWLEDGE_DOCUMENT", "sections": [{"h": "x"}]}) == MATCHED
    assert route_status_for({}) == MATCHED


@pytest.mark.parametrize("value", ["false", "true", 1, 0, "", [], {}, None, "abstained"])
def test_only_the_literal_True_abstains(value):
    """`is True`, because this value crossed a JSON boundary from an engine we do not control.

    `"false"` is the one that matters: a truthiness test reads an engine's DENIAL as an abstain.
    `1` is the one that looks harmless — `1 == True` in Python, and `is True` is what separates
    them. The same trap classified-refusal tuples set in `mesh_registration`.
    """
    assert engine_abstained({ABSTAIN_FIELD: value}) is False
    assert route_status_for({ABSTAIN_FIELD: value}) == MATCHED


def test_a_non_dict_payload_cannot_crash_routing():
    """An engine returning a list or a string must not take the turn down on the way to a status."""
    for junk in (None, "abstained", ["abstained"], 7):
        assert route_status_for(junk) == MATCHED


# ── both sides call it, rather than agreeing on a literal ────────────────────

def _imports_engine_abstain(src: str) -> bool:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("engine_abstain"):
            return True
    return False


def test_the_supervisor_imports_the_rule_instead_of_restating_it():
    assert _imports_engine_abstain(_SUP), (
        "the supervisor decides abstain-vs-matched with its own copy of the rule; a rename on "
        "one side then silently makes every abstain 'matched' again"
    )


def test_the_census_imports_the_same_constant():
    census_src = (_REPO / "src" / "iagent_pure" / "walk_census.py").read_text(encoding="utf-8")
    assert _imports_engine_abstain(census_src)
    assert '"abstained"' not in census_src.replace('ABSTAINED = "abstained"', ""), (
        "the census spells the status as a bare literal somewhere — one axis gets one spelling, "
        "and a literal here is the drift this module was created to prevent"
    )


def test_the_engine_answered_site_no_longer_hardcodes_matched():
    """THE NO-OP MEASUREMENT, inverted: this arm is RED on the unfixed tree.

    The old code was `"route_status": "matched",` immediately above `"expert_response": data,`.
    That exact adjacency is the defect, so its absence is what proves the fix landed — and its
    presence is what this arm would have caught before the fix existed.
    """
    assert not re.search(r'"route_status":\s*"matched",\s*\n\s*"expert_response":\s*data,', _SUP), (
        "the pass-through site still stamps a literal 'matched' over an engine's own payload"
    )
    assert re.search(r'"route_status":\s*route_status\b', _SUP), (
        "the pass-through site no longer carries a computed route_status at all"
    )


def test_the_three_sibling_matched_sites_are_left_alone():
    """A CENSUS, NOT A SAMPLE. Three other subtask returns stamp a literal `matched`, and all
    three are CORRECT: each builds its own payload with an explicit `status`, so none can carry a
    foreign engine's `abstained`. If one of them ever starts passing an engine's dict through,
    this count moves and the class gets re-examined instead of assumed settled.
    """
    assert _SUP.count('"route_status": "matched"') == 3, (
        "the population of literal-matched sites changed; re-read them and decide whether the "
        "new one passes an engine payload through unexamined"
    )


# ── the instrument scores it, without disturbing the ruling next door ────────

def _route_decision(status, verb):
    return {"event": "route_decision", "data": {
        "action": {"iri": verb},
        "handled_by": {"endpoint_url": "http://iagent-engine-docs:8093/explain"},
        "route_status": status, "fallback": False,
    }}


def _result(status, components, row=None):
    """A routed answer, with the verb DERIVED FROM THE ROW rather than typed here.

    ⚠ NOT A CLAIM ABOUT THE LIVE VERB SPELLING, and deliberately so. `mesh_explain` appears only
    in the sheet and the census file — nowhere in code — because `mesh:explain` is not yet in Jena,
    so the four docs rows currently fail upstream of this with `no_match` / `no_compatible_verbs`
    and `verb ['UNKNOWN','unknown']` (measured 2026-09-26, three fires). Whether the registered
    IRI's local name will snake to `mesh_explain` or to plain `explain` is undecided and is Lane
    1's to settle when it builds the pool leg — see the report. Deriving the fixture's IRI from
    `row.expect_verb` keeps THIS seal's subject the disposition, and stops it quietly becoming a
    seal on a verb spelling nobody has registered.
    """
    verb = f"mesh:{row.expect_verb}" if row is not None and row.expect_verb else "mesh:explain"
    return {"events": [_route_decision(status, verb)], "final": {"components": components}}


def _doc_card(payload):
    return {"archetype": "KNOWLEDGE_DOCUMENT", "payload": payload}


def test_judge_scores_the_real_abstain_as_abstained(rows):
    """End to end through the instrument, on the SHEET'S OWN ROW and the ENGINE'S OWN payload."""
    row = next(r for r in rows if r.id == _ROW_ID)
    state, why = judge(row, _result(ABSTAINED, [_doc_card(_real_abstain())], row))
    assert state == PASS, f"the designed refusal still fails the census: {why}"


def test_the_same_answer_stamped_matched_is_the_defect_this_fixes(rows):
    """THE PROOF THAT THE FIX IS THE SUPERVISOR'S, not the sheet's.

    Identical card, identical payload, only `route_status` reverted to `matched` — and the row
    fails as `drawn`. This is the measured 2026-09-26 behaviour, preserved as a fixture so the
    defect cannot come back quietly.
    """
    row = next(r for r in rows if r.id == _ROW_ID)
    state, why = judge(row, _result(MATCHED, [_doc_card(_real_abstain())], row))
    assert state == FAIL
    assert "drawn" in " ".join(why), why


def test_the_ruling_still_has_rows_depending_on_it(rows):
    """NON-VACUITY FOR THE ARM BELOW, and a stale-number guard.

    The arm below protects the 2026-09-17 ruling on behalf of the sheet's `slot_required` rows. If
    that population ever empties, the arm defends a path nothing uses and this says so — and the
    count is read from the sheet, so it cannot go stale the way the comment it replaced did.
    """
    keeps = [r.id for r in rows if "slot_required" in r.dispositions]
    assert len(keeps) >= 3, (
        f"only {len(keeps)} row(s) still accept `slot_required` ({keeps}); the arm below is "
        f"defending a ruling nothing in the sheet exercises any more"
    )
    assert _ROW_ID not in keeps, (
        "row 4 still accepts `slot_required`, which is the unreachable claim this change removed"
    )


def test_an_abstain_WITH_candidates_still_scores_slot_required(rows):
    """THE LIVE RULING, 2026-09-17: an abstain that can offer verbs is drawn as a MENU.

    Four sheet rows accept `slot_required` on exactly this path, so the new arm sits BELOW `asked`
    in `judge`. Moving it up would turn all four red, and this is the arm that says so.
    """
    row = next(r for r in rows if r.id == _ROW_ID)
    elicitation = {"archetype": "ELICITATION", "slot": "verb", "option_source": "candidates",
                   "options": [{"verb": "mesh:explain"}, {"verb": "mesh:describeAsset"}]}
    state, why = judge(row, _result(ABSTAINED, [elicitation], row))
    assert state == FAIL, "row 4 accepts only `abstained`; a menu here would be a different answer"
    assert "slot_required" in " ".join(why), (
        f"an abstain carrying a verb menu was not scored as an ask — the ruling is broken: {why}"
    )


def test_a_row_expecting_drawn_still_FAILS_on_an_abstain(rows):
    """THE NON-HIDING CONTROL.

    `judge` no longer names `abstained` in its unexpected-route_status reason, which is exactly
    the kind of suppression that quietly turns a red green. It does not here: a row that wants a
    real answer and receives a refusal still fails, on the disposition line. If this ever passes,
    the suppression has started hiding something.
    """
    row = next(r for r in rows if r.id != _ROW_ID and "drawn" in r.dispositions and r.expect_verb)
    state, why = judge(row, _result(ABSTAINED, [_doc_card(_real_abstain())], row))
    assert state == FAIL, f"an abstain passed a row that demands a drawn answer: {row.id}"
    assert "abstained" in " ".join(why), (
        f"the failure never mentions the abstain, so the reader cannot tell a refusal from an "
        f"empty card — which is the original defect wearing a red: {why}"
    )


def test_an_unknown_route_status_is_still_reported(rows):
    """NON-VACUITY FOR THE ARM ABOVE: the unexpected-status line still fires for other values,
    so adding `abstained` to its accepted set widened one word and not the check."""
    row = next(r for r in rows if r.id == _ROW_ID)
    _, why = judge(row, _result("infra_error", [_doc_card({})], row))
    assert "route_status='infra_error'" in " ".join(why), why


# ── the vocabulary and the sheet ─────────────────────────────────────────────

def test_abstained_is_in_the_census_vocabulary():
    assert ABSTAINED in DISPOSITIONS


def test_the_sheet_row_asserts_the_claim_and_not_its_neighbour():
    """Row 4 said `[slot_required]`, which was UNREACHABLE for it: its subject is a doc-corpus
    gap, there are no comparable verbs to offer, and `presentation_agent` refuses to draw an empty
    menu. A row whose accepted disposition cannot occur is a row asserting a neighbour."""
    doc = yaml.safe_load(_CENSUS_PATH.read_text(encoding="utf-8"))
    row = next(r for r in doc["rows"] if r["id"] == _ROW_ID)
    assert row["dispositions"] == [ABSTAINED]


def test_the_legend_no_longer_documents_a_name_the_code_rejects():
    """The sheet's legend listed `task_created` — the one name the vocabulary's own docstring says
    it is NOT, "and the name is the whole point" — and omitted `task_requested` entirely. A stale
    legend is pre-authenticated: it was written by someone who knew, so it reads as current."""
    head = _CENSUS_PATH.read_text(encoding="utf-8").split("version: 1")[0]
    for name in DISPOSITIONS:
        assert name in head, f"the legend never explains {name!r} to whoever writes the next row"
    assert not re.search(r"^#\s+task_created\s", head, re.M), (
        "the legend still defines `task_created` as a disposition; the runner reads the artifact "
        "and cannot see the human_tasks row, which is why the name was rejected"
    )


def test_the_catch_all_guard_still_refuses_the_whole_vocabulary(tmp_path):
    """Widening `DISPOSITIONS` makes the proper-subset guard CHEAPER, and its own seal cannot see
    that, because it builds its catch-all from `list(DISPOSITIONS)`. The guard is re-asserted here
    at the widened vocabulary so the widening is at least measured once.
    """
    doc = yaml.safe_load(_CENSUS_PATH.read_text(encoding="utf-8"))
    doc["rows"][0]["dispositions"] = list(DISPOSITIONS)
    p = tmp_path / "permissive.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(CensusError, match="asserts nothing"):
        load_rows(p)


def test_no_row_leans_on_the_slack_the_widening_created(rows):
    """THE REACH THE GUARD LOST, named. Before `abstained`, a row accepting the other three was
    refused as vacuous; now it loads. No row does that today, and this arm is what notices if one
    starts — a row accepting three of four asserts only "not an abstain"."""
    slack = [r.id for r in rows if len(set(r.dispositions)) >= len(DISPOSITIONS) - 1]
    assert not slack, (
        f"row(s) {slack} accept nearly the whole vocabulary, which the proper-subset guard used "
        f"to refuse and no longer does. Name the one disposition that is correct."
    )


# ── the knock-on, asserted rather than discovered later ──────────────────────

def test_an_abstaining_subtask_yields_primacy_to_one_that_answered():
    """`pick_primary` selects the first MATCHED subtask, so changing this status changes which
    card renders on a multi-subtask turn. That is the behaviour we want — prefer the sibling that
    answered — but it is a consequence, so it is sealed rather than left to be found."""
    abstained = {"route_status": ABSTAINED}
    answered = {"route_status": MATCHED}
    assert pick_primary([abstained, answered], lambda r: r["route_status"]) is answered


def test_a_lone_abstaining_subtask_still_renders():
    """AND THE CASE EVERY DOCS CENSUS ROW ACTUALLY IS: one subtask, nothing matched. The fallback
    returns that same item, so a single-question turn is unchanged by the status flip."""
    only = {"route_status": ABSTAINED}
    assert pick_primary([only], lambda r: r["route_status"]) is only


# ── the guard a comment can demote ───────────────────────────────────────────

def test_no_subtask_return_is_outside_the_neighbouring_seals_window():
    """MEASURED ON MY OWN EDIT. `_result_dicts_missing_status` finds each subtask return by
    searching back 1400 characters from `"expert_response"` for its `return {`. The first draft of
    this change wrote fifteen lines of rationale INSIDE that dict, which pushed the site past the
    window; `rfind` returned -1, the helper `continue`d, and the seal passed while checking one
    site fewer. A guard whose reach a comment can shrink needs the reach asserted.
    """
    skipped = []
    for m in re.finditer(r'"expert_response"\s*:', _SUP):
        if _SUP.rfind("return {", max(0, m.start() - 1400), m.start()) == -1:
            skipped.append(_SUP[:m.start()].count("\n") + 1)
    assert not skipped, (
        f"subtask return(s) at line(s) {skipped} are further than 1400 characters from their "
        f"`return {{`, so test_every_subtask_result_carries_a_routing_status silently skips them. "
        f"Move the prose above the return; do not widen the window."
    )
