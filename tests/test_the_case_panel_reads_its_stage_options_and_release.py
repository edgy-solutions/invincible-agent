"""The case panel reads its stage, its options and its release (0.4.72).

`GET /cases/{case_id}` used to emit `current_stage=None`, `options=[]` and `output_artifact=None`
for every case, and cortex rendered those absences as defects. Each field now has ONE declared
source, and where the source says nothing the field is ABSENT -- never guessed, never `[]`:

  * `current_stage`: a step may declare the stage it begins (`stage:`), admitted only where this
    read-only route can observe the beginning (step 0, or a non-grouped human_await with a row).
  * `options`: the decide task is registered carrying `payload.options`, resolved from the step's
    `chooses_from` -- PURELY, with no journalled call added (replay-safe).
  * `output_artifact`: the newest ActionRecord, `released_at` = its `valid_as_of`; an unreadable
    store is a 503, never a null.

Arms: s1-s6 stage, o1-o5 options, a1-a4 artifact.

Run: uv run --frozen pytest tests/test_the_case_panel_reads_its_stage_options_and_release.py -v
"""
from __future__ import annotations

import copy
import datetime as _dt
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

# One cluster double, the case runner's own; one route double, the cases route's own.
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402
    _Cluster, _answer, main, wd)
from tests.test_cases_route import (  # noqa: E402,F401
    _FakeRestate, _user, client_for)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: E402,F401
    DECIDE, OPTION_VERBS, REVIEW, _declared_walk_double, _event, _options, _real_policy,
    _run)

from src.iagent import case_projection, gateway  # noqa: E402

_WF = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "openddil-lab" / "workflows"


def _load(name):
    return wd.load_workflow_definition(_WF / f"{name}.yaml")


PROPOSE = _load("maint_fault_propose")
RELEASE = _load("maint_release")
SUPERVISOR = _load("maint_supervisor_review")
DEFS = {d.id: d for d in (PROPOSE, RELEASE, SUPERVISOR, _load("maint_fault_park"),
                          _load("maint_fault_escalate"))}

OPTIONS = [
    {"verb": "replace_now", "label": "Replace now", "readiness": "FMC", "spares": []},
    {"verb": "defer_with_restriction", "readiness": "PMC"},
    {"label": "no verb: skipped"},
    {"verb": 7, "label": "non-string verb: skipped"},
]


def _case(*defs, status="running"):
    insts = [{"n": i, "instance_id": f"c-1~{i}", "definition_id": d}
             for i, d in enumerate(defs, start=1)]
    case = {"case_id": "c-1", "instances": insts, "transitions": [], "state": None,
            "terminal": None}
    if status == "completed":
        case["terminal"] = "closed"
    elif status == "failed":
        case["state"] = "failed"
    return case


def _row(wf, step, *, status="pending", options=None):
    row = {"task_id": f"{wf}:{step}", "workflow_id": wf, "status": status, "decision": None,
           "acted_by": None, "acted_at": None, "comment": ""}
    if options is not None:
        row["payload"] = {"options": options}
    else:
        row["payload"] = {}
    return row


def _stage(case, rows):
    return case_projection.project_instances(case, DEFS, rows)[-1]["current_stage"]


# ── STAGE ───────────────────────────────────────────────────────────────────────────────────

def test_s1_a_proposal_with_its_decide_row_is_awaiting_approval():
    assert _stage(_case("maint_fault_propose"),
                  [_row("c-1~1", "decide")]) == "awaiting_approval"
    # a DECIDED row means the await began too
    assert _stage(_case("maint_fault_propose"),
                  [_row("c-1~1", "decide", status="decided")]) == "awaiting_approval"


def test_s2_a_proposal_with_no_decide_row_yet_is_proposed():
    assert _stage(_case("maint_fault_propose"), []) == "proposed"
    # another instance's row is not this instance's await
    assert _stage(_case("maint_fault_propose"), [_row("c-9~1", "decide")]) == "proposed"


