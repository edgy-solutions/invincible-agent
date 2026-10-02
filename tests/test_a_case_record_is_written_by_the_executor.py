"""The generic runner's executor half: what a definition may declare, and who writes the case record.

The maintenance fault workflow and safety acceptance must run on ONE executor with nothing
domain-specific in Python (dispatch B). That needs a definition to carry more than awaits: a
rendered option set, a system's acknowledgement, a durable revisit timer, an emitted release, and
an approval chain. Each arm below is one of those, and each is a claim about WHO writes what:

* THE CHAIN IS WRITTEN BY THE EXECUTOR from the verified `acted_by`, never by a template, and a
  non-approval ENDS it -- an approval of a rejected proposal must not ride into the next release.
* EVERYTHING THAT WRITES THE CASE RECORD IS REGISTRY-ONLY. BPMNWorkflowRunner runs a caller-supplied
  definition; a caller that could declare `approves` would author its own approvals.
* A DOTTED PLACEHOLDER BINDS OR REFUSES. It used to fall outside the pattern and pass through as
  literal braces, strict or not -- an audience nobody holds, suspended forever.
* A LEGACY AWAIT'S JOURNAL IS UNCHANGED. A new `ctx.run` on every human_await would shift the
  journal of an in-flight multi-step instance, and Restate refuses a divergent replay.

Run: uv run --frozen pytest tests/test_a_case_record_is_written_by_the_executor.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

yaml = pytest.importorskip("yaml")
pytest.importorskip("restate")
import restate  # noqa: E402
import main  # noqa: E402  — the real executor
import workflow_definition as wd  # noqa: E402  — the SAME module object main validates with

_POLICY = _REPO / "policy"


# ── the double ──────────────────────────────────────────────────────────────────────────────

class _Promise:
    def __init__(self, answer):
        self.answer = answer

    def value(self):
        async def _v():
            if self.answer is None:
                raise AssertionError("the run awaited a promise this arm did not script")
            return self.answer
        return _v()


class _Ctx:
    """Answers each promise by name, records every journalled `run` name and every state write."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.state: dict = {}
        self.runs: list = []
        self.slept: list = []

    def key(self):
        return "seal-key"

    def set(self, k, v):
        self.state[k] = v

    async def get(self, k, **_kw):
        return self.state.get(k)

    async def run(self, name, fn):
        self.runs.append(name)
        return fn()

    def promise(self, name, type_hint=None):
        return _Promise(self.answers.get(name))

    def sleep(self, delta):
        self.slept.append(delta.total_seconds())

        async def _s():
            return None
        return _s()


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (task["id"], task["audience"], kind)) or {})
    return rows


@pytest.fixture
def no_stubs(monkeypatch):
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {})


_TRIGGER = {"authz_id": "a@x", "owning_tier": "ORG", "asset_id": "A-7",
            "fault": {"item": "array module", "fault_code": "F12"},
            "picture": {"spare": {"on_hand_here": 0, "nearest_site_with_stock": None}}}


async def _drive(steps, *, ctx=None, trigger=None, did="seal_def", **kw):
    ctx = ctx or _Ctx()
    env = await main._run_definition(
        ctx, "wf-seal", {"id": did, "name": did, "steps": steps}, trigger or _TRIGGER, **kw)
    return ctx, env


def _await(sid="approve", **extra):
    return {"kind": "human_await", "id": sid, "audience": "maint:{trigger.owning_tier}", **extra}


def _answer(verb, who="m@x", comments=""):
    return {"status": verb, "acted_by": who, "comments": comments, "task_id": "t"}


# ── 1. DOTTED PLACEHOLDERS ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_DOTTED_AUDIENCE_BINDS_FROM_THE_TRIGGER(registered):
    await _drive([_await()], ctx=_Ctx({"approval_approve": _answer("ok")}))
    assert registered == [("wf-seal:approve", "maint:ORG", "workflow_ack")], registered


