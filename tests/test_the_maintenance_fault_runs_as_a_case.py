"""The maintenance fault workflow runs as a CASE through the generic runner, from the overlay.

Dispatch B's second YAML: received -> triaged -> proposed (the S1000D walk, stubbed until 7f Phase
2(e)) -> awaiting approval -> released -> closed on the owning tier's ack, with a supervisor's
second approval when the chosen option yields NMC or takes a mission-essential asset offline,
reject back to proposed, defer to a parked revisit, and an unanswered approval escalating rather
than approving.

EVERYTHING IS IN `policy/overlays/openddil-lab/`; NOTHING MAINTENANCE-SPECIFIC IS IN PYTHON. Every
arm reads the REAL policy tree -- no env override, no tmp rows -- because the claim is about what
the overlay routes. The one Python change S6 needed is generic and has its own arm here:
`test_A_REOPENED_CASE_STARTS_A_NEW_APPROVAL_CHAIN`.

Run: uv run --frozen pytest tests/test_the_maintenance_fault_runs_as_a_case.py -v
"""
from __future__ import annotations

import copy

import pytest

# One cluster double, the case runner's own -- not a second one free to drift from it.
from tests.test_a_case_runs_from_trigger_to_terminal import R, _answer, _Cluster, main, restate

TRIGGER = "maintenance_fault"
OPTION_VERBS = ["replace_now", "replace_after_resupply", "defer_with_restriction",
                "evacuate_for_depot"]

#: An answer that never comes: the await's deadline wins the race.
EXPIRE = object()


@pytest.fixture(autouse=True)
def _real_policy(monkeypatch):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)

    async def _select(**arms):
        # The deadline race. The scripted answer decides which arm won; the loser is closed so no
        # coroutine is left un-awaited.
        value = await arms["approved"]
        arms["expired"].close()
        return ("expired", None) if value is EXPIRE else ("approved", value)
    monkeypatch.setattr(restate, "select", _select)


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (wf, task["audience"], kind)) or {})
    return rows


def _event(event_id="EV-1", me=False, kind="cm_discrepancy"):
    """A MaintenanceEvent in the week-1 bridge contract's shape, with `battle_condition` in the
    shape OpenDDIL answered on 2026-10-02: a boolean `mission_essential` and its `basis`."""
    return {
        "event_id": event_id, "kind": kind, "asset_id": "AST-7", "owning_tier": "ORG",
        "fault": {"item": "fuel-pump", "fault_code": "F-0417",
                  "observed_at": "2026-10-02T00:00:00Z"},
        "sources": [{"system": "bit"}],
        "picture": {"readiness": "PMC", "factors": ["fuel"], "lifecycle": "in_service",
                    "spare": {"on_hand_here": 0, "nearest_site_with_stock": "SITE-B",
                              "as_of": "2026-10-01T00:00:00Z"},
                    "battle_condition": {
                        "mission_essential": me,
                        "basis": {"rule": "readiness-rollup:ORG",
                                  "observed_at": "2026-10-01T06:00:00Z"}}},
        "label": {"originator_nation": "AA", "releasable_to": ["AA", "BB"]},
        "provenance": [],
    }


async def _run(event, answers):
    """Drive one case. `answers` is one entry per INSTANCE, in order: ``None`` for an instance
    that takes no answer (the parked wait), else ``(promise, verb)`` or ``(promise, verb, who)``,
    with ``EXPIRE`` as the verb for an approval nobody gave."""
    key = event["event_id"]
    scripted = {}
    for n, a in enumerate(answers, start=1):
        if a is None:
            continue
        promise, verb, who = (*a, "m@x") if len(a) == 2 else a
        scripted[(f"{key}~{n}", promise)] = (
            EXPIRE if verb is EXPIRE else _answer(verb, who, f"because {n}"))
    c = _Cluster(scripted)
    try:
        out = await c.start(key, TRIGGER, copy.deepcopy(event))
    except Exception as exc:  # noqa: BLE001 -- a case that did not CLOSE is the arm's red
        raise AssertionError(
            f"the case ended in {type(exc).__name__}: {exc}; case={c.case(key)}") from exc
    return out, c


def _path(out):
    """The hops after intake: (from, outcome, to)."""
    return [(t["from"], t["outcome"], t["to"]) for t in out["transitions"]][2:]


def _emitted(c):
    """Every ActionRecord the case emitted, across all of its instances."""
    return [e["record"] for k, ctx in sorted(c.ctxs.items())
            for e in ctx.state.get("outbox:maintenance_action") or []]


