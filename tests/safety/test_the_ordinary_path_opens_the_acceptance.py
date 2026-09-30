"""R-076 on the ORDINARY answer path: a drafted hazard opens its acceptance without an ask.

MEASURED BEFORE THIS FILE (2026-09-29, fleet `ec055c49`, read-only). The only consumer of
`review_request` lived in `_stream_direct_outcome`, which runs only for a turn that answers an ask
(`lineage_claim.pre_resolved_route_allowed`). "Draft a risk assessment for HAZ-1003" names its
hazard, never asks, and went down the Dagster path: 34 turns in a pod's life, zero on the direct
path, zero risk rows in `human_task_projection`. Meanwhile engine-safety's own
`/measure/draft_risk_assessment` answer carried the block in full: kind `risk_acceptance_medium`,
audience `risk_acceptance_medium:SUSTAINMENT`. Engine F's render drops it, and that is the only
thing the ordinary path read back.

THE CARRIER. `execute_subtask` materializes `subtask_review_request` from the engine's own body,
and the gateway reads it after the poll loop and opens the acceptance through the SAME body the
direct path uses.

WHAT THIS FILE PROVES, AND WHAT IT DOES NOT.
  * the JOIN: the supervisor's real emitter, shaped as the gateway's GraphQL read returns it,
    reaches exactly one `/SafetyAcceptance/<key>/run/send` with the trigger the reader derives;
  * the consumer's refusals to lie: a duplicate materialization opens one acceptance, not two,
    and an EMPTY read is recorded as unknown, not as "no request";
  * the wiring on both ends, by AST: the generator awaits the consumer after the poll loop and
    before the success branch, and `execute_subtask` feeds the emitter the engine's body.
  NOT PROVED HERE: that a real turn writes a row. That is
  `tests/sandbox_e2e/_seal_haz1003_acceptance.py`, a script rather than a test module, and it runs
  after the roll that deploys this code, because firing it writes through the real path.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from ._engine_extra import requires_rdflib
from iagent_pure import acceptance_request as ar

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ONE MODULE OBJECT PER FILE, each on the import its own area's seals already use: the gateway as
# `iagent.gateway` (the direct-path seal), the supervisor as `src.iagent.defs.dynamic_supervisor`
# (the identity seal). Neither module is imported twice under two names here.
import iagent.gateway as gw  # noqa: E402

_GATEWAY_SRC = _SRC / "iagent" / "gateway.py"
_SUPERVISOR_SRC = _SRC / "iagent" / "defs" / "dynamic_supervisor.py"
_HAZARD = "HAZ-1003"


def _supervisor():
    return pytest.importorskip(
        "src.iagent.defs.dynamic_supervisor",
        reason="dagster not importable here, so the emitter half is VOID, not green",
    )


@pytest.fixture
def draft():
    """The REAL engine body, not a hand-written block. A fixture thinner than the engine's answer
    tests a shape the system never produces."""
    from agent_fleet.safety_agent import matrix, measures
    matrix.reset_cache()
    try:
        yield measures.draft_risk_assessment(hazard_id=_HAZARD)
    finally:
        matrix.reset_cache()


class _Ctx:
    """`execute_subtask`'s context, as far as the emitter touches it."""

    def __init__(self):
        self.events = []

    def log_event(self, ev):
        self.events.append(ev)


def _as_graphql(mat) -> dict:
    """A Dagster `AssetMaterialization` in the shape `_get_run_events` returns it.

    Only TEXT entries are converted, and any other kind fails the test. The gateway's query asks
    for `... on TextMetadataEntry { text }` among others, so an entry of a kind the conversion
    does not know would be a claim about the query that this test has not checked.
    """
    from dagster import TextMetadataValue
    entries = []
    for label, value in mat.metadata.items():
        assert isinstance(value, TextMetadataValue), (
            f"`{label}` is {type(value).__name__}; the carrier is sealed for text entries only"
        )
        entries.append({"label": label, "text": value.text})
    return {"assetKey": {"path": list(mat.asset_key.path)}, "metadataEntries": entries}