@pytest.mark.parametrize("status", ["running", "failed", "completed"])
def test_s3_a_single_stage_definition_is_that_stage_for_any_status(status):
    assert _stage(_case("maint_supervisor_review", status=status), []) == "awaiting_supervisor"


def test_s4_a_release_is_released_while_running_and_closed_when_completed():
    assert _stage(_case("maint_release", status="completed"), []) == "closed"
    assert _stage(_case("maint_release", status="running"), []) == "released"


def test_s5_two_stages_and_no_declaration_is_never_guessed():
    d = wd.WorkflowDefinition.model_validate({
        "id": "two_stage", "name": "two", "domain_stages": ["a", "b"],
        "steps": [{"kind": "wait", "id": "w", "seconds": 5}]})
    case = {"case_id": "c-1", "state": None, "terminal": None, "transitions": [],
            "instances": [{"n": 1, "instance_id": "c-1~1", "definition_id": "two_stage"}]}
    got = case_projection.project_instances(case, {"two_stage": d}, [])
    assert got[0]["current_stage"] is None


def _defn(steps, stages=("a", "b")):
    return {"id": "d", "name": "d", "domain_stages": list(stages), "steps": steps}


_AWAIT = {"kind": "human_await", "id": "h", "audience": "x:y"}


def test_s6_the_model_refuses_a_stage_it_cannot_honour():
    ok = wd.WorkflowDefinition.model_validate(_defn([
        {"kind": "wait", "id": "w", "seconds": 5, "stage": "a"}, dict(_AWAIT, stage="b")]))
    assert ok.steps[0].stage == "a"
    with pytest.raises(Exception, match="not in domain_stages"):
        wd.WorkflowDefinition.model_validate(_defn([
            {"kind": "wait", "id": "w", "seconds": 5, "stage": "nope"}]))
    with pytest.raises(Exception, match="cannot be observed"):
        wd.WorkflowDefinition.model_validate(_defn([
            {"kind": "wait", "id": "w", "seconds": 5},
            {"kind": "render", "id": "r", "template": {}, "stage": "a"}]))
    with pytest.raises(Exception, match="cannot be observed"):
        wd.WorkflowDefinition.model_validate(_defn([
            {"kind": "wait", "id": "w", "seconds": 5},
            dict(_AWAIT, stage="a", completion={"mode": "grouped"})]))
    # the field is still refused where it is not declared at all
    with pytest.raises(Exception):
        wd.WorkflowDefinition.model_validate(_defn([
            {"kind": "wait", "id": "w", "seconds": 5, "stagee": "a"}]))
    # the overlay definitions load, with the declarations the panel reads
    assert [s.stage for s in PROPOSE.steps] == ["proposed", None, "awaiting_approval"]
    assert [s.stage for s in RELEASE.steps] == ["released"]
    assert SUPERVISOR.domain_stages == ["awaiting_supervisor"]


# ── OPTIONS ─────────────────────────────────────────────────────────────────────────────────

def test_o1_a_decide_row_carrying_options_yields_case_options_in_order():
    out = case_projection.project_workflow_case(
        _case("maint_fault_propose"), DEFS, [_row("c-1~1", "decide", options=OPTIONS)])
    assert out["options"] == [
        {"id": "replace_now", "label": "Replace now",
         "data": {"readiness": "FMC", "spares": []}, "artifact_uri": None},
        {"id": "defer_with_restriction", "label": "defer_with_restriction",
         "data": {"readiness": "PMC"}, "artifact_uri": None},
    ]


def test_o2_no_row_carrying_options_omits_the_key():
    out = case_projection.project_workflow_case(
        _case("maint_fault_propose"), DEFS, [_row("c-1~1", "decide")])
    assert "options" not in out
    assert "options" not in case_projection.project_workflow_case(
        _case("maint_fault_propose"), DEFS, [])


def test_o3_two_proposals_read_the_latest_ones_options():
    first = [{"verb": "old_one"}]
    second = [{"verb": "new_one"}]
    rows = [_row("c-1~1", "decide", status="decided", options=first),
            _row("c-1~3", "decide", options=second)]
    out = case_projection.project_workflow_case(
        _case("maint_fault_propose", "maint_supervisor_review", "maint_fault_propose"),
        DEFS, rows)
    assert [o["id"] for o in out["options"]] == ["new_one"]


