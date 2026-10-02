"""AN ORIGIN SUGGESTION RUNS AS A CASE -- and the artifact's own dropper cannot be the one to confirm it.

An artifact with no recorded origin is unreadable to everyone but its owner. A suggestion cites
evidence for an origin; a steward of the suggested owner domain accepts it (the origin is handed
to its writer, which opens the artifact to the domain's consumers) or rejects it (nothing is
written; the artifact stays unresolved). Same runner, same approval card, same authority gate as
every other human decision -- declared in the SAMPLE overlay, not the seed.

THE DROPPER IS EXCLUDED STRUCTURALLY. The definition declares `excludes` on the confirm step; the
executor journals it beside the audience; `_authorize_resolution` refuses a listed caller before
`can_act` is asked, so no steward grant re-admits them. The exclusion is in the gate's namespace
(`authz_id`): the artifact stamps its dropper as a JWT `sub`, and the producer of the suggestion
resolves one to the other -- a `sub` would never equal an `acted_by`, and would refuse nobody.

Run: uv run --frozen pytest tests/test_an_origin_suggestion_runs_as_a_case.py -v
"""
from __future__ import annotations

import copy

import pytest

# One cluster double, the case runner's own -- not a second one free to drift from it.
from tests.test_a_case_runs_from_trigger_to_terminal import (
    R, _answer, _body, _Cluster, _refused, main, restate, wd, wr)

TRIGGER = "origin_suggestion"
DROPPER, STEWARD = "dropper@x", "steward@x"
CONFIRM, WRITTEN = "approval_confirm", "origin_written"
AUDIENCE = "origin_confirmation:aviation"
SUGGESTED = {"owner_domain": "aviation", "program": "PRG-1",
             "obtained_via": "contract_deliverable"}


@pytest.fixture(autouse=True)
def _real_policy(monkeypatch):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (wf, task["audience"], kind)) or {})
    return rows


def _suggestion(sid="SG-1", dropper=DROPPER):
    return {
        "kind": "origin_suggestion", "suggestion_id": sid, "artifact_id": "ART-9",
        # Both identities, as a producer that resolved one to the other would carry them. Only
        # the authz_id is the gate's namespace; the sub is here so an arm can show it is unused.
        "dropped_by": {"authz_id": dropper, "sub": "0b8e2c4a-sub-of-the-dropper"},
        "suggested": dict(SUGGESTED),
        "evidence": {"source": "contract", "citation": "CDRL A001 para 3"},
    }


async def _run(event, answers):
    """Drive one case: one entry per INSTANCE, ``(promise, verb)`` or ``(promise, verb, who)``."""
    key = event["suggestion_id"]
    scripted = {}
    for n, a in enumerate(answers, start=1):
        promise, verb, who = (*a, STEWARD) if len(a) == 2 else a
        scripted[(f"{key}~{n}", promise)] = _answer(verb, who, f"because {n}")
    c = _Cluster(scripted)
    try:
        out = await c.start(key, TRIGGER, copy.deepcopy(event))
    except Exception as exc:  # noqa: BLE001 -- a case that did not CLOSE is the arm's red
        raise AssertionError(
            f"the case ended in {type(exc).__name__}: {exc}; case={c.case(key)}") from exc
    return out, c


def _path(out):
    return [(t["from"], t["outcome"], t["to"]) for t in out["transitions"]][2:]


def _emitted(c):
    return [e["record"] for k, ctx in sorted(c.ctxs.items())
            for e in ctx.state.get("outbox:origin_resolution") or []]


def _approve(ctx, who):
    return _body(wr.approve)(ctx, {"task_id": f"{ctx.key()}:confirm", "promise_name": CONFIRM,
                                   "status": "accepted", "comments": "evidence holds",
                                   "acted_by": who})


# ── DECLARED, AND WHERE ─────────────────────────────────────────────────────────────────────

def test_THE_ORIGIN_CASE_IS_DECLARED_IN_THE_SAMPLE_OVERLAY_NOT_THE_SEED():
    seed = wd.definition_dirs()[0].parent
    sample = seed / "overlays" / "sample"
    declared = {
        "triggers": ["origin_suggestion"],
        "decisions": ["origin_suggestion_selection", "origin_confirm_chaining",
                      "origin_record_chaining"],
        "workflows": ["origin_confirm", "origin_record"],
        "task_kinds": ["origin_confirmation"],
    }
    for sub, names in declared.items():
        for n in names:
            assert (sample / sub / f"{n}.yaml").is_file(), (sub, n)
            assert not (seed / sub / f"{n}.yaml").exists(), f"{sub}/{n} is in the seed"