_ROSTER = {"assetKey": {"path": ["active_agent_roster"]}, "metadataEntries": []}


class _Restate:
    """Stands in for `httpx.AsyncClient` against the Restate ingress. Records every POST."""

    def __init__(self, boom=False):
        self.boom, self.posts = boom, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": dict(headers or {})})
        if self.boom:
            raise RuntimeError("restate ingress refused")
        return self

    def raise_for_status(self):
        return None


def _bundle():
    return {"id": "urn:li:answerArtifact:test", "resolved_intent": {}}


async def _consume(monkeypatch, mats, *, boom=False):
    fake = _Restate(boom=boom)

    async def _events(run_id):
        assert run_id == "run-1"
        return mats

    monkeypatch.setattr(gw, "_get_run_events", _events)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = _bundle()
    errors = await gw._open_acceptances_from_run("run-1", bundle)
    return fake, bundle, errors


def _emit(draft) -> list:
    ds = _supervisor()
    ctx = _Ctx()
    emitted = ds._log_subtask_review_request_asset(
        ctx, engine_response=draft, sub_query=f"draft a risk assessment for {_HAZARD}",
    )
    return emitted, ctx.events


# ---------------------------------------------------------------------------
# The fixture discriminates: it must carry the thing the consumer keys on.
# ---------------------------------------------------------------------------

@requires_rdflib
def test_the_real_draft_asks_for_the_acceptance_this_file_expects(draft):
    rr = ar.review_request_of(draft)
    assert rr, "the HAZ-1003 draft carries no review_request, so every arm below would be vacuous"
    assert rr["kind"] == "risk_acceptance_medium", rr


# ---------------------------------------------------------------------------
# The join: supervisor's real emitter → gateway's real reader → one send.
# ---------------------------------------------------------------------------

@requires_rdflib
@pytest.mark.asyncio
async def test_the_emitted_request_opens_exactly_one_acceptance(draft, monkeypatch):
    emitted, events = _emit(draft)
    assert emitted is True and len(events) == 1, events
    rr = ar.review_request_of(draft)
    mat = _as_graphql(events[0])

    # THE SAME MATERIALIZATION TWICE, because `_get_run_events` merges `eventConnection` with
    # `stepStats` and so returns it twice. The roster is first, as every run materializes it.
    fake, bundle, errors = await _consume(monkeypatch, [_ROSTER, mat, mat])

    assert errors == []
    assert len(fake.posts) == 1, fake.posts
    trigger = ar.acceptance_trigger(rr)
    wf = ar.acceptance_workflow_id(trigger["hazard_id"], trigger["level_slug"])
    post = fake.posts[0]
    assert post["url"] == f"{gw._RESTATE_INGRESS_URL}/SafetyAcceptance/{gw._restate_key(wf)}/run/send"
    # NO INGRESS IDEMPOTENCY KEY ON A WORKFLOW HANDLER. Restate 1.6 refuses it with 400 "cannot use
    # the idempotency key with workflow handlers" -- the workflow key already is the idempotency.
    # This line asserted the header's PRESENCE, so it was green on the one request the live
    # fleet refused on every turn (measured 2026-09-30, rev 159: 0 HAZ-1003 tasks, 4 fires).
    assert "idempotency-key" not in {k.lower() for k in (post["headers"] or {})}, post["headers"]
    assert post["json"] == trigger
    assert trigger["kind"] == "risk_acceptance_medium"

    dispatched = bundle["resolved_intent"]["acceptance_dispatched"]
    assert dispatched == [{
        "workflow": wf, "kind": trigger["kind"], "audience": trigger["audience"],
        "subject_ref": rr.get("subject_ref"), "path": "run",
    }]