@pytest.mark.asyncio
async def test_AN_UNBOUND_DOTTED_AUDIENCE_IS_REFUSED(registered):
    step = dict(_await(), audience="maint:{trigger.no_such}")
    with pytest.raises(restate.TerminalError) as exc:
        await _drive([step])
    assert "trigger.no_such" in str(exc.value)
    assert registered == []


@pytest.mark.asyncio
async def test_A_DOTTED_PATH_TO_A_MAPPING_IS_NOT_A_BINDING(registered):
    step = dict(_await(), audience="maint:{trigger.fault}")
    with pytest.raises(restate.TerminalError):
        await _drive([step])
    assert registered == []


# ── 2. THE RENDERER ─────────────────────────────────────────────────────────────────────────

_CTX = {"trigger": _TRIGGER, "outputs": {"d": {"s": {"refs": ["DMC-1", "DMC-2"]}}}}


def test_AN_EXACT_PLACEHOLDER_YIELDS_THE_RAW_VALUE():
    assert main._render("{outputs.d.s.refs}", _CTX, where="t") == ["DMC-1", "DMC-2"]


def test_A_PRESENT_NONE_IS_KEPT_not_refused():
    assert main._render("{trigger.picture.spare.nearest_site_with_stock}", _CTX, where="t") is None


def test_INTERPOLATION_RENDERS_SCALARS():
    got = main._render({"task": "replace the {trigger.fault.item} on {trigger.asset_id}"},
                       _CTX, where="t")
    assert got == {"task": "replace the array module on A-7"}


@pytest.mark.parametrize("tmpl", [
    "{trigger.no_such}",                                    # absent, exact
    "x {trigger.no_such}",                                  # absent, interpolated
    "site {trigger.picture.spare.nearest_site_with_stock}",  # present None, interpolated
    "refs {outputs.d.s.refs}",                              # a list interpolated into a string
], ids=["absent-exact", "absent-interp", "none-interp", "list-interp"])
def test_THE_RENDERER_REFUSES_RATHER_THAN_BLANKS(tmpl):
    with pytest.raises(restate.TerminalError):
        main._render({"k": [tmpl]}, _CTX, where="t")


# ── 3. THE APPROVAL CHAIN ───────────────────────────────────────────────────────────────────

_OPTIONS = [{"verb": "replace_now", "readiness": "FMC"},
            {"verb": "evacuate_for_depot", "readiness": "NMC"}]


def _choosing(**extra):
    return [{"kind": "render", "id": "options", "template": _OPTIONS},
            _await(role="maintainer", approves=["replace_now", "evacuate_for_depot"],
                   chooses_from="outputs.seal_def.options", **extra)]


@pytest.mark.asyncio
async def test_AN_APPROVAL_APPENDS_ONE_ENTRY_WRITTEN_FROM_THE_VERIFIED_ACTOR(registered, no_stubs):
    prior = [{"step": 1, "role": "x", "approver_sub": "p@x", "decision": "approved",
              "decided_at": "t0", "decision_record_ref": "r"}]
    ctx, env = await _drive(_choosing(), ctx=_Ctx({"approval_approve": _answer("replace_now")}),
                            from_registry=True, approval_chain=prior)
    entry = env["approval_chain"][-1]
    assert len(env["approval_chain"]) == 2, env["approval_chain"]
    assert (entry["step"], entry["role"], entry["approver_sub"], entry["decision"]) == (
        2, "maintainer", "m@x", "approved"), entry
    assert entry["decided_at"] and entry["decision_record_ref"] == "wf-seal:approve", entry
    assert prior == [prior[0]] and len(prior) == 1, "the caller's chain was mutated in place"


@pytest.mark.asyncio
async def test_A_NON_APPROVAL_ENDS_THE_CHAIN(registered, no_stubs):
    prior = [{"step": 1, "role": "x", "approver_sub": "p@x", "decision": "approved",
              "decided_at": "t0", "decision_record_ref": "r"}]
    _, env = await _drive(_choosing(), ctx=_Ctx({"approval_approve": _answer("rejected")}),
                          from_registry=True, approval_chain=prior)
    assert env["approval_chain"] == [], env["approval_chain"]
    assert env["outcome"] == "rejected"


