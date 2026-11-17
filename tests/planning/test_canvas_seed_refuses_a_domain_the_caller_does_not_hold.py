"""`/canvas/seed` treats a client-sent domain list as a request, never as a grant.

MEASURED CAUSE (Lane 1, 2026-11-16). `/orchestrate` already refused a picker cell the caller did
not hold (403 `cell_not_entitled`). `/canvas/seed` did not. Its 409 path builds the "which
program?" ask with `_canvas_seed_ask`, which sent the client's `active_domains`, as given, to
engine-o's `/enumerate_instances` as `entitled_domains`. Engine-o decides origin visibility from
that list (`agent_fleet/utils/origin_entitlement.py`, `can_consume`), so naming a domain the
caller does not hold widened what the ask could enumerate. The panels themselves were safe,
because each one goes back through `/interview/stream` and its gate. The ask did not.

THE RULE IS THE CELL, not the domain: a domain held under another persona is still refused.
One miss refuses the request, and nothing is silently dropped.

Run: uv run --no-sync pytest tests/planning/test_canvas_seed_refuses_a_domain_the_caller_does_not_hold.py -v
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
from iagent.authz.topaz_client import EntitlementCell, Entitlements  # noqa: E402

PERSONA = "PROGRAM_FINANCE_ANALYST"
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


@pytest.fixture()
def wire(monkeypatch):
    """Records every domain list that would leave the BFF: the ask's enumerator and the panels'
    `/interview/stream` posts. Neither reaches a network."""
    seen: dict[str, list] = {"enumerator": [], "panels": []}

    def _enumerator(*, user_email, entitled_domains):
        seen["enumerator"].append(list(entitled_domains))
        return lambda _cls, **_k: {"outcome": "members", "members": []}

    class _Resp:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield "event: final_payload"
            yield "data: {}"

    class _Stream:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        def stream(self, method, url, json=None, headers=None):
            seen["panels"].append(list((json or {}).get("active_domains") or []))
            return _Stream()

    monkeypatch.setattr(gw, "_canvas_seed_enumerator", _enumerator)
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    return seen


async def _seed(**fields):
    req = gw.CanvasSeedRequest(template_id="program_finance", **fields)
    try:
        return 200, await gw.canvas_seed(req, _Req(), _user())
    except HTTPException as exc:
        return exc.status_code, exc.detail


@pytest.mark.asyncio
async def test_a_domain_the_caller_does_not_hold_is_refused_before_anything_leaves(wire):
    status, detail = await _seed(active_persona=PERSONA, active_domains=["DEFENSE"],
                                 bindings={"program": "NP-MERIDIAN"})
    assert status == 403, detail
    assert detail["error"] == "cell_not_entitled"
    assert detail["refusal"]["missing_binding"] == f"a_group_granting({PERSONA}, DEFENSE)"
    assert wire == {"enumerator": [], "panels": []}


@pytest.mark.asyncio
async def test_the_409_ask_never_enumerates_with_an_unheld_domain(wire):
    """THE PATH THAT LEAKED. No bindings, so the seed takes the 409 path and builds the ask."""
    status, detail = await _seed(active_persona=PERSONA, active_domains=["DEFENSE"])
    assert status == 403, detail
    assert wire["enumerator"] == []


@pytest.mark.asyncio
async def test_control_the_409_ask_enumerates_with_the_held_domains(wire):
    """The instrument can see the leak: with held domains the ask DOES reach the enumerator,
    with exactly the list the caller named."""
    status, _detail = await _seed(active_persona=PERSONA, active_domains=["PROGRAM_FINANCE"])
    assert status == 409
    assert wire["enumerator"] == [["PROGRAM_FINANCE"]]


@pytest.mark.asyncio
async def test_one_unheld_domain_refuses_the_whole_list_and_nothing_is_dropped(wire):
    status, detail = await _seed(active_persona=PERSONA,
                                 active_domains=["PROGRAM_FINANCE", "DEFENSE"])
    assert status == 403, detail
    assert "['DEFENSE']" in detail["message"]
    assert wire == {"enumerator": [], "panels": []}


@pytest.mark.asyncio
async def test_a_domain_held_under_ANOTHER_persona_is_still_refused(wire):
    """The grant is a cell. OTHER_DOMAIN is held, but under OTHER_PERSONA."""
    status, detail = await _seed(active_persona=PERSONA, active_domains=["OTHER_DOMAIN"])
    assert status == 403, detail
    assert detail["error"] == "cell_not_entitled"


@pytest.mark.asyncio
async def test_control_held_domains_still_seed(wire):
    status, _detail = await _seed(active_persona=PERSONA, active_domains=["PROGRAM_FINANCE"],
                                  bindings={"program": "NP-MERIDIAN"})
    assert status == 200
    assert wire["panels"] and all(p == ["PROGRAM_FINANCE"] for p in wire["panels"])