def test_THE_CONFIRM_STEP_EXCLUDES_THE_DROPPER_BY_AUTHZ_ID_AND_INTAKE_REQUIRES_IT():
    [step] = [s for s in wd.get_workflow_definition("origin_confirm").steps
              if s.kind == "human_await"]
    assert step.resolved_promise_name() == CONFIRM, step
    assert step.excludes == ["{trigger.dropped_by.authz_id}"], step.excludes
    [trig] = [t for t in R.load_triggers().values() if t.trigger == TRIGGER]
    assert "dropped_by.authz_id" in trig.requires, trig.requires
    assert not any(r.startswith("dropped_by.sub") for r in trig.requires), trig.requires


@pytest.mark.asyncio
async def test_A_SUGGESTION_WITHOUT_ITS_DROPPER_IS_REFUSED_AT_INTAKE(registered):
    """At INTAKE (400), not at the step: a case that opened without its exclusion's subject would
    fail later with a row's worth of state already journalled."""
    ev = _suggestion()
    del ev["dropped_by"]["authz_id"]
    c = _Cluster({})
    msg = await _refused(c.start("SG-1", TRIGGER, ev), 400)
    assert "lacks" in msg and "dropped_by.authz_id" in msg, msg
    assert "SG-1~1" not in c.ctxs, "the case opened an instance before refusing"
    assert registered == [], registered


def test_BOTH_VERBS_ON_THE_CARD_NEED_A_REASON(monkeypatch):
    """Accept-with-reason: accepting opens the artifact on the evidence cited, so the record must
    say why the steward believed it; a bare rejection invites the same suggestion again."""
    from src.iagent import human_tasks as ht
    seed = wd.definition_dirs()[0].parent
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(seed / "overlays" / "sample" / "task_kinds"))
    assert set(ht.verbs_for_kind("origin_confirmation")) == {"accepted", "rejected"}
    for verb in ("accepted", "rejected"):
        with pytest.raises(ht.InvalidDecisionForKind, match="REQUIRES a reason"):
            ht.validate_decision("origin_confirmation", verb, comment="  ")
        ht.validate_decision("origin_confirmation", verb, comment="the CDRL says so")