@requires_rdflib
def test_the_carrier_reads_back_as_the_request_the_engine_made(draft):
    _, events = _emit(draft)
    assert gw._project_review_request(_as_graphql(events[0])) == ar.review_request_of(draft)


@requires_rdflib
def test_a_refused_draft_emits_nothing():
    from agent_fleet.safety_agent import measures
    refused = measures.draft_risk_assessment(hazard_id="")
    assert refused.get("refused"), "the control is not a refusal, so it controls nothing"
    emitted, events = _emit(refused)
    assert emitted is False and events == []


# ---------------------------------------------------------------------------
# The consumer does not read a failure as an answer.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_empty_read_is_unknown_not_no(monkeypatch):
    fake, bundle, errors = await _consume(monkeypatch, [])
    assert fake.posts == [] and errors == []
    assert bundle["resolved_intent"]["acceptance_check"] == {"materializations_read": 0}


@pytest.mark.asyncio
async def test_a_run_that_asked_for_nothing_opens_nothing_and_says_nothing(monkeypatch):
    """The control for the arm above: a SUCCESSFUL read with no request is not an empty read."""
    fake, bundle, errors = await _consume(monkeypatch, [_ROSTER])
    assert fake.posts == [] and errors == []
    assert "acceptance_check" not in bundle["resolved_intent"]
    assert "acceptance_dispatched" not in bundle["resolved_intent"]


@requires_rdflib
@pytest.mark.asyncio
async def test_a_refused_send_is_an_error_the_turn_shows(draft, monkeypatch):
    _, events = _emit(draft)
    fake, bundle, errors = await _consume(monkeypatch, [_as_graphql(events[0])], boom=True)
    assert len(fake.posts) == 1
    assert len(errors) == 1, errors
    head, data = errors[0].split("\n")[:2]
    assert head == "event: pipeline_error"
    body = json.loads(data[len("data: "):])
    assert body["cause"] == "acceptance_not_opened" and body["retryable"] is True
    rec = bundle["resolved_intent"]["acceptance_not_opened"]
    assert rec["where"] == "run/review_request_consumer"
    assert rec["kind"] == "risk_acceptance_medium"
    assert "acceptance_dispatched" not in bundle["resolved_intent"]


# ---------------------------------------------------------------------------
# Wiring. Both ends, by AST, because neither function is drivable without a Dagster run.
# ---------------------------------------------------------------------------