def _options(c, key="EV-1"):
    """The four options the first proposal rendered, as the case carried them to instance 2."""
    return c.ctx(key).state["instance:2"]["outputs"]["maint_fault_propose"]["options"]


DECIDE, REVIEW, ESCALATION, ACK = ("approval_decide", "approval_review", "approval_escalation",
                                   "tier_ack")


# ── INTAKE ──────────────────────────────────────────────────────────────────────────────────

def test_THE_TRIGGER_IS_DECLARED_AND_ONLY_A_DISCREPANCY_OPENS_A_PROPOSAL():
    t = R.load_triggers()[TRIGGER]
    assert (t.key, t.episode) == ("event_id", ["asset_id", "fault.item", "fault.fault_code"]), t
    flat = R.flatten(_event())
    R.check_intake(t, flat, "EV-1")
    assert R.select(t, flat)["then"] == "maint_fault_propose"
    with pytest.raises(R.CaseRoutingError, match="lifecycle_transition"):
        R.select(t, R.flatten(_event(kind="lifecycle_transition")))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [("mission_essential",), ("basis", "rule"),
                                  ("basis", "observed_at")])
async def test_AN_EVENT_WITHOUT_MISSION_ESSENTIAL_OR_ITS_BASIS_IS_REFUSED_AT_INTAKE(registered,
                                                                                 path):
    """Absent is not `false`: a default would skip the supervisor for exactly the assets the rule
    protects. A verdict without the rule and time it was decided under is refused the same way."""
    ev = _event()
    node = ev["picture"]["battle_condition"]
    for seg in path[:-1]:
        node = node[seg]
    del node[path[-1]]
    dotted = r"picture\.battle_condition\." + r"\.".join(path)
    with pytest.raises(AssertionError, match=dotted):
        await _run(ev, [])
    assert registered == [], registered


@pytest.mark.asyncio
async def test_THE_PRE_ANSWER_SPELLING_AT_THE_PICTURE_ROOT_IS_NOT_READ(registered):
    """CONTROL ON THE PATH. An event carrying `picture.mission_essential` (the field asked for
    before OpenDDIL placed it) and no `battle_condition` must not open a proposal: the rule reads
    only the answered path, so the old spelling would otherwise be honoured by nothing."""
    ev = _event()
    ev["picture"]["mission_essential"] = True
    del ev["picture"]["battle_condition"]
    with pytest.raises(AssertionError, match=r"picture\.battle_condition\.mission_essential"):
        await _run(ev, [])
    assert registered == [], registered


# ── THE OPTIONS ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_EXACTLY_FOUR_OPTIONS_IN_ORDER_EACH_CITING_THE_MANUAL_AND_THE_SPARES(registered):
    ev = _event()
    _, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    opts = _options(c)
    assert [o["verb"] for o in opts] == OPTION_VERBS, opts
    assert [o["readiness"] for o in opts] == ["FMC", "PMC", "PMC", "NMC"], opts
    for o in opts:
        assert o["task_refs"] and all("data_module_code" in r for r in o["task_refs"]), o
        assert o["spares"] == ev["picture"]["spare"], o
    # THE WALK IS A STUB AND ITS CODES ARE NULL: an invented DMC would be cited on a work order.
    assert {r["data_module_code"] for o in opts for r in o["task_refs"]} == {None}, opts
    assert opts[1]["parts"][0]["source_site"] == "SITE-B", opts[1]
    # THE SUPERVISOR-DEPENDENT OPTION CITES THE VERDICT AND ITS BASIS, raw, not a restatement.
    assert opts[0].get("battle_condition") == ev["picture"]["battle_condition"], opts[0]
    assert opts[0]["battle_condition"]["basis"]["rule"] == "readiness-rollup:ORG", opts[0]