@pytest.mark.asyncio
async def test_THE_VERB_CHOOSES_THE_OPTION(registered, no_stubs):
    _, env = await _drive(_choosing(), ctx=_Ctx({"approval_approve": _answer("evacuate_for_depot")}),
                          from_registry=True)
    assert env["outputs"]["seal_def"]["approve"]["chosen"] == _OPTIONS[1]
    assert env["outcome"] == "evacuate_for_depot"


@pytest.mark.asyncio
async def test_AN_APPROVAL_OF_NO_OPTION_IS_REFUSED(registered, no_stubs):
    steps = _choosing()
    steps[1]["approves"] = [*steps[1]["approves"], "replace_after_resupply"]
    with pytest.raises(restate.TerminalError) as exc:
        await _drive(steps, ctx=_Ctx({"approval_approve": _answer("replace_after_resupply")}),
                     from_registry=True)
    assert "approval of nothing" in str(exc.value)


@pytest.mark.asyncio
async def test_TWO_OPTIONS_ON_ONE_VERB_ARE_REFUSED(registered, no_stubs):
    steps = _choosing()
    steps[0]["template"] = [*_OPTIONS, {"verb": "replace_now", "readiness": "PMC"}]
    with pytest.raises(restate.TerminalError) as exc:
        await _drive(steps, ctx=_Ctx({"approval_approve": _answer("replace_now")}),
                     from_registry=True)
    assert "2 options" in str(exc.value)


def test_AN_APPROVES_WITHOUT_A_ROLE_IS_REFUSED_AT_LOAD():
    with pytest.raises(Exception) as exc:
        wd.HumanAwaitStep.model_validate(_await(approves=["ok"]))
    assert "role" in str(exc.value)


@pytest.mark.asyncio
async def test_CONTROL_A_LEGACY_AWAIT_JOURNALS_ONLY_ITS_REGISTER(registered):
    """Replay safety: a human_await declaring none of the new fields journals exactly what it did
    before. A `decided_at_*` entry here would shift every in-flight multi-step instance."""
    ctx, env = await _drive([_await()], ctx=_Ctx({"approval_approve": _answer("ok")}))
    assert ctx.runs == ["register_approve"], ctx.runs
    assert env["outcome"] == "ok" and env["approval_chain"] == []


# ── 4. REGISTRY-ONLY ────────────────────────────────────────────────────────────────────────

_AUTHORED = {
    "render": [{"kind": "render", "id": "r", "template": "x"}],
    "signal_await": [{"kind": "signal_await", "id": "s", "signal": "ack", "audience": "a:B",
                      "accepts": ["acked"]}],
    "wait": [{"kind": "wait", "id": "w", "seconds": 5}],
    "emit": [{"kind": "emit", "id": "e", "channel": "release", "template": "x"}],
    "approves": [_await(role="r", approves=["ok"])],
    "chooses_from": [_await(chooses_from="outputs.x")],
    "stub_verb": [{"kind": "spo_operation", "id": "walk", "subject": "urn:s", "verb": "urn:v:walk"}],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_AUTHORED))
async def test_A_CASE_RECORD_FIELD_ON_A_CALLER_SUPPLIED_DEFINITION_IS_REFUSED(
        name, registered, monkeypatch):
    stub = wd.StubVerb(verb="urn:v:walk", stub=True, retired_by="t", returns={})
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {"urn:v:walk": stub})
    # A register step FIRST: the refusal must come before any step's effect, not at the step.
    steps = [_await("first"), *_AUTHORED[name]]
    ctx = _Ctx({"approval_first": _answer("ok")})
    with pytest.raises(restate.TerminalError) as exc:
        await _drive(steps, ctx=ctx)
    assert "only a registry definition may" in str(exc.value), str(exc.value)
    assert registered == [] and ctx.state == {}, "refused AFTER an earlier step's effect"