def _fn(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(found) == 1, f"{name}: {len(found)} definitions"
    return found[0]


def _calls(node, name):
    return [c for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name]


def test_the_stream_awaits_the_consumer_after_the_poll_and_before_the_success_branch():
    fn = _fn(_GATEWAY_SRC, "_generate_dagster_stream_inner")
    body = fn.body

    def is_consumer(s):
        return (isinstance(s, ast.For) and isinstance(s.iter, ast.Await)
                and isinstance(s.iter.value, ast.Call)
                and isinstance(s.iter.value.func, ast.Name)
                and s.iter.value.func.id == "_open_acceptances_from_run")

    consumers = [i for i, s in enumerate(body) if is_consumer(s)]
    # BODY LEVEL, not merely present. Nested under a branch, the consumer would run for some
    # turns only, which is the defect this file exists for.
    assert len(consumers) == 1, "the consumer is not a body-level statement of the stream"
    i = consumers[0]
    call = body[i].iter.value
    assert [ast.unparse(a) for a in call.args] == ["run_id", "_artifact_bundle"]
    # The loop YIELDS what the consumer returns, or a refused send is silent.
    yields = [n for n in ast.walk(body[i]) if isinstance(n, ast.Yield)]
    assert yields and ast.unparse(yields[0].value) == body[i].target.id

    polls = [j for j, s in enumerate(body)
             if isinstance(s, ast.For) and _calls(s, "_get_run_status")]
    assert len(polls) == 1, "the poll loop is not identifiable by the status call it makes"
    success = [j for j, s in enumerate(body)
               if isinstance(s, ast.If) and ast.unparse(s.test) == "is_success"]
    assert len(success) == 1
    assert polls[0] < i < success[0], (polls, i, success)


def test_execute_subtask_feeds_the_emitter_the_engine_body():
    fn = _fn(_SUPERVISOR_SRC, "execute_subtask")
    calls = _calls(fn, "_log_subtask_review_request_asset")
    assert len(calls) == 1, calls
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    body_name = kw.get("engine_response")
    # THE NAME BOUND FROM THE ENGINE'S HTTP ANSWER, derived rather than typed.
    bound = [t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
             and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
             and n.value.func.attr == "json" for t in n.targets if isinstance(t, ast.Name)]
    assert bound == [body_name], (bound, body_name)
    # At body level, so no branch between the answer and the carrier decides to skip it.
    top = [s for s in fn.body if calls[0] in list(ast.walk(s))]
    assert len(top) == 1 and isinstance(top[0], ast.Try), "the emitter is nested under a branch"


# ── THE CLASS: no gateway send to ANY Restate Workflow carries an ingress idempotency key ───────

_REPO = Path(__file__).resolve().parents[2]


def _workflow_names() -> set:
    """Every `Workflow("<Name>")` the fleet registers, DERIVED from the engine sources."""
    names = set()
    for src in (_REPO / "agent_fleet").rglob("*.py"):
        if "__pycache__" in src.parts or ".venv" in "/".join(src.parts):
            continue
        try:
            tree = ast.parse(src.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Workflow" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                names.add(node.args[0].value)
    return names


def _posts_to(tree, name: str):
    """Every `.post(...)` call in the gateway whose URL spells `/<name>/`."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "post" and node.args):
            continue
        consts = [c.value for c in ast.walk(node.args[0])
                  if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if any(f"/{name}/" in c or c.startswith(f"{name}/") for c in consts):
            yield node


def _enclosing(tree, call):
    """The innermost function whose body holds `call`."""
    best = None
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(n is call for n in ast.walk(fn)):
            if best is None or fn.lineno >= best.lineno:
                best = fn
    return best


def _names_idempotency_key(tree, call) -> bool:
    """Does the send carry the header? Read over the ENCLOSING FUNCTION, not the call's own
    `headers=` literal: the ReviewStarter send builds its headers in a variable first, and a
    matcher reading only the literal would be blind to that form (the positive control below)."""
    scope = _enclosing(tree, call) or call
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str)
               and c.value.lower() == "idempotency-key" for c in ast.walk(scope))


def test_the_workflow_population_is_real():
    names = _workflow_names()
    assert "SafetyAcceptance" in names, names


def test_no_gateway_send_to_a_workflow_carries_an_idempotency_key():
    tree = ast.parse(Path(gw.__file__).read_text(encoding="utf-8"))
    names = _workflow_names()
    reached = {n for n in names if any(True for _ in _posts_to(tree, n))}
    # THE MATCHER POINTS AT SOMETHING: the one workflow the gateway is known to send to.
    assert "SafetyAcceptance" in reached, (names, reached)
    offenders = sorted(n for n in reached
                       if any(_names_idempotency_key(tree, c) for c in _posts_to(tree, n)))
    assert offenders == [], (
        f"gateway sends an idempotency-key to workflow(s) {offenders}; Restate refuses it (400)")


def test_the_matcher_sees_a_header_on_a_service_send():
    """Positive control: ReviewStarter is a SERVICE and legitimately carries the header, built
    in a variable. The matcher must see it there, or the offender arm above cannot fire."""
    tree = ast.parse(Path(gw.__file__).read_text(encoding="utf-8"))
    assert "ReviewStarter" not in _workflow_names()
    sends = list(_posts_to(tree, "ReviewStarter"))
    assert sends, "the matcher found no ReviewStarter send"
    assert all(_names_idempotency_key(tree, c) for c in sends)
