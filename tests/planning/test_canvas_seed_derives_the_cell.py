"""`/canvas/seed` derives the cell a persona names, and a panel's caller error is a 4xx that
names the field -- never a 502.

MEASURED CAUSE. cortex-ui's re-send after the "which program?" pick carries `query + program_id
+ persona` and NO domains. `canvas_seed` forwarded the persona alone into each panel's
`/interview/stream`, which refuses a persona without domains (400 `incomplete_override`);
`seed_template_canvas` dropped that body and the aggregate answered 502 `seed_upstream_failed`
with `causes: []`, accusing the server for the caller's request shape.

TWO CHANGES, SEALED HERE. (1) ONE derivation of the cell (`_canvas_seed_domains`), shared by the
ask and the seed, applied to the request before any panel is POSTed. (2) A panel's 4xx keeps its
body; when EVERY panel was refused as a malformed request (400/422, one status) the route
relays that status naming the field. Entitlement (403) is still first and unchanged; 5xx,
timeouts and mixed statuses stay 502.

The fake sits at the network edge (`httpx.AsyncClient` as `seed_template_canvas` uses it): the
fill, the refusals and the aggregate all run for real.

Run: uv run --no-sync pytest tests/planning/test_canvas_seed_derives_the_cell.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent.auth import User  # noqa: E402
from iagent.authz.topaz_client import EntitlementCell, Entitlements  # noqa: E402
from iagent.canvas_template import load_template  # noqa: E402

PERSONA = "PROGRAM_FINANCE_ANALYST"
BINDINGS = {"program": "NP-MERIDIAN"}
# Cells chosen so that `domains_for(PERSONA)` is a strict subset of "every cell's domain" and
# has more than one member: the two derivations cannot agree by accident.
_CELLS = [
    EntitlementCell(persona=PERSONA, domain="PROGRAM_FINANCE"),
    EntitlementCell(persona=PERSONA, domain="PORTFOLIO_PLANNING"),
    EntitlementCell(persona="OTHER_PERSONA", domain="OTHER_DOMAIN"),
]


def _user() -> User:
    return User(
        id="u1", authz_id="alice@example.com", entitlement_source="none",
        entitlements=Entitlements(cells=list(_CELLS)),
    )


class _Req:
    headers = {"Authorization": "Bearer t"}


class _Resp:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code = status
        self._body = body

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        yield "event: final_payload"
        yield "data: {}"


class _Stream:
    def __init__(self, outcome):
        self._o = outcome

    async def __aenter__(self):
        if isinstance(self._o, Exception):
            raise self._o
        return self._o

    async def __aexit__(self, *a):
        return False


class _Posted(list):
    """The JSON payloads POSTed to `/interview/stream`, plus the scripted outcomes."""

    outcomes: list


@pytest.fixture()
def panels(monkeypatch):
    posted = _Posted()
    posted.outcomes = [_Resp(200)]

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        def stream(self, method, url, json=None, headers=None):
            posted.append(json)
            outs = posted.outcomes
            return _Stream(outs[min(len(posted) - 1, len(outs) - 1)])

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    return posted


def _body(status: int, body: dict) -> _Resp:
    return _Resp(status, json.dumps(body).encode())


async def _seed(**fields):
    req = gw.CanvasSeedRequest(template_id="program_finance", **fields)
    try:
        return 200, await gw.canvas_seed(req, _Req(), _user())
    except HTTPException as exc:
        return exc.status_code, exc.detail


def _held() -> list[str]:
    return _user().entitlements.domains_for(PERSONA)


# -- 1-3: the fill -------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("domains", [None, []], ids=["no_domains", "empty_domains"])
async def test_arm1_persona_only_seed_sends_every_panel_the_domains_the_persona_holds(
    panels, domains,
):
    status, body = await _seed(active_persona=PERSONA, active_domains=domains, bindings=BINDINGS)
    assert status == 200, body
    assert len(panels) >= 2
    assert len(_held()) > 1
    for p in panels:
        assert p["active_persona"] == PERSONA
        assert p["active_domains"] == _held()


@pytest.mark.asyncio
async def test_arm2_the_chat_resend_shape_user_persona_and_params_fills_the_same_cell(panels):
    status, body = await _seed(user_persona=PERSONA, params={"program_id": "NP-MERIDIAN"})
    assert status == 200, body
    assert len(panels) >= 2
    for p in panels:
        assert p["active_persona"] == PERSONA
        assert p["active_domains"] == _held()


@pytest.mark.asyncio
async def test_arm3_explicit_active_domains_win_unchanged(panels):
    subset = [_held()[0]]
    assert subset != _held()
    status, body = await _seed(active_persona=PERSONA, active_domains=subset, bindings=BINDINGS)
    assert status == 200, body
    assert len(panels) >= 2
    for p in panels:
        assert p["active_domains"] == subset


# -- 4-5: refused up front, no panel POSTed ------------------------------------------------

@pytest.mark.asyncio
async def test_arm4_a_persona_the_caller_does_not_hold_is_a_policy_403_and_posts_nothing(panels):
    status, detail = await _seed(active_persona="NOT_MY_PERSONA", bindings=BINDINGS)
    assert status == 403, detail
    r = detail["refusal"]
    assert r["policy_id"] == "groups"
    assert r["missing_binding"] == "a_group_granting(NOT_MY_PERSONA)"
    assert r["grantable_by"]
    assert list(panels) == [], "a refused seed still POSTed a panel"


@pytest.mark.asyncio
async def test_arm5_domains_without_a_persona_is_a_400_naming_the_field_and_posts_nothing(panels):
    status, detail = await _seed(active_domains=["PROGRAM_FINANCE"], bindings=BINDINGS)
    assert status == 400, detail
    assert detail["error"] == "incomplete_override"
    assert detail["field"] == "active_persona"
    assert list(panels) == []


# -- 6: one derivation ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_arm6_the_ask_and_the_seed_derive_the_same_domains(panels, monkeypatch):
    asked: list = []

    def _spy(*, user_email, entitled_domains):
        asked.append(list(entitled_domains))
        return lambda *a, **k: []

    monkeypatch.setattr(gw, "_canvas_seed_enumerator", _spy)
    ask_req = gw.CanvasSeedRequest(template_id="program_finance", active_persona=PERSONA)
    try:
        await gw._canvas_seed_ask(load_template("program_finance"), ask_req, _user())
    except Exception:  # noqa: BLE001 - the spy enumerates nothing; only its domains argument matters
        pass
    assert asked, "the ask never built its enumerator"

    status, body = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 200, body
    assert asked[0] == panels[0]["active_domains"] == _held()


# -- 7-11: a panel's refusal keeps its body ------------------------------------------------

_INCOMPLETE = {"detail": {"error": "incomplete_override",
                          "requested": {"persona": PERSONA, "domains": []}}}


@pytest.mark.asyncio
async def test_arm7_every_panel_400_incomplete_override_is_a_400_naming_the_field(panels):
    panels.outcomes = [_body(400, _INCOMPLETE)]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 400, f"a caller-shaped refusal came back {status}"
    assert detail["error"] == "seed_panel_refused"
    assert detail["upstream_error"] == "incomplete_override"
    assert detail["fields"] == ["active_domains"]


@pytest.mark.asyncio
async def test_arm8_every_panel_422_validation_body_is_a_422_naming_the_field_from_loc(panels):
    panels.outcomes = [_body(422, {"detail": [
        {"loc": ["body", "seed_panel", "panel"], "msg": "bad", "type": "x"}]})]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 422, detail
    assert detail["error"] == "seed_panel_refused"
    assert detail["upstream_error"] == "validation_error"
    assert detail["fields"] == ["seed_panel.panel"]


@pytest.mark.asyncio
async def test_arm9_every_panel_500_stays_a_502_and_a_timeout_stays_a_502(panels):
    panels.outcomes = [_body(500, {"detail": "boom"})]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 502
    assert detail["error"] == "seed_upstream_failed"

    del panels[:]
    panels.outcomes = [httpx.ReadTimeout("slow")]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 502
    assert detail["error"] == "seed_upstream_failed"


@pytest.mark.asyncio
async def test_arm10_every_panel_403_with_a_body_is_still_the_entitlement_403(panels):
    panels.outcomes = [_body(403, {"detail": {"error": "cell_not_entitled"}})]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 403, detail
    assert detail["error"] == "cell_cannot_see_verbs"
    assert "cell_not_entitled" in detail["causes"]


@pytest.mark.asyncio
async def test_arm11_mixed_400_and_500_is_a_502_whose_causes_name_the_400(panels):
    panels.outcomes = [_body(400, _INCOMPLETE), _body(500, {"detail": "boom"})]
    status, detail = await _seed(active_persona=PERSONA, bindings=BINDINGS)
    assert status == 502, detail
    assert detail["error"] == "seed_upstream_failed"
    assert "incomplete_override" in detail["causes"]


@pytest.mark.asyncio
async def test_arm3b_the_ask_also_takes_explicit_active_domains_unchanged(monkeypatch):
    asked: list = []

    def _spy(*, user_email, entitled_domains):
        asked.append(list(entitled_domains))
        return lambda *a, **k: []

    monkeypatch.setattr(gw, "_canvas_seed_enumerator", _spy)
    subset = [_held()[0]]
    ask_req = gw.CanvasSeedRequest(
        template_id="program_finance", active_persona=PERSONA, active_domains=subset)
    try:
        await gw._canvas_seed_ask(load_template("program_finance"), ask_req, _user())
    except Exception:  # noqa: BLE001 - only the enumerator's domains argument matters
        pass
    assert asked and asked[0] == subset
