"""A human_await CARD STATES WHAT EACH CHOICE LEADS TO, derived from the chaining table.

THE DEFECT. `maint_fault_propose`'s `decide` card said "Choosing one approves it". Its chaining
table routes `evacuate_for_depot` (always) and `replace_now` (on a mission-essential asset) to
`maint_supervisor_review`, a SECOND approval. The card claimed a finality the walk refuses.

THE RULING. The text comes from the declarations. The supervisor rule keeps its one home, the
chaining table; `case_routing.verb_consequences` reads it and `main._choice_consequence_text`
renders it. Nothing here restates which verb needs a supervisor except as a CONTROL against the
table the code read.

Run: uv run pytest tests/routing/test_card_states_each_choice_consequence.py -v
"""
from __future__ import annotations

import copy

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import R, main, restate, wd
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- autouse fixtures
    DECIDE, OPTION_VERBS, _declared_walk_double, _event, _real_policy, _run)

DEF = "maint_fault_propose"
ME = "picture.battle_condition.mission_essential"
SUPERVISOR, RELEASE = "maint_supervisor_review", "maint_release"
STALE = "Choosing one approves it"


def _by_verb(rows):
    return {r["verb"]: r for r in rows}


def _step(def_id=DEF, step_id="decide"):
    return next(s for s in wd.get_workflow_definition(def_id).steps if s.id == step_id)


def _name(def_id):
    return wd.get_workflow_definition(def_id).name


# -- a. the real tables ----------------------------------------------------------------------

def test_A_THE_REAL_TABLE_SAYS_WHICH_CHOICES_NEED_A_SUPERVISOR():
    got = _by_verb(R.verb_consequences(DEF, OPTION_VERBS, {}))
    assert list(got) == OPTION_VERBS, list(got)
    assert got["evacuate_for_depot"] == {
        "verb": "evacuate_for_depot", "then": [SUPERVISOR], "conditional": False}, got
    for v in ("replace_after_resupply", "defer_with_restriction"):
        assert got[v]["then"] == [RELEASE] and not got[v]["conditional"], got[v]
    rn = got["replace_now"]
    assert rn["conditional"] is True, rn
    assert {leg["then"] for leg in rn["then"]} == {SUPERVISOR, RELEASE}, rn


def test_A_A_CHANGED_TABLE_CHANGES_THE_ANSWER_THE_TEXT_IS_DERIVED_NOT_TYPED():
    index = copy.deepcopy(R.chaining_index())
    for row in index[DEF]["rows"]:
        if row["when"].get("outcome") == "evacuate_for_depot":
            row["then"] = RELEASE
    got = _by_verb(R.verb_consequences(DEF, OPTION_VERBS, {}, index=index))
    assert got["evacuate_for_depot"]["then"] == [RELEASE], got["evacuate_for_depot"]


def test_A_NO_TABLE_OR_NO_OUTCOME_COLUMN_IS_EMPTY():
    assert R.verb_consequences("no_such_definition", ["x"], {}) == []
    idx = {"d": {"decision": "t", "after": "d", "matches": ["other"], "rows": []}}
    assert R.verb_consequences("d", ["x"], {}, index=idx) == []


# -- b. the picture decides replace_now ------------------------------------------------------

@pytest.mark.parametrize("me, target", [(True, SUPERVISOR), (False, RELEASE)])
def test_B_REPLACE_NOW_FOLLOWS_THE_PICTURE_WHEN_IT_IS_KNOWN(me, target):
    rn = _by_verb(R.verb_consequences(DEF, OPTION_VERBS, {ME: me}))["replace_now"]
    assert rn == {"verb": "replace_now", "then": [target], "conditional": False}, rn


# -- c. the renderer on the real registry definition -----------------------------------------

