"""PROMISE-NAME EQUALITY SEAL (M3.2 build 1) — the durable name the executor AWAITS
must equal the one the resolving handler RESOLVES.

A Restate promise name is durable journal state: an IDENTITY SURFACE ON LIVE DATA, the
same class as a VirtualObject dedup key or a Topaz audience key. The failure mode is
specific and SILENT — a review suspended on one name while the runner resolves another
can never be woken by ANY submission. No error, no retry, just a task in a queue that
nothing can clear.

WHY THIS SEAL EXISTS, precisely: the 2026-08-04 ruling asserted the two names were "the
same string by construction, since the grouped step's id IS `decision`". Evaluated, that
is false — `f"approval_{step.id}"` with `step.id = "decision"` is `approval_decision`,
and the `approval_` literal lives in the EXECUTOR where no definition content can reach
it. The ruling was believed because of who produced it, not because anyone ran it. This
guard is what running it looks like (AGENTS.md: a ruling that asserts a string identity
gets EVALUATED, not read).

INDEPENDENCE IS THE POINT. Both arms are BEHAVIOURAL and read from SOURCES THAT DO NOT
SHARE A WRITE:
  * AWAIT arm   — drives the real ``_run_definition`` over the real git-asserted YAML and
                  records the name it actually suspends on.
  * RESOLVE arm — drives the real ``submit_decision`` and records the name it actually
                  resolves.
Deliberately NOT a shared constant both sides import: that guard could never fail. Rename
one constant and both arms move together while cortex-bff and every in-flight journal
still expect the old string — a green over a broken system, which is worse than no seal.

Run:  uv run --frozen --with pytest --with pytest-asyncio pytest tests/test_promise_name_seal.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import main  # noqa: E402  — the real executor
from agent_fleet.restate_analyst import grouped_review_workflow  # noqa: E402
from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    load_all_workflows, load_workflow_definition,
)

_SUBMIT = grouped_review_workflow.submit_decision.__wrapped__


# ---------------------------------------------------------------------------
# AUTHORITY GATE scaffolding (approval-bypass-bpmn-runner, 2026-08-11)
# ---------------------------------------------------------------------------
# `submit_decision` now gates on Topaz `can_act(caller, audience)` before resolving the
# decision promise. These suites are about VALIDATION and CONCURRENCY, not authorization,
# so they drive the AUTHORIZED path: a stubbed allow-decider plus an audience in workflow
# state. Stubbing the decider does not weaken them — none of their claims involve who the
# caller is. The gate's own discriminating pairs live in
# tests/security/test_approval_authority_gate.py, where a stub would be the whole bug.
#
# PATCHES BOTH MODULE IDENTITIES (the flatten dance): sys.path carries the repo root AND
# agent_fleet/restate_analyst, so `spo_step_executor` and
# `agent_fleet.restate_analyst.spo_step_executor` are two distinct module objects.
_ACTOR = "approver@example.com"
_AUDIENCE = "promotion:SUSTAINMENT"


@pytest.fixture(autouse=True)
def _allow_can_act(monkeypatch):
    import importlib
    for _name in ("spo_step_executor", "agent_fleet.restate_analyst.spo_step_executor"):
        try:
            _mod = importlib.import_module(_name)
        except ImportError:
            continue
        monkeypatch.setattr(_mod, "check_can_act", lambda aud, who: True, raising=False)
_WORKFLOWS = _REPO / "policy" / "workflows"


@pytest.fixture(autouse=True)
def _stub_service_mint(monkeypatch):
    """The AWAIT arm drives the real ``_run_definition``, which registers the grouped task — and that
    register MINTS AT USE since 2026-08-04 (``docs/plans/archive/2026-08-04-notice-a-dispatch-failure.md``).
    Without a stub this seal would reach Keycloak and die on a bare ``KeyError``, which says nothing
    about promise names.

    STUBBING THE MINT DOES NOT WEAKEN THIS SEAL. Its claim is that the name AWAITED equals the name
    RESOLVED; the credential used to register a task is orthogonal to both arms, and neither arm reads
    it. What must stay un-stubbed is the promise plumbing, and it is.

    Patches SOURCE modules as well as consumers: ``main`` imports ``dispatch_driver`` lazily inside
    ``_run_definition``, so that module object may not exist yet when this fixture runs."""
    stub = lambda **_: "svc-token-stub"  # noqa: E731
    # ACTIVELY IMPORT, don't poll sys.modules. The passive form
    # (`sys.modules.get(_name)` + `if _mod is not None`) patched NOTHING whenever the
    # module wasn't loaded yet — and this fixture's own docstring says that happens, since
    # the consumer imports lazily. A seal that silently declines to seal is worse than no
    # seal. Mirrors the `check_can_act` fixture in this same file, which already does it
    # this way. See docs/principles/a-stub-that-needs-another-test-is-not-a-stub.md
    import importlib  # noqa: PLC0415

    _bound = 0
    for _name in ("agent_fleet.utils.service_identity", "utils.service_identity",
                  "dispatch_driver", "agent_fleet.restate_analyst.dispatch_driver"):
        try:
            _mod = importlib.import_module(_name)
        except ImportError:
            continue
        monkeypatch.setattr(_mod, "mint_service_token", stub, raising=False)
        _bound += 1
    assert _bound, (
        "mint_service_token was patched in ZERO modules -- the seal would run against the "
        "real mint and prove nothing. Import paths changed; update this fixture's name list."
    )


# ---------------------------------------------------------------------------
# Fakes that RECORD THE NAME (the existing grouped-review fakes ignore it)
# ---------------------------------------------------------------------------
class _Captured(Exception):
    """Raised the instant the executor suspends, so the assertion is isolated to the
    await site and no downstream step (direct_call -> Topaz -> HTTP) executes."""

    def __init__(self, name: str):
        self.name = name


class _CapturingPromise:
    def __init__(self, name):
        self._name = name

    def value(self):
        async def _a():
            raise _Captured(self._name)
        return _a()


class _AwaitCapturingCtx:
    """WorkflowContext stand-in that records the promise name the runner suspends on."""

    def __init__(self, key="pcn-review-IPCN25300X-qa"):
        self._key = key
        self.state: dict = {}
        self.runs: list = []

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        self.runs.append(name)
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def promise(self, name, type_hint=None):
        return _CapturingPromise(name)

    def object_send(self, tpe, key, arg, idempotency_key=None, **kw):
        pass


class _ResolveRecordingPromise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append(self._name)


class _ResolveCapturingCtx:
    """WorkflowSharedContext stand-in that records the promise name actually resolved."""

    def __init__(self, state):
        self._state = state
        self.resolved: list = []

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _ResolveRecordingPromise(self.resolved, name)


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


_TRIGGER = {
    "approver": "qa",
    "compartment": "SUSTAINMENT",
    "notice_fingerprint": "IPCN25300X",
    "notice_id": "IPCN25300X",
    "notice_ref": "http://internal/notices/IPCN25300X",
    "dispatch_endpoint": "http://engine-o/dispatch",
    "batch_items": [
        {"mpn": "MPN-0", "subject": "http://internal/components/MPN-0",
         "proposed_disposition": "dispatchQualification", "needs_review": False},
    ],
}


async def _awaited_name(definition_path: Path, trigger: dict, monkeypatch) -> str:
    """Drive the REAL executor and return the promise name it suspends on."""
    monkeypatch.setattr(requests, "post", lambda url, **k: _Resp(200, {"task_id": "t"}))
    wf = load_workflow_definition(definition_path)
    ctx = _AwaitCapturingCtx()
    try:
        await main._run_definition(ctx, ctx.key(), wf.model_dump(), trigger)
    except _Captured as c:
        return c.name
    raise AssertionError(
        f"{definition_path.name}: the runner never suspended on a promise — a human_await "
        "that does not suspend is not awaiting anything"
    )


# ===========================================================================
# THE SEAL
# ===========================================================================
@pytest.mark.asyncio
async def test_grouped_awaited_name_equals_resolved_name(monkeypatch):
    """THE guard. The executor's await site and the shared handler's resolve site must
    agree on one durable string, measured independently on both sides."""
    awaited = await _awaited_name(_WORKFLOWS / "grouped_review.yaml", _TRIGGER, monkeypatch)

    ctx = _ResolveCapturingCtx({
        "batch_items": _TRIGGER["batch_items"],
        "approver": "qa",
        "notice_fingerprint": "IPCN25300X",
        "audience:decision": _AUDIENCE,
    })
    out = await _SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": _ACTOR})
    assert out["accepted"] is True, "fixture must reach the RESOLVE path to measure the name"
    assert len(ctx.resolved) == 1
    resolved = ctx.resolved[0]

    assert awaited == resolved, (
        f"promise-name mismatch: the runner suspends on {awaited!r} but submit_decision "
        f"resolves {resolved!r}. A review suspended on one name cannot be woken by the "
        "other — no error, no retry, a task nothing can clear. Fix by threading the "
        "DECLARED promise_name to whichever site missed it; NEVER by renaming the "
        "handler's literal (that is a durable-state migration, morning work behind the drain)."
    )


@pytest.mark.asyncio
async def test_default_convention_preserved_for_undeclared_steps(monkeypatch):
    """The dark-launched path must be BYTE-IDENTICAL. `promote_answer_artifact` declares no
    promise_name, so it must still await `approval_{id}` — this is what makes "drop the
    `approval_` prefix globally" show up as RED instead of as a silent rename on a durable
    surface whose in-flight instances sit OUTSIDE the grouped-review drain's coverage."""
    path = _WORKFLOWS / "promote_answer_artifact.yaml"
    wf = load_workflow_definition(path)
    step = next(s for s in wf.steps if s.kind == "human_await")
    assert step.promise_name is None, "fixture: this definition must NOT declare a name"

    awaited = await _awaited_name(path, {"authz_id": "alice@example.com"}, monkeypatch)
    assert awaited == f"approval_{step.id}", (
        f"the undeclared default changed: {awaited!r} != 'approval_{step.id}'. Every "
        "in-flight instance of this dark-launched workflow is suspended on the old name."
    )


def test_every_human_await_resolves_to_a_nonempty_name():
    """Cheap totality check across the git-asserted corpus — a blank or whitespace promise
    name is a suspend on nothing."""
    for wf_id, wf in load_all_workflows(_WORKFLOWS).items():
        for step in wf.steps:
            if step.kind != "human_await":
                continue
            name = step.resolved_promise_name()
            assert name and name.strip() == name and " " not in name, (
                f"{wf_id}/{step.id}: unusable promise name {name!r}"
            )