# ── 5. THE NEW STEP KINDS ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_SIGNAL_JOURNALS_ITS_GATE_AND_DISPOSES(registered, no_stubs):
    step = {"kind": "signal_await", "id": "ack", "signal": "release_ack",
            "audience": "mmis_ack:{trigger.owning_tier}", "accepts": ["acknowledged", "refused"]}
    ctx, env = await _drive([step], ctx=_Ctx({"release_ack": _answer("acknowledged", "svc@x")}),
                            from_registry=True)
    assert ctx.state.get(main._audience_key("release_ack")) == "mmis_ack:ORG", ctx.state
    assert ctx.state.get(main._signal_accepts_key("release_ack")) == ["acknowledged", "refused"], (
        f"the resolver reads the vocabulary at the accepts key and found none: {ctx.state}")
    assert registered == [], "a system's ack registered a human task"
    assert env["outcome"] == "acknowledged"


@pytest.mark.asyncio
async def test_A_WAIT_IS_DURABLE_AND_ELAPSES(registered, no_stubs):
    ctx, env = await _drive([{"kind": "wait", "id": "revisit", "seconds": 86400}], from_registry=True)
    assert ctx.slept == [86400.0]
    assert env["outcome"] == "elapsed"


@pytest.mark.asyncio
async def test_AN_EMIT_APPENDS_THE_RENDERED_RECORD_TO_THE_OUTBOX(registered, no_stubs):
    step = {"kind": "emit", "id": "release", "channel": "maintenance_action",
            "template": {"asset_id": "{trigger.asset_id}",
                         "approval_chain": "{case.approval_chain}",
                         "definition": "{definition.id}@{definition.version}"}}
    ctx = _Ctx()
    ctx.state["outbox:maintenance_action"] = [{"record": "earlier"}]
    _, env = await _drive([step], ctx=ctx, from_registry=True,
                          approval_chain=[{"step": 1, "approver_sub": "m@x"}])
    box = ctx.state["outbox:maintenance_action"]
    assert len(box) == 2 and box[0] == {"record": "earlier"}, box
    rec = box[1]["record"]
    assert rec["asset_id"] == "A-7" and rec["approval_chain"] == [{"step": 1, "approver_sub": "m@x"}]
    assert rec["definition"] == f"seal_def@{env['definition_version']}"
    assert env["outcome"] is None, "an emit is not a disposition"


@pytest.mark.asyncio
async def test_A_STUB_VERB_RENDERS_AND_NEVER_REACHES_THE_VERIFIER(registered, monkeypatch):
    stub = wd.StubVerb(verb="urn:v:walk", stub=True, retired_by="7f Phase 2(e)",
                       returns={"task_refs": [{"data_module_code": "STUB-{trigger.fault.fault_code}"}]})
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {"urn:v:walk": stub})
    import spo_step_executor as sse

    def _boom(*a, **k):
        raise AssertionError("a stub reached the stage-2 verifier")
    monkeypatch.setattr(sse, "verify_spo_step", _boom)
    monkeypatch.setattr(sse, "dispatch_spo_step", _boom)
    step = {"kind": "spo_operation", "id": "walk", "subject": "urn:s", "verb": "urn:v:walk"}
    _, env = await _drive([step], from_registry=True)
    assert env["outputs"]["seal_def"]["walk"] == {"task_refs": [{"data_module_code": "STUB-F12"}]}
    assert env["step_results"][0]["status"] == "STUB"
    assert env["step_results"][0]["stub"]["retired_by"] == "7f Phase 2(e)"


@pytest.mark.asyncio
async def test_A_RERUN_REPLACES_ITS_OWN_OUTPUTS_AND_KEEPS_OTHERS(registered, no_stubs):
    prior = {"seal_def": {"stale": 1}, "other_def": {"s": 2}}
    _, env = await _drive([{"kind": "render", "id": "fresh", "template": "{trigger.asset_id}"}],
                          from_registry=True, outputs=prior)
    assert env["outputs"] == {"seal_def": {"fresh": "A-7"}, "other_def": {"s": 2}}, env["outputs"]
    assert prior == {"seal_def": {"stale": 1}, "other_def": {"s": 2}}, "the caller's outputs mutated"