# ── TITLES: a step is never labelled with a raw placeholder ─────────────────────────────────

def _step_of(case, rows, step_id, definitions=None):
    got = case_projection.project_instances(case, definitions or DEFS, rows)[-1]
    return next(st for st in got["definition"]["steps"] if st["id"] == step_id)


def _templated(title=None, audience="a:b"):
    return {"d": wd.WorkflowDefinition.model_validate({
        "id": "d", "name": "d", "domain_stages": ["a"],
        "steps": [{"kind": "human_await", "id": "h", "audience": audience, "title": title}]})}


_ONE = {"case_id": "c-1", "state": None, "terminal": None, "transitions": [],
        "instances": [{"n": 1, "instance_id": "c-1~1", "definition_id": "d"}]}


def test_t1_a_registered_title_is_the_steps_title():
    rows = [dict(_row("c-1~1", "h"), title="Fault X on A: choose")]
    assert _step_of(_ONE, rows, "h", _templated("Fault {trigger.x}"))["title"] == \
        "Fault X on A: choose"


def test_t2_an_unrendered_title_with_no_row_is_none():
    assert _step_of(_ONE, [], "h", _templated("Fault {trigger.x}"))["title"] is None


def test_t3_a_plain_title_with_no_row_is_unchanged():
    assert _step_of(_ONE, [], "h", _templated("Choose"))["title"] == "Choose"


def test_t4_a_templated_audience_is_none():
    assert _step_of(_ONE, [], "h", _templated("T", "maint:{trigger.tier}"))["audience"] is None
    assert _step_of(_ONE, [], "h", _templated("T", "maint:ORG"))["audience"] == "maint:ORG"


# ── THE RUNNER: registration carries the options, and journals nothing new ──────────────────

@pytest.fixture
def tasks(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        main, "_register_human_task",
        lambda wf, task, kind="workflow_ack", case_id=None: seen.append(
            (wf, copy.deepcopy(task))) or {})
    return seen


@pytest.mark.asyncio
async def test_o4_registration_carries_the_resolved_options_only_when_declared(tasks):
    _, c = await _run(_event(), [(DECIDE, "evacuate_for_depot"), (REVIEW, "rejected", "s@x"),
                                 (DECIDE, "replace_after_resupply", "m2@x")])
    decide = [t for wf, t in tasks if t["id"].endswith(":decide")]
    review = [t for wf, t in tasks if t["id"].endswith(":review")]
    assert decide and review
    carried = _options(c)  # the first proposal's options, as the case carried them on
    assert [o["verb"] for o in carried] == OPTION_VERBS
    assert decide[0]["payload"] == {"options": carried}, decide[0]
    for t in decide:
        assert [o["verb"] for o in t["payload"]["options"]] == OPTION_VERBS, t
    for t in review:
        assert "payload" not in t, t


def _journal(c, key):
    ctx = c.ctx(key)
    return list(ctx.runs), sorted(ctx.state)


async def _first_instance(event, verb):
    """Drive the case and return its cluster. The case may fail in a LATER instance (stripping
    `chooses_from` leaves the release with no `chosen.verb` to cite); only instance 1 is read."""
    c = _Cluster({(f"{event['event_id']}~1", DECIDE): _answer(verb, "m@x", "because")})
    try:
        await c.start(event["event_id"], "maintenance_fault", copy.deepcopy(event))
    except Exception:  # noqa: BLE001
        pass
    return c


@pytest.mark.asyncio
async def test_o5_resolving_the_options_adds_no_journalled_call(tasks, monkeypatch):
    ev = _event()
    with_options = await _first_instance(ev, "replace_after_resupply")

    real = wd.get_workflow_definition

    def _without(workflow_id):
        d = real(workflow_id)
        if workflow_id != "maint_fault_propose":
            return d
        steps = [s.model_copy(update={"chooses_from": None}) if s.id == "decide" else s
                 for s in d.steps]
        return d.model_copy(update={"steps": steps})
    monkeypatch.setattr(wd, "get_workflow_definition", _without)
    tasks.clear()
    without = await _first_instance(ev, "replace_after_resupply")
    decide = [t for _, t in tasks if t["id"].endswith(":decide")]
    assert decide and all("payload" not in t for t in decide)

    runs, state = _journal(with_options, "EV-1~1")
    assert any(r.startswith("register_decide") for r in runs), runs
    assert (runs, state) == _journal(without, "EV-1~1")


