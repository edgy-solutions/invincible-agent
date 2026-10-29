"""ADR-0050 §3's SEED_PANEL — the gates `orchestrate()` raises BEFORE the stream opens, and the
FALL_BACK branch's one hard rule: a seed_panel turn whose declared route the mesh disagrees with
is a VISIBLE failure, never a silent slide into the classified path.

Coordinator review follow-up (2026-10-06): the original seal
(`tests/planning/test_seed_panel_rebuilds_from_the_template.py`) covers `_pre_resolved_from_seed_
panel` directly but never drives `orchestrate()` itself, so none of its six refusal codes were
pinned to the function that actually raises them, and the FALL_BACK branch inside
`_generate_dagster_stream_inner` had no seal of its own at all. This file is both.

SECTION 1 — `orchestrate()`'s gates, called directly (no TestClient, no ASGI transport: a
`Depends(...)` default is just that, a default, and every gated path here raises before ever
touching `current_user.entitlements` beyond what a plain User satisfies). `generate_dagster_
stream` is monkeypatched to a call-counter ("the stub" the coordinator's message names) so a
passing gate is distinguished from a refusing one by WHETHER THE STREAM WAS EVER REACHED, not by
guessing from the status code alone.

SECTION 2 — the FALL_BACK branch, driven through `_generate_dagster_stream_inner` directly with
`dispatch_pre_resolved` stubbed to return FALL_BACK. The seed_panel turn must never reach
`_launch_supervisor_job` (the classified path's first call); the discriminating CONTROL is the
same stub on an ORDINARY (ask-derived) pre-resolved turn, which MUST reach it — so the seal proves
the branch discriminates on `seed_panel`, not merely on the stubbed outcome.

Run: uv run pytest tests/planning/test_seed_panel_gates_and_fallback.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent.auth import User  # noqa: E402


def _user() -> User:
    # entitlement_source="none": honest-empty, no Topaz cells — every gated path below raises
    # or refuses before `orchestrate()` ever branches on a picker override, so a bare user with
    # zero entitlements is sufficient and does not smuggle in a second, untested code path.
    return User(id="u1", authz_id="alice@example.com", entitlement_source="none")


class _HttpReq:
    headers: dict = {}


# ── SECTION 1 — orchestrate()'s pre-stream gates ────────────────────────────────────────────

@pytest.fixture()
def stream_calls(monkeypatch):
    """Replaces `generate_dagster_stream` with a counter. A gate that raises never reaches this
    call; the positive control is the one case that does."""
    calls: list = []

    def _stub(*a, **k):
        calls.append((a, k))
        return None  # never iterated: orchestrate() only constructs the StreamingResponse here.

    monkeypatch.setattr(gw, "generate_dagster_stream", _stub)
    return calls


async def _orchestrate(seed_panel=None, answering_artifact_id=None):
    req = gw.InterviewRequest(
        message="irrelevant label — seed_template_canvas never builds a phrase",
        session_id="s-gate-1",
        seed_panel=seed_panel,
        answering_artifact_id=answering_artifact_id,
    )
    return await gw.orchestrate(req, _HttpReq(), _user())


@pytest.mark.asyncio
async def test_unknown_template_is_422_before_the_stream(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(seed_panel={"template_id": "no_such_template", "panel": 0, "bindings": {}})
    assert ei.value.status_code == 422
    assert stream_calls == [], "a refused seed_panel reached the stream"


@pytest.mark.asyncio
async def test_out_of_range_panel_is_422_before_the_stream(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(seed_panel={"template_id": "program_finance", "panel": 99, "bindings": {}})
    assert ei.value.status_code == 422
    assert stream_calls == []


@pytest.mark.asyncio
async def test_non_int_panel_is_422_before_the_stream(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(
            seed_panel={"template_id": "program_finance", "panel": "0", "bindings": {}}
        )
    assert ei.value.status_code == 422
    assert stream_calls == []


@pytest.mark.asyncio
async def test_a_panel_with_no_subject_is_422_before_the_stream(stream_calls):
    # portfolio's panels declare no `subject` (ADR-0050 §3's carry has not landed there) — this
    # must refuse regardless of bindings, which is why `{}` is enough to exercise it.
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(seed_panel={"template_id": "portfolio", "panel": 0, "bindings": {}})
    assert ei.value.status_code == 422
    assert "no subject" in str(ei.value.detail)
    assert stream_calls == []


@pytest.mark.asyncio
async def test_a_binding_naming_an_undeclared_slot_is_422_before_the_stream(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(
            seed_panel={
                "template_id": "program_finance", "panel": 0,
                "bindings": {"this_slot_does_not_exist": "x"},
            }
        )
    assert ei.value.status_code == 422
    assert stream_calls == []


@pytest.mark.asyncio
async def test_an_unbound_consumed_slot_is_409_before_the_stream(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(seed_panel={"template_id": "program_finance", "panel": 0, "bindings": {}})
    assert ei.value.status_code == 409
    assert stream_calls == []


@pytest.mark.asyncio
async def test_seed_panel_WITH_answering_artifact_id_is_422_before_the_stream(stream_calls):
    """THE NEW GATE (coordinator review, 2026-10-06). A seed is not an answer: a turn naming
    both would silently drop the seed and route as if answering the ask instead."""
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(
            seed_panel={
                "template_id": "program_finance", "panel": 0,
                "bindings": {"program": "NP-MERIDIAN"},
            },
            answering_artifact_id="artifact-1",
        )
    assert ei.value.status_code == 422
    assert "cannot be sent together" in str(ei.value.detail)
    assert stream_calls == []


@pytest.mark.asyncio
async def test_a_valid_seed_panel_PASSES_every_gate_and_reaches_the_stream(stream_calls):
    """THE POSITIVE CONTROL. Every refusal above proves nothing unless something can also get
    through — a gate that rejects everything would pass every red above for the wrong reason."""
    result = await _orchestrate(
        seed_panel={
            "template_id": "program_finance", "panel": 0,
            "bindings": {"program": "NP-MERIDIAN"},
        },
    )
    assert len(stream_calls) == 1, f"expected the gates to clear exactly once, got {stream_calls}"
    assert result is not None


# ── SECTION 2 — the FALL_BACK branch: visible failure for a seed_panel turn, classified path
# for an ordinary one ───────────────────────────────────────────────────────────────────────

@pytest.fixture()
def stubbed_stream(monkeypatch):
    """Everything `_generate_dagster_stream_inner` would otherwise reach for real I/O on this
    path, stubbed — the restate status probe (raises, caught by the gateway's own try/except,
    leaving `is_interview_active=False`), the chain-slot read, the trailing artifact write, the
    classified path's first call (`_launch_supervisor_job`, call-counted), and `dispatch_pre_
    resolved` itself (FALL_BACK, unconditionally)."""
    calls = {"supervisor": 0, "bundles": []}

    class _FakeHttpClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise RuntimeError("no network in this test — caught by the gateway's own guard")

    monkeypatch.setattr(gw.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(gw, "_accumulated_slots", lambda *a, **k: {})

    async def _fake_dispatch_answer_artifact(bundle):
        # THE BUNDLE, NEVER THE STORE: what the real writer is handed (before its backstop).
        calls["bundles"].append(bundle)
        return None

    monkeypatch.setattr(gw, "_dispatch_answer_artifact", _fake_dispatch_answer_artifact)

    async def _fake_launch_supervisor_job(*a, **k):
        calls["supervisor"] += 1
        return None

    monkeypatch.setattr(gw, "_launch_supervisor_job", _fake_launch_supervisor_job)

    def _fake_dispatch_pre_resolved(**kwargs):
        return gw.direct_dispatch.DirectOutcome(
            kind=gw.direct_dispatch.FALL_BACK,
            reason="the mesh no longer agrees with this declared subject",
        )

    monkeypatch.setattr(gw, "dispatch_pre_resolved", _fake_dispatch_pre_resolved)
    return calls


@pytest.mark.asyncio
async def test_a_seed_panel_FALL_BACK_is_a_visible_failure_never_the_classified_path(
    stubbed_stream,
):
    req = gw.InterviewRequest(
        message="irrelevant label",
        session_id="s-seed-fb-1",
        seed_panel={
            "template_id": "program_finance", "panel": 0,
            "bindings": {"program": "NP-MERIDIAN"},
        },
    )
    events = []
    async for ev in gw._generate_dagster_stream_inner(req):
        events.append(ev)
    blob = "".join(events)
    assert "seed_panel_fell_back" in blob, f"no visible failure in the stream: {blob!r}"
    assert stubbed_stream["supervisor"] == 0, (
        "a seed_panel FALL_BACK reached the classified path — it has no phrase to route"
    )


@pytest.mark.asyncio
async def test_the_CONTROL_an_ordinary_FALL_BACK_still_reaches_the_classified_path(
    stubbed_stream, monkeypatch,
):
    """Discriminates the branch on `seed_panel`, not on the stubbed outcome: the SAME FALL_BACK,
    on an ask-derived pre-resolved turn, must fall through exactly as it always has."""
    monkeypatch.setattr(
        gw, "_pre_resolved_from_ask",
        lambda *a, **k: {
            "subject_uri": "http://invincible-agent/fin#Program",
            "subject_instance_id": "NP-MERIDIAN",
            "subject_instance_label": "",
            "verb_iri": "mesh:finVarianceAnalysis",
            "owner_persona": "",
        },
    )
    req = gw.InterviewRequest(
        message="how is NP-MERIDIAN's variance",
        session_id="s-ask-fb-1",
        answering_artifact_id="artifact-1",
        bound_slots={"program_id": "NP-MERIDIAN"},
    )
    events = []
    async for ev in gw._generate_dagster_stream_inner(req):
        events.append(ev)
    blob = "".join(events)
    assert "seed_panel_fell_back" not in blob
    assert stubbed_stream["supervisor"] == 1, (
        "an ordinary (non-seed) FALL_BACK must still route the full path — this is the control "
        "that proves the branch above discriminates on seed_panel, not on the FALL_BACK itself"
    )


@pytest.mark.asyncio
async def test_a_seed_panel_FALL_BACK_because_the_verb_is_not_visible_carries_the_entitlement_cause(
    stubbed_stream, monkeypatch,
):
    """The reason `direct_dispatch` gives when the caller's cell cannot see the verb types the
    pipeline_error, so `/canvas/seed` can answer 403 `cell_cannot_see_verbs`."""
    def _incompatible(**kwargs):
        return gw.direct_dispatch.DirectOutcome(
            kind=gw.direct_dispatch.FALL_BACK,
            reason=f"verb mesh:finX {gw.direct_dispatch.VERB_NO_LONGER_COMPATIBLE} with fin#Y",
        )

    monkeypatch.setattr(gw, "dispatch_pre_resolved", _incompatible)
    req = gw.InterviewRequest(
        message="irrelevant label",
        session_id="s-seed-fb-2",
        seed_panel={
            "template_id": "program_finance", "panel": 0,
            "bindings": {"program": "NP-MERIDIAN"},
        },
    )
    blob = "".join([ev async for ev in gw._generate_dagster_stream_inner(req)])
    assert "seed_panel_verb_not_visible" in blob, blob
    assert "seed_panel_fell_back" not in blob


# ── SECTION 3 — the failed seed's artifact records the template's verb and the cause ─────────
# Layer asserted: the bundle handed to `_dispatch_answer_artifact` (stubbed, so the real
# backstop that writes `NoCauseRecorded` does not run; the point is that it has nothing to do).

_NOT_VISIBLE = "verb mesh:finX {} with fin#Y"


def _pipeline_error(blob: str) -> dict:
    import json as _json
    lines = blob.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("event: pipeline_error"):
            return _json.loads(lines[i + 1][len("data: "):])
    raise AssertionError(f"no pipeline_error in the stream: {blob!r}")


@pytest.mark.asyncio
@pytest.mark.parametrize("not_visible", [True, False], ids=["verb_not_visible", "fell_back"])
async def test_a_failed_seed_artifact_records_the_templates_verb_and_the_cause(
    stubbed_stream, monkeypatch, not_visible,
):
    from iagent.canvas_template import load_template, panel_dispatch

    reason = (
        _NOT_VISIBLE.format(gw.direct_dispatch.VERB_NO_LONGER_COMPATIBLE) if not_visible
        else "the mesh no longer agrees with this declared subject"
    )
    monkeypatch.setattr(
        gw, "dispatch_pre_resolved",
        lambda **k: gw.direct_dispatch.DirectOutcome(
            kind=gw.direct_dispatch.FALL_BACK, reason=reason),
    )
    bindings = {"program": "NP-MERIDIAN"}
    template = load_template("program_finance")
    verb, _subject, _params = panel_dispatch(template, 0, bindings)
    panel_subject = template.panels[0].subject
    req = gw.InterviewRequest(
        message="irrelevant label", session_id="s-seed-fb-3",
        seed_panel={"template_id": "program_finance", "panel": 0, "bindings": bindings},
    )
    blob = "".join([ev async for ev in gw._generate_dagster_stream_inner(req)])

    (bundle,) = stubbed_stream["bundles"]
    ri = bundle["resolved_intent"]
    assert bundle["status"] == "failed"
    assert verb and ri["verb_iri"] == verb
    assert ri["subject_uri"] == panel_subject
    cause = ri["failure_cause"]
    assert cause["exception"] == _pipeline_error(blob)["cause"]
    assert cause["message"] == reason
    assert cause["exception"] != "NoCauseRecorded"
    assert cause["exception"] == (
        "seed_panel_verb_not_visible" if not_visible else "seed_panel_fell_back")


def _sse_events(blob: str, name: str) -> list[dict]:
    import json as _json
    lines = blob.splitlines()
    return [
        _json.loads(lines[i + 1][len("data: "):])
        for i, ln in enumerate(lines) if ln == f"event: {name}"
    ]


_SENTINEL = "http://internal-host.example"
_DD = gw.direct_dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reported, step",
    [
        ([(_DD.STAGE_VERIFYING, "started"), (_DD.STAGE_VERIFYING, "completed"),
          (_DD.STAGE_CALLING, "started")], _DD.STAGE_CALLING),
        ([], _DD.STAGE_VERIFYING),
    ],
    ids=["at_calling", "before_any_stage"],
)
async def test_a_dispatch_raise_on_a_seed_turn_fails_visibly_naming_its_step(
    stubbed_stream, monkeypatch, reported, step,
):
    """A raise out of `dispatch_pre_resolved` on a seed turn is a retryable 5xx-class failure
    bound to the step it died in, never the full supervisor run (a seed turn has no phrase).
    With no stage reported, no stage event is honest (nothing started): the error is bound to
    `verifying_route` by `kind` alone."""
    from iagent.canvas_template import load_template, panel_dispatch

    def _raises(**kwargs):
        for kind, status in reported:
            kwargs["on_stage"](kind, status)
        raise RuntimeError(f"engine unreachable at {_SENTINEL}/x")

    monkeypatch.setattr(gw, "dispatch_pre_resolved", _raises)
    bindings = {"program": "NP-MERIDIAN"}
    template = load_template("program_finance")
    verb, _subject, _params = panel_dispatch(template, 0, bindings)
    req = gw.InterviewRequest(
        message="irrelevant label", session_id="s-seed-raise-1",
        seed_panel={"template_id": "program_finance", "panel": 0, "bindings": bindings},
    )
    blob = "".join([ev async for ev in gw._generate_dagster_stream_inner(req)])

    assert stubbed_stream["supervisor"] == 0, "a seed-turn raise fell through to the full run"
    err = _pipeline_error(blob)
    assert err["kind"] == step
    assert err["retryable"] is True
    assert err["cause"] == "seed_panel_dispatch_raised"
    failed = [e["kind"] for e in _sse_events(blob, "pipeline_stage") if e["status"] == "failed"]
    assert failed == ([step] if reported else [])

    (bundle,) = stubbed_stream["bundles"]
    assert bundle["status"] == "failed"
    ri = bundle["resolved_intent"]
    assert verb and ri["verb_iri"] == verb
    assert ri["subject_uri"] == template.panels[0].subject
    cause = ri["failure_cause"]
    assert cause["exception"] == err["cause"]
    assert cause["step"] == step
    assert _SENTINEL not in cause["message"]
    assert _SENTINEL not in err["message"]