# ── THE THREE ENDINGS ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_STEWARD_ACCEPTS_AND_THE_CONFIRMED_ORIGIN_GOES_TO_ITS_WRITER(registered):
    out, c = await _run(_suggestion(), [(CONFIRM, "accepted"), (WRITTEN, "written", "w@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "resolved"), out
    assert _path(out) == [("triaged", "selected", "origin_confirm"),
                          ("origin_confirm", "accepted", "origin_record"),
                          ("origin_record", "written", "resolved")], _path(out)
    # A SIGNAL REGISTERS NO HUMAN ROW: one task, the steward's, on the suggested domain.
    assert registered == [("SG-1~1", AUDIENCE, "origin_confirmation")], registered
    [rec] = _emitted(c)
    assert rec["origin"] == SUGGESTED and rec["artifact_id"] == "ART-9", rec
    assert rec["suggestion_id"] == "SG-1", rec
    assert [(e["role"], e["approver_sub"]) for e in rec["approval_chain"]] == [
        ("steward", STEWARD)], rec["approval_chain"]
    prov = rec["provenance"]
    assert prov.get("case_definition") == "origin_suggestion" and prov.get("case_id") == "SG-1", prov
    assert prov.get("emitted_by") == prov.get("workflow_definition_id") == "origin_record", prov
    assert prov.get("workflow_instance_id") == rec["resolution_id"] == "SG-1~2", rec


@pytest.mark.asyncio
async def test_A_REJECTION_LEAVES_THE_ARTIFACT_UNRESOLVED_WITH_ITS_REASON(registered):
    out, c = await _run(_suggestion(), [(CONFIRM, "rejected")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "unresolved"), out
    hops = out["transitions"][2:]
    assert [(h["from"], h["outcome"], h["to"]) for h in hops] == [
        ("triaged", "selected", "origin_confirm"),
        ("origin_confirm", "rejected", "unresolved")], hops
    assert (hops[1]["by"], hops[1]["reason"]) == (STEWARD, "because 1"), hops[1]
    assert _emitted(c) == [], "a rejection wrote an origin"


@pytest.mark.asyncio
async def test_A_REFUSED_WRITE_IS_NOT_A_RESOLUTION(registered):
    out, c = await _run(_suggestion(), [(CONFIRM, "accepted"), (WRITTEN, "write_refused", "w@x")])
    assert out["terminal"] == "write_refused", out
    assert len(_emitted(c)) == 1, _emitted(c)


# ── THE DROPPER, AT THE GATE ────────────────────────────────────────────────────────────────

@pytest.fixture
def can_act(monkeypatch):
    """`can_act` says YES to everyone -- the dropper holds the steward grant -- and records who
    it was asked about, so an arm can show the exclusion refused BEFORE the grant was consulted."""
    seen: list = []
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: seen.append((aud, who)) or True)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("fact, caller", [
    (DROPPER, DROPPER),
    (DROPPER, "  DROPPER@X "),           # the caller's own spelling: stripped, casefolded
    ("  Dropper@X ", DROPPER),           # the producer's spelling: journalled stripped
])
async def test_THE_DROPPER_IS_REFUSED_BEFORE_CAN_ACT_IS_ASKED(registered, can_act, fact, caller):
    _, c = await _run(_suggestion(dropper=fact), [(CONFIRM, "rejected")])
    ctx = c.ctx("SG-1~1")
    assert ctx.state.get(main._excluded_key(CONFIRM)) == [fact.strip()], ctx.state
    msg = await _refused(_approve(ctx, caller), 403)
    assert "excluded" in msg, msg
    assert can_act == [] and ctx.resolved == [], (can_act, ctx.resolved)


@pytest.mark.asyncio
async def test_CONTROL_ANOTHER_STEWARD_PASSES_THE_SAME_GATE(registered, can_act):
    _, c = await _run(_suggestion(), [(CONFIRM, "rejected")])
    ctx = c.ctx("SG-1~1")
    await _approve(ctx, STEWARD)
    assert can_act == [(AUDIENCE, STEWARD)], can_act
    assert [n for n, _ in ctx.resolved] == [CONFIRM], ctx.resolved


@pytest.mark.asyncio
async def test_THE_DROPPERS_SUB_IS_NOT_WHAT_THE_GATE_REFUSES(registered, can_act):
    """The sub travels on the suggestion but is never journalled: an `acted_by` is an authz_id,
    so an exclusion bound to the sub would be a guard that cannot fire."""
    ev = _suggestion()
    _, c = await _run(ev, [(CONFIRM, "rejected")])
    ctx = c.ctx("SG-1~1")
    assert ctx.state.get(main._excluded_key(CONFIRM)) == [DROPPER], ctx.state
    await _approve(ctx, ev["dropped_by"]["sub"])
    assert can_act == [(AUDIENCE, ev["dropped_by"]["sub"])], can_act


@pytest.mark.asyncio
async def test_AN_EXCLUSION_THAT_BINDS_TO_NOBODY_FAILS_BEFORE_ANYTHING_IS_RESOLVABLE(registered):
    """Blank passes intake (`requires` refuses only absent and empty), so the executor is the
    guard: the step fails before its audience is journalled or its row exists."""
    c = _Cluster({})
    msg = await _refused(c.start("SG-1", TRIGGER, _suggestion(dropper="   ")), 422)
    assert "names nobody" in msg, msg
    assert registered == [], registered
    state = c.ctx("SG-1~1").state
    assert main._audience_key(CONFIRM) not in state, state
    assert main._excluded_key(CONFIRM) not in state, state


@pytest.mark.asyncio
async def test_A_STEP_THAT_DECLARES_NO_EXCLUSION_JOURNALS_NONE(registered, monkeypatch):
    """Every other human_await replays unchanged: the key is written only when declared."""
    from tests.test_the_maintenance_fault_runs_as_a_case import _event

    async def _select(**arms):  # the deadline race, answered: the approval wins
        value = await arms["approved"]
        arms["expired"].close()
        return ("approved", value)
    monkeypatch.setattr(restate, "select", _select)
    c = _Cluster({("EV-1~1", "approval_decide"): _answer("replace_after_resupply", "m@x"),
                  ("EV-1~2", "tier_ack"): _answer("released", "tier@x")})
    out = await c.start("EV-1", "maintenance_fault", _event())
    assert out["terminal"] == "closed", out
    state = c.ctx("EV-1~1").state
    assert main._audience_key("approval_decide") in state, state
    assert not any(k.startswith("excluded_") for k in state), sorted(state)