# ── THE PATHS ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_RESUPPLY_IS_RELEASED_AND_CLOSED_ON_THE_TIER_ACK(registered):
    ev = _event()
    out, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "replace_after_resupply", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)
    # A SIGNAL REGISTERS NO HUMAN ROW: one task, the maintainer's.
    assert registered == [("EV-1~1", "maint_fault_approval:ORG", "maint_fault_approval")], (
        registered)
    [rec] = _emitted(c)
    assert rec["work_order"]["option"] == "replace_after_resupply", rec
    assert rec["label"] == ev["label"] and rec["event_id"] == "EV-1", rec
    assert [(e["role"], e["approver_sub"]) for e in rec["approval_chain"]] == [
        ("maintainer", "m@x")], rec["approval_chain"]
    prov = rec["provenance"]
    # RULED: the case definition AND the emitter, both fields; the workflow_* spellings are the
    # week-1 contract's, which named `workflow_definition_version` / `workflow_instance_id`.
    assert prov.get("case_definition") == TRIGGER and prov.get("case_id") == "EV-1", prov
    assert prov.get("emitted_by") == prov.get("workflow_definition_id") == "maint_release", prov
    assert prov.get("workflow_instance_id") == rec["action_id"] == "EV-1~2", rec
    assert len(prov.get("workflow_definition_version") or "") == 16, prov
    assert not {"version", "instance_id"} & set(prov), prov


@pytest.mark.asyncio
async def test_A_DEPOT_EVACUATION_NEEDS_THE_SUPERVISOR(registered):
    out, c = await _run(_event(me=False), [(DECIDE, "evacuate_for_depot"),
                                           (REVIEW, "approved", "s@x"),
                                           (ACK, "released", "tier@x")])
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_supervisor_review", "maint_release", "closed"], _path(out)
    assert registered[1] == ("EV-1~2", "maint_supervisor_approval:ORG",
                             "maint_supervisor_approval"), registered
    [rec] = _emitted(c)
    assert [(e["role"], e["approver_sub"]) for e in rec["approval_chain"]] == [
        ("maintainer", "m@x"), ("supervisor", "s@x")], rec["approval_chain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("me, via_supervisor", [(True, True), (False, False)])
async def test_REPLACE_NOW_NEEDS_THE_SUPERVISOR_ONLY_ON_A_MISSION_ESSENTIAL_ASSET(
        registered, me, via_supervisor):
    answers = [(DECIDE, "replace_now")]
    if via_supervisor:
        answers.append((REVIEW, "approved", "s@x"))
    answers.append((ACK, "released", "tier@x"))
    out, _ = await _run(_event(me=me), answers)
    assert out["terminal"] == "closed", out
    assert ("maint_supervisor_review" in [h[2] for h in _path(out)]) is via_supervisor, _path(out)


@pytest.mark.asyncio
async def test_A_SUPERVISOR_REFUSAL_RETURNS_TO_PROPOSED_AND_CLEARS_THE_CHAIN(registered):
    out, c = await _run(_event(), [(DECIDE, "evacuate_for_depot"), (REVIEW, "rejected", "s@x"),
                                   (DECIDE, "replace_after_resupply", "m2@x"),
                                   (ACK, "released", "tier@x")])
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_supervisor_review", "maint_fault_propose", "maint_release",
        "closed"], _path(out)
    [rec] = _emitted(c)
    assert [e["approver_sub"] for e in rec["approval_chain"]] == ["m2@x"], rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_REJECTION_RETURNS_TO_PROPOSED_WITH_ITS_REASON(registered):
    out, c = await _run(_event(), [(DECIDE, "rejected"), (DECIDE, "replace_after_resupply"),
                                   (ACK, "released", "tier@x")])
    hops = out["transitions"][2:]
    assert [(h["from"], h["outcome"], h["to"]) for h in hops][:2] == [
        ("triaged", "selected", "maint_fault_propose"),
        ("maint_fault_propose", "rejected", "maint_fault_propose")], hops
    assert (hops[1]["by"], hops[1]["reason"]) == ("m@x", "because 1"), hops[1]
    assert out["terminal"] == "closed", out
    [rec] = _emitted(c)
    assert len(rec["approval_chain"]) == 1, rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_DEFERRAL_PARKS_AND_COMES_BACK_AS_A_NEW_PROPOSAL(registered):
    out, _ = await _run(_event(), [(DECIDE, "deferred"), None,
                                   (DECIDE, "defer_with_restriction"),
                                   (ACK, "released", "tier@x")])
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "deferred", "maint_fault_park"),
                          ("maint_fault_park", "elapsed", "maint_fault_propose"),
                          ("maint_fault_propose", "defer_with_restriction", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)


@pytest.mark.asyncio
async def test_AN_UNANSWERED_PROPOSAL_ESCALATES_AND_NEVER_RELEASES(registered):
    out, c = await _run(_event(), [(DECIDE, EXPIRE), (ESCALATION, "withdrawn", "e@x")])
    assert (out["terminal"], _path(out)[1]) == (
        "withdrawn", ("maint_fault_propose", "timed_out", "maint_fault_escalate")), _path(out)
    assert out["transitions"][3]["by"] == "system", out["transitions"][3]
    assert [k for *_, k in registered] == ["maint_fault_approval", "maint_escalation"], registered
    assert _emitted(c) == [], _emitted(c)