# ── 6. LOAD-TIME SHAPE ──────────────────────────────────────────────────────────────────────

def test_TWO_AWAITS_ON_ONE_PROMISE_ARE_REFUSED():
    with pytest.raises(Exception) as exc:
        wd.WorkflowDefinition.model_validate({"id": "d", "name": "d", "steps": [
            _await("a", promise_name="p"),
            {"kind": "signal_await", "id": "b", "signal": "p", "audience": "x:Y", "accepts": ["k"]},
        ]})
    assert "awaited twice" in str(exc.value)


def test_DUPLICATE_STEP_IDS_ARE_REFUSED():
    with pytest.raises(Exception) as exc:
        wd.WorkflowDefinition.model_validate({"id": "d", "name": "d", "steps": [
            {"kind": "wait", "id": "a", "seconds": 1}, {"kind": "wait", "id": "a", "seconds": 2}]})
    assert "duplicate step ids" in str(exc.value)


# ── 7. THE REGISTRY SEES THE OVERLAYS ───────────────────────────────────────────────────────

def _tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


_WF = "id: {id}\nname: {id}\nsteps:\n  - {{kind: wait, id: w, seconds: 1}}\n"


def test_AN_OVERLAY_DEFINITION_IS_ON_THE_DEFAULT_PATH(tmp_path, monkeypatch):
    _tree(tmp_path, {"policy/workflows/seed_one.yaml": _WF.format(id="seed_one"),
                     "policy/overlays/lab/workflows/lab_one.yaml": _WF.format(id="lab_one")})
    monkeypatch.delenv("WORKFLOW_DEFINITIONS_DIR", raising=False)
    monkeypatch.setattr(wd, "candidate_definition_dirs",
                        lambda _p: [tmp_path / "policy" / "workflows"])
    try:
        assert wd.get_workflow_definition("lab_one").id == "lab_one"
    except wd.WorkflowDefinitionError as exc:
        raise AssertionError(f"an overlay definition is off the default search path: {exc}") from exc
    assert wd.get_workflow_definition("seed_one").id == "seed_one"


def _shared_definitions(overlays_root: Path) -> dict:
    owners: dict = {}
    for d in sorted(overlays_root.glob("*/workflows")):
        for p in sorted(d.glob("*.yaml")):
            owners.setdefault(p.stem, []).append(d.parent.name)
    return {k: v for k, v in owners.items() if len(v) > 1}


def test_NO_TWO_OVERLAYS_DECLARE_ONE_DEFINITION():
    """Name order is not a precedence anyone chose -- the decision tables' rule, for definitions."""
    assert not _shared_definitions(_POLICY / "overlays")


def test_CONTROL_the_collision_check_can_fire(tmp_path):
    _tree(tmp_path, {"a/workflows/x.yaml": "", "b/workflows/x.yaml": ""})
    assert _shared_definitions(tmp_path) == {"x": ["a", "b"]}


def test_A_STUB_VERB_DECLARED_TWICE_IS_REFUSED(tmp_path, monkeypatch):
    stub = "verb: urn:v:walk\nstub: true\nretired_by: later\nreturns: {}\n"
    _tree(tmp_path, {"policy/workflows/.keep": "",
                     "policy/overlays/a/verbs/walk.yaml": stub,
                     "policy/overlays/b/verbs/walk.yaml": stub})
    monkeypatch.delenv("WORKFLOW_DEFINITIONS_DIR", raising=False)
    monkeypatch.setattr(wd, "candidate_definition_dirs",
                        lambda _p: [tmp_path / "policy" / "workflows"])
    with pytest.raises(wd.WorkflowDefinitionError) as exc:
        wd.load_stub_verbs()
    assert "declared twice" in str(exc.value)


def test_THE_COMMITTED_STUB_VERBS_LOAD():
    wd.load_stub_verbs()
