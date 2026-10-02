"""The acceptance row carries the kind its request names, and the register's refusals are final.

THE DEFECT, MEASURED BY LANE 1 ON HAZ-1003 (2026-10-01). engine-safety's review_request names
`kind: risk_acceptance_medium`. SafetyAcceptance ran `safety_acceptance_direct` on the shared
executor, and `_register_human_task` hard-coded `"kind": "workflow_ack"`. `/act` keys its
decision vocabulary and its reason requirement on the ROW's kind, so the acceptance was approved
with no reason, through the gate of a kind that requires none. The second defect sat in the same
function: the register's 422 `no_entitled_recipients` fell through to `raise_for_status`, was
retried, and Restate paused the invocation until a human resumed it.

WHAT THIS DRIVES. The real `safety_acceptance_workflow.run`, the real selection table and the
real `safety_acceptance_direct.yaml`, on the real `_run_definition` and the real
`_register_human_task`. Replaced: the HTTP transport (its request body is the observable), the
service-token mint, and the Restate context, which suspends by raising at the first await.

THE GENERIC RUNNER IS THE CONTROL, AND IT DIFFERS IN ONE THING. The same trigger (which carries
`kind: risk_acceptance_medium`) and the same definition, run through `_run_definition` directly
(as BPMNWorkflowRunner runs a client's request), must still register `workflow_ack`. A fix that
read the kind out of the request would turn this arm red: any caller of the generic runner could
then choose the gate its own decision passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

from ._engine_extra import requires_rdflib
from iagent_pure import acceptance_request as ar

_REPO = Path(__file__).resolve().parents[2]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import main  # noqa: E402  — the real executor and register
import restate  # noqa: E402
from agent_fleet.restate_analyst import safety_acceptance_workflow as saw  # noqa: E402
from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    load_workflow_definition,
)

_DIRECT = _REPO / "policy" / "workflows" / "safety_acceptance_direct.yaml"

#: HAZ-1003's review_request in the producer's shape (`measures.draft_risk_assessment`). The
#: rdflib arm below builds it from the producer itself; this literal keeps the other arms
#: running where rdflib is legitimately absent.
_HAZ_1003 = {
    "kind": "risk_acceptance_medium",
    "task_id": "risk-acceptance-HAZ-1003",
    "audience": "risk_acceptance_medium:SUSTAINMENT",
    "title": "Accept Medium risk — HAZ-1003",
    "summary": "seal fixture",
    "requested_by": "engine-safety",
    "subject_ref": "HAZ-1003",
    "payload": {"hazard_id": "HAZ-1003", "risk_level": "Medium", "risk_level_slug": "medium"},
}


@pytest.fixture(autouse=True)
def _stub_mint(monkeypatch):
    # `main` binds `mint_service_token` at import, so main's own name is the one to replace.
    monkeypatch.setattr(main, "mint_service_token", lambda **_: "svc-token-stub")


class _Resp:
    def __init__(self, code=200, body=None, text=""):
        self.status_code, self._body, self.text = code, body or {}, text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class _Suspended(Exception):
    """Raised at the first await, so nothing past the register runs."""


class _Promise:
    def value(self):
        async def _a():
            raise _Suspended()
        return _a()


class _Ctx:
    def __init__(self, key):
        self._key = key
        self.state: dict = {}

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def promise(self, name, type_hint=None):
        return _Promise()


def _recording_post(monkeypatch, resp=None):
    posts: list = []

    def _post(url, json=None, **kw):
        posts.append({"url": url, "body": json})
        return resp or _Resp(200, {"task_id": "t", "recipients": 1})

    monkeypatch.setattr(requests, "post", _post)
    return posts


def _registers(posts):
    return [p["body"] for p in posts if p["url"].endswith("/internal/human_tasks/register")]


def _ctx_for(trigger):
    return _Ctx(ar.acceptance_workflow_id(trigger["hazard_id"], trigger["level_slug"]))


async def _outcome(coro):
    """The exception a run ends in, or None. Captured rather than `pytest.raises`d so a wrong
    outcome fails as an AssertionError that names it, not as the stray exception itself."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