@pytest.mark.asyncio
async def test_A_REOPENED_CASE_STARTS_A_NEW_APPROVAL_CHAIN(registered):
    """THE ONE GENERIC FIX S6 NEEDED. The maintainer approves replace-now on a mission-essential
    asset, the supervisor never answers, the escalation reopens, and a DIFFERENT maintainer
    chooses resupply. Nothing on that path said "no", so nothing cleared the chain, and the first
    maintainer's approval of an abandoned proposal rode into the second proposal's release."""
    out, c = await _run(_event(me=True), [(DECIDE, "replace_now", "m1@x"), (REVIEW, EXPIRE),
                                          (ESCALATION, "reopen", "e@x"),
                                          (DECIDE, "replace_after_resupply", "m2@x"),
                                          (ACK, "released", "tier@x")])
    assert [h[1] for h in _path(out)][1:] == [
        "replace_now", "timed_out", "reopen", "replace_after_resupply", "released"], _path(out)
    [rec] = _emitted(c)
    assert [e["approver_sub"] for e in rec["approval_chain"]] == ["m2@x"], rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_TIER_REFUSAL_IS_NOT_A_RELEASE(registered):
    out, _ = await _run(_event(), [(DECIDE, "replace_after_resupply"),
                                   (ACK, "tier_refused", "tier@x")])
    assert out["terminal"] == "tier_refused", out


# ── THE TABLES AGAINST THE TEMPLATE ─────────────────────────────────────────────────────────

def test_THE_SUPERVISOR_ROWS_AGREE_WITH_THE_OPTION_TEMPLATE():
    """The chaining table names verbs; the rule is about readiness and taking the asset offline.
    Derive the rule from the TEMPLATE and decide every (option, mission-essential) cell."""
    import workflow_definition as wd
    propose = wd.get_workflow_definition("maint_fault_propose")
    [render] = [s for s in propose.steps if s.kind == "render"]
    table = R.chaining_index()["maint_fault_propose"]
    seen = []
    for opt in render.template:
        for me in (True, False):
            want = opt["readiness"] == "NMC" or (opt["takes_offline"] and me)
            got = R._dt.decide(table, {"outcome": opt["verb"],
                                       "picture.battle_condition.mission_essential": me}).then
            seen.append((opt["verb"], me, got))
            assert (got == "maint_supervisor_review") is want, (opt["verb"], me, got)
            assert got in {"maint_supervisor_review", "maint_release"}, (opt["verb"], me, got)
    assert len(seen) == 8, seen


def test_EVERY_MAINTENANCE_DEFINITION_HAS_A_TABLE_THAT_FOLLOWS_IT():
    idx = R.chaining_index()
    reachable = {r["then"] for r in R._dt.load_table("maintenance_fault_selection")["rows"]}
    frontier = set(reachable)
    while frontier:
        d = frontier.pop()
        assert d in idx, f"{d} is reachable and nothing declares `after: {d}`"
        for row in idx[d]["rows"]:
            if row["then"] not in idx[d].get("terminals", []) and row["then"] not in reachable:
                reachable.add(row["then"])
                frontier.add(row["then"])
    assert reachable == {"maint_fault_propose", "maint_supervisor_review", "maint_fault_escalate",
                         "maint_fault_park", "maint_release"}, reachable


def test_THE_CHART_COMPOSES_EVERY_OVERLAY_THAT_DECLARES_TASK_KINDS():
    """A kind the deployment does not compose is undeclared at `/act`, so its rows accept
    nothing. The chart default must name every overlay that ships task kinds."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    cm = (root / "helm/invincible-agent/templates/configmap.yaml").read_text(encoding="utf-8")
    [value] = re.findall(r'^\s*TASK_KIND_OVERLAY_DIRS: "([^"]*)"', cm, flags=re.M)
    composed = set(value.split(":"))
    shipped = {f"/app/policy/overlays/{p.parent.name}/task_kinds"
               for p in root.glob("policy/overlays/*/task_kinds") if p.is_dir()}
    assert "/app/policy/overlays/openddil-lab/task_kinds" in shipped, shipped
    assert shipped <= composed, sorted(shipped - composed)
