"""THE SIX-PANEL SEAL — `program_finance`, bound, seeds through its OWN declared verbs.

ADR-0050 §3's carry, landed: the picker sends `template_id: "program_finance"` plus a binding
for the `program` shared slot, and gets six artifact ids back, one per panel in panel order —
each panel dispatched as the template's DECLARED verb with the template's DECLARED slots, never
a phrase list. `seed_template_canvas` (gateway.py) is what makes this true; this file is its
seal.

THE STREAM-SIDE HALF. `seed_panel`'s dispatch route (`src/iagent/gateway.py`'s `/interview/stream`
handling) reads `subject_uri` straight off the ratified template's `Panel.subject` — no
verb_iri -> input_uri lookup exists or is needed, because the TEMPLATE declares the verb's input
class (nothing in the fleet maps verb -> input class). `dispatch_pre_resolved`'s
own `find_compatible_verbs` call still CONFIRMS that declaration against the live mesh on every
dispatch — a declared `subject` the mesh disagrees with is FALL_BACK, a visible failure, never a
silent route. This file's drift seal (below) guards the DECLARATION side: every ratified panel
that declares a `subject` must match the producing engine's own catalogue `input_uri` for that
verb, derived by importing the engine's `VERBS`, never a literal table.

Run: uv run pytest tests/planning/test_program_finance_seeds_six_panels.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Req:
    headers = {"Authorization": "Bearer t"}


class _FakeStreamCtx:
    """Stands in for `httpx.AsyncClient().stream(...)`'s async context manager.

    Always reports a clean `final_payload` — this test is about WHAT is sent and in what
    ORDER, not about failure handling (that is `seed_portfolio_canvas`'s own territory and
    is not re-tested here).
    """

    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        yield "event: final_payload"
        yield "data: {}"


class _FakeClient:
    """Stands in for `httpx.AsyncClient`. Records every `.stream(...)` call's method, url and
    json body so the test can assert on them without a live engine."""

    calls: list[dict] = []  # class-level: `async with httpx.AsyncClient(...) as client` makes
    # a fresh instance per call, so the record has to live above any one instance.

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None, headers=None):
        _FakeClient.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return _FakeStreamCtx()


@pytest.fixture()
def fake_stream(monkeypatch):
    import iagent.gateway as gw

    _FakeClient.calls = []
    monkeypatch.setattr(gw.httpx, "AsyncClient", _FakeClient)
    return _FakeClient


async def _seed_program_finance(bindings):
    import iagent.gateway as gw

    req = gw.CanvasSeedRequest(template_id="program_finance", bindings=bindings)
    try:
        return 200, await gw.canvas_seed(req, _Req(), _User())
    except HTTPException as exc:
        return exc.status_code, exc.detail


@pytest.mark.asyncio
async def test_six_panels_dispatch_in_order_each_carrying_seed_panel(fake_stream):
    """THE SEAL. One POST per panel, panel order 0..5, each payload's `seed_panel` names the
    template, the panel index and the caller's binding — never a phrase."""
    status, body = await _seed_program_finance({"program": "NP-MERIDIAN"})
    assert status == 200, f"a fully bound program_finance request was refused: {body}"

    calls = fake_stream.calls
    assert len(calls) == 6, f"expected one POST per panel, got {len(calls)}"

    for i, call in enumerate(calls):
        assert call["url"].endswith("/interview/stream")
        sp = (call["json"] or {}).get("seed_panel")
        assert sp is not None, f"panel {i}'s POST carries no seed_panel: {call['json']}"
        assert sp["template_id"] == "program_finance"
        assert sp["panel"] == i, f"panel index out of order: expected {i}, got {sp['panel']}"
        assert sp["bindings"] == {"program": "NP-MERIDIAN"}
        # The caller's own Authorization header reaches every panel — the same requirement
        # RULING (a) carries for the portfolio seeder.
        assert call["headers"].get("Authorization") == "Bearer t"


@pytest.mark.asyncio
async def test_the_response_carries_six_non_null_ids_in_order(fake_stream):
    """cortex's contract: `artifact_ids`, slot-ordered, nothing else — the same contract
    `seed_portfolio_canvas`'s alias honours, now exercised on the per-panel path."""
    status, body = await _seed_program_finance({"program": "NP-MERIDIAN"})
    assert status == 200, f"refused: {body}"
    ids = body["artifact_ids"]
    assert len(ids) == 6, f"expected six artifact ids, got {len(ids)}: {ids}"
    assert all(ids), f"a null hole survived to the response: {ids}"
    assert len(set(ids)) == 6, f"duplicate artifact id across panels: {ids}"


@pytest.mark.asyncio
async def test_without_the_binding_the_seeder_is_never_reached(fake_stream):
    """THE CONTROL. Without `program` bound, the 409 must fire before any POST — the per-panel
    seeder existing must not make the §3 carry's gate optional."""
    status, body = await _seed_program_finance(None)
    assert status == 409, f"expected the unbound-shared-slot refusal, got {status}: {body}"
    assert fake_stream.calls == [], "a POST was issued despite the shared slot being unbound"


# ── THE DRIFT SEAL — a declared `subject` must equal the PRODUCING ENGINE'S OWN input_uri ──────
#
# The map below is DERIVED, never written as a literal table: each ratified panel's verb is
# looked up in the owning engine's own `VERBS` catalogue (imported, not restated), and the
# catalogue's `input_uri` for that `fn` is what the panel's `subject` is checked against. A panel
# whose `subject` disagrees with its own engine's declaration is the exact staleness
# `dispatch_pre_resolved`'s runtime `find_compatible_verbs` call exists to catch at dispatch time
# — this seal catches the AUTHORING-time version of the same mistake, before it ever reaches a
# live mesh. `portfolio.yaml` declares no `subject` on any panel (ADR-0050 §3's carry has not
# landed there), so it contributes nothing to this seal and is not asserted on here.
def _verb_to_input_uri(verbs: list[dict]) -> dict[str, str]:
    """`{"mesh:<verb>": "<input_uri>"}`, derived from one engine's own VERBS list."""
    return {v["verb"]: v["input_uri"] for v in verbs}


def test_every_declared_subject_matches_its_engine_s_own_input_uri():
    from agent_fleet.finance_agent.main import VERBS as FIN_VERBS

    import iagent.canvas_template as ct

    # Only engines that back a RATIFIED template declaring `subject` need a map entry — today
    # that is finance alone. A second template declaring `subject` against a different engine
    # adds its own VERBS import and map here; it must not grow a hand-typed input_uri table.
    expected = _verb_to_input_uri(FIN_VERBS)

    checked = 0
    for template_id in ct.ratified_template_ids():
        template = ct.load_template(template_id)
        for i, panel in enumerate(template.panels):
            if panel.subject is None:
                continue
            assert panel.verb in expected, (
                f"{template_id} panel {i} declares verb {panel.verb!r}, which the finance "
                f"engine's own VERBS catalogue does not list — subject drift cannot even be "
                f"checked for an unrecognised verb."
            )
            assert panel.subject == expected[panel.verb], (
                f"{template_id} panel {i} ({panel.verb}) declares subject {panel.subject!r}, "
                f"but the finance engine's own VERBS catalogue says this verb's input_uri is "
                f"{expected[panel.verb]!r}. The template's declaration has drifted from the "
                f"engine it describes."
            )
            checked += 1

    assert checked == 6, (
        f"expected all six program_finance panels to declare a checkable subject, got {checked} "
        f"— either a panel's subject went missing or a new subject-declaring panel needs this "
        f"seal's attention."
    )