def _sync_outcome(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


async def _run_acceptance(trigger):
    out = await _outcome(saw.run(_ctx_for(trigger), trigger))
    assert isinstance(out, _Suspended), (
        f"the acceptance ended in {type(out).__name__}: {out} instead of suspending on its await")


# ── 1. THE ROW'S KIND IS THE KIND THE REQUEST NAMES ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_haz_1003s_acceptance_registers_the_kind_its_request_names(monkeypatch):
    posts = _recording_post(monkeypatch)
    await _run_acceptance(ar.acceptance_trigger(_HAZ_1003))

    bodies = _registers(posts)
    assert len(bodies) == 1, f"expected one register, got {len(bodies)}: {posts}"
    assert bodies[0]["kind"] == "risk_acceptance_medium", (
        f"the acceptance row registered as {bodies[0]['kind']!r}; /act would gate its decision "
        "on that kind instead of the one the review_request names"
    )
    assert bodies[0]["audience"] == "risk_acceptance_medium:SUSTAINMENT", bodies[0]


@requires_rdflib
@pytest.mark.asyncio
async def test_the_producers_own_request_reaches_the_register_with_its_kind(monkeypatch):
    """The same claim from engine-safety's real draft, so the kind is the producer's, not ours."""
    from agent_fleet.safety_agent import measures

    review_request = measures.draft_risk_assessment(hazard_id="HAZ-1003")["review_request"]
    posts = _recording_post(monkeypatch)
    await _run_acceptance(ar.acceptance_trigger(review_request))

    bodies = _registers(posts)
    assert [b["kind"] for b in bodies] == [review_request["kind"]], (bodies, review_request["kind"])


@pytest.mark.asyncio
async def test_the_generic_runner_does_not_take_the_kind_from_the_request(monkeypatch):
    """CONTROL, one difference: the entry point. Same trigger (it carries
    `kind: risk_acceptance_medium`) and same definition, through `_run_definition` as a client's
    BPMN request reaches it. The row stays `workflow_ack`."""
    posts = _recording_post(monkeypatch)
    trigger = ar.acceptance_trigger(_HAZ_1003)
    assert trigger["kind"] == "risk_acceptance_medium"  # the request DOES name a kind
    wf = load_workflow_definition(_DIRECT)
    ctx = _ctx_for(trigger)
    out = await _outcome(main._run_definition(ctx, ctx.key(), wf.model_dump(), trigger))
    assert isinstance(out, _Suspended), f"{type(out).__name__}: {out}"

    assert [b["kind"] for b in _registers(posts)] == ["workflow_ack"], _registers(posts)


@pytest.mark.parametrize("kind", ["", "workflow_ack", "risk_acceptance_high", "grouped_review"])
@pytest.mark.asyncio
async def test_a_trigger_whose_kind_disagrees_with_its_level_is_refused_before_any_register(
    monkeypatch, kind
):
    posts = _recording_post(monkeypatch)
    trigger = {**ar.acceptance_trigger(_HAZ_1003), "kind": kind}
    out = await _outcome(saw.run(_ctx_for(trigger), trigger))

    assert isinstance(out, restate.TerminalError), (
        f"a trigger naming kind {kind!r} at level_slug 'medium' ended in "
        f"{type(out).__name__}, not a terminal refusal; registered: {_registers(posts)}")
    assert out.status_code == 400, out
    assert "risk_acceptance_medium" in str(out), str(out)
    assert _registers(posts) == [], "a refused trigger still registered a row"


# ── 2. A 4xx FROM THE REGISTER IS TERMINAL ──────────────────────────────────────────────────
# Called with the register's DEFAULT kind: which kind a row has is orthogonal to whether a
# refusal of it is final, and the arms must not depend on the first fix to test the second.

_TASK = {"id": "acceptance", "audience": "risk_acceptance_medium:SUSTAINMENT"}
_WF = "risk-acceptance-HAZ-1003-medium"


@pytest.mark.parametrize("code", [400, 404, 409, 422])
def test_a_4xx_from_the_register_is_terminal(monkeypatch, code):
    _recording_post(monkeypatch, _Resp(code, text='{"detail":"no_entitled_recipients"}'))
    out = _sync_outcome(lambda: main._register_human_task(_WF, _TASK))

    assert isinstance(out, restate.TerminalError), (
        f"a {code} from the register raised {type(out).__name__}, which Restate retries until "
        "it pauses the invocation")
    assert out.status_code == code, out
    assert "no_entitled_recipients" in str(out), "the refusal's reason was dropped"


@pytest.mark.parametrize("code", [429, 500, 503])
def test_a_rate_limit_or_5xx_from_the_register_stays_retryable(monkeypatch, code):
    """CONTROL: the terminal arm must not swallow the transient codes."""
    _recording_post(monkeypatch, _Resp(code))
    out = _sync_outcome(lambda: main._register_human_task(_WF, _TASK))
    assert type(out) is requests.HTTPError, (
        f"a {code} from the register raised {type(out).__name__}; it is transient and must "
        "stay retryable")


@pytest.mark.parametrize("code", [401, 403])
def test_an_auth_denial_from_the_register_is_still_terminal_as_403(monkeypatch, code):
    _recording_post(monkeypatch, _Resp(code))
    out = _sync_outcome(lambda: main._register_human_task(_WF, _TASK))
    assert isinstance(out, restate.TerminalError), f"{type(out).__name__}: {out}"
    assert out.status_code == 403, out


@pytest.mark.asyncio
async def test_haz_1003s_measured_422_fails_the_acceptance_terminally(monkeypatch):
    """The incident's shape end to end: the register refuses with a 422, and the acceptance
    fails terminally with that status instead of retrying into a paused invocation."""
    _recording_post(monkeypatch, _Resp(422, text='{"detail":"no_entitled_recipients"}'))
    trigger = ar.acceptance_trigger(_HAZ_1003)
    out = await _outcome(saw.run(_ctx_for(trigger), trigger))
    assert isinstance(out, restate.TerminalError), (
        f"HAZ-1003's 422 ended the acceptance in {type(out).__name__}, which Restate retries")
    assert out.status_code == 422, out