def test_C_THE_CARD_NAMES_THE_SUPERVISOR_REVIEW_FOR_AN_EVACUATION():
    text = main._choice_consequence_text(DEF, _step(), {})
    assert text, text
    sup = _name(SUPERVISOR)
    sentence = next(s for s in text.split(".") if "evacuate_for_depot" in s)
    assert sup in sentence, (sentence, sup)
    assert _name(RELEASE) in text and ME in text, text   # the conditional verb states its condition


def test_C_THE_CONSTANT_NO_LONGER_CLAIMS_FINALITY():
    step = _step()
    assert STALE not in (step.summary or ""), step.summary
    composed = main._compose_summary(step.summary, main._choice_consequence_text(DEF, step, {}))
    assert STALE not in composed and "evacuate_for_depot" in composed, composed


@pytest.mark.parametrize("me", [True, False])
def test_C_WITH_THE_PICTURE_KNOWN_REPLACE_NOW_NAMES_ONE_TARGET(me):
    text = main._choice_consequence_text(DEF, _step(), {ME: me})
    want = _name(SUPERVISOR if me else RELEASE)
    sentence = next(s for s in text.split(".") if "replace_now" in s)
    assert want in sentence and ME not in sentence, sentence


# -- d. an approved verb no row routes is refused --------------------------------------------

def test_D_AN_UNROUTED_APPROVED_VERB_IS_A_422_NOT_A_HIDDEN_CARD(monkeypatch):
    idx = copy.deepcopy(R.chaining_index())
    idx[DEF]["rows"] = [r for r in idx[DEF]["rows"]
                        if r["when"].get("outcome") != "defer_with_restriction"]
    monkeypatch.setattr(R, "chaining_index", lambda tables=None: idx)
    with pytest.raises(restate.TerminalError) as ei:
        main._choice_consequence_text(DEF, _step(), {})
    assert ei.value.status_code == 422 and "defer_with_restriction" in str(ei.value), ei.value


# -- e. the class: every approving step that a chaining table follows ------------------------

def _population():
    index = R.chaining_index()
    out = []
    for d in wd.definition_dirs():
        for path in sorted(d.glob("*.yaml")):
            try:
                definition = wd.load_workflow_definition(path)
            except Exception:  # noqa: BLE001 -- not a workflow definition
                continue
            for s in definition.steps:
                if (s.kind == "human_await" and s.approves and definition.id in index
                        and "outcome" in (index[definition.id].get("matches") or [])):
                    out.append((definition.id, s))
    return out


def test_E_EVERY_APPROVING_STEP_FOLLOWED_BY_A_TABLE_STATES_EVERY_VERB():
    pop = _population()
    print(f"population: {len(pop)} approving human_await steps followed by a chaining table: "
          f"{[(d, s.id) for d, s in pop]}")
    assert len(pop) >= 1, "the population is empty: this arm would pass over nothing"
    assert DEF in [d for d, _ in pop], pop
    for def_id, step in pop:
        text = main._choice_consequence_text(def_id, step, {})
        assert text, (def_id, step.id)
        accepts = main._kind_accepts(step.task_kind)
        for v in step.approves:
            if accepts is None or v in accepts:
                assert v in text, (def_id, step.id, v, text)


# -- f. the registration path ----------------------------------------------------------------

@pytest.fixture
def tasks(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack", case_id=None: rows.append(
                            (wf, task, kind)) or {})
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("me", [True, False])
async def test_F_THE_REGISTERED_TASK_CARRIES_THE_DERIVED_TEXT(tasks, me):
    await _run(_event(me=me), [(DECIDE, "replace_after_resupply")])
    [(wf, task, kind)] = [t for t in tasks if t[2] == "maint_fault_approval"][:1]
    summary = task["summary"]
    assert STALE not in summary, summary
    assert "Reject sends it back" in summary, summary           # the bound constant survives
    assert "Evacuate for depot" in summary and _name(SUPERVISOR) in summary, summary
    rn = next(s for s in summary.split(".") if "Replace now" in s)
    assert (_name(SUPERVISOR) if me else _name(RELEASE)) in rn, rn