# ── THE ARTIFACT ────────────────────────────────────────────────────────────────────────────

_RELEASE_CASE = {
    "case_id": "c-1",
    "instances": [{"n": 1, "instance_id": "c-1~1", "definition_id": "maint_release"}],
    "transitions": [], "state": "closed", "terminal": "closed",
}
_SPEC1 = {"trigger": {"domain_type": "MAINT", "dropped_by": {"authz_id": "alice"}}}
_T0, _T1 = 1_760_000_000_000, 1_760_000_500_000


def _rec(artifact_id, valid_as_of):
    return {"artifact_id": artifact_id, "seeded_by": "alice", "valid_as_of": valid_as_of,
            "record": {"action_id": artifact_id}}


def _iso(ms):
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).isoformat()


def _get(client_for, monkeypatch, case, reader):
    monkeypatch.setattr(gateway, "_read_action_records", reader)
    c = client_for(_user("alice"), _FakeRestate(case=case, spec1=_SPEC1),
                   get_definition=lambda wf_id: DEFS[wf_id])
    return c.get("/cases/c-1")


def test_a1_a_released_case_names_its_action_record_and_when_it_was_written(
        client_for, monkeypatch):
    resp = _get(client_for, monkeypatch, _RELEASE_CASE,
                lambda cid: [_rec("old", _T0), _rec("new", _T1)])
    assert resp.status_code == 200, resp.text
    assert resp.json()["output_artifact"] == {
        "uri": "/cases/c-1/action", "label": "Maintenance action record",
        "released_at": _iso(_T1)}


def test_a2_a_release_with_no_record_is_not_released(client_for, monkeypatch):
    resp = _get(client_for, monkeypatch, _RELEASE_CASE, lambda cid: [])
    assert resp.status_code == 200, resp.text
    assert resp.json()["output_artifact"] is None


def test_a3_a_case_with_no_emit_step_never_reads_the_store(client_for, monkeypatch):
    calls: list = []
    case = {"case_id": "c-1", "state": None, "terminal": None, "transitions": [],
            "instances": [{"n": 1, "instance_id": "c-1~1",
                           "definition_id": "maint_fault_propose"}]}
    resp = _get(client_for, monkeypatch, case, lambda cid: calls.append(cid) or [])
    assert resp.status_code == 200, resp.text
    assert resp.json()["output_artifact"] is None
    assert calls == []


def test_a4_an_unreadable_store_is_a_503_not_a_null(client_for, monkeypatch):
    def _boom(cid):
        raise RuntimeError("neo4j down")
    resp = _get(client_for, monkeypatch, _RELEASE_CASE, _boom)
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == {"error": "artifact_store_unavailable"}


# ── LABELS: the derived sentence names a verb as its button reads ───────────────────────────

def test_l1_the_consequence_sentence_uses_labels_when_known():
    step = PROPOSE.steps[-1]
    facts = {"mission_essential": False}
    plain = main._choice_consequence_text("maint_fault_propose", step, facts)
    assert "replace_now" in plain and "Replace now" not in plain, plain
    labelled = main._choice_consequence_text(
        "maint_fault_propose", step, facts,
        {"replace_now": "Replace now", "evacuate_for_depot": "Evacuate for depot"})
    assert "Replace now" in labelled and "Evacuate for depot" in labelled, labelled
    assert "replace_now" not in labelled and "evacuate_for_depot" not in labelled, labelled
    # a verb with no label is still spelled as its id
    assert "defer_with_restriction" in main._choice_consequence_text(
        "maint_fault_propose", step, facts, {"replace_now": "Replace now"})
