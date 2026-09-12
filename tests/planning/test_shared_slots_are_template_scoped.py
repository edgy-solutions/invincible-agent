"""R-005 — a shared slot gates the seed only where a PANEL CONSUMES it.

RULED 2026-09-11, `docs/rulings/README.md#r-005--shared_slots-are-template-scoped`.

THE REGRESSION THIS PREVENTS, and it was refused twice before it could ship. The gate used to
union every REQUIRED shared slot with every panel's `consumes`, so a slot that was merely
DECLARED blocked the seed even when no panel of that template consumed it. Declaring `program`
on both templates — which ADR-0050 §3's carry needs — would therefore have taken `portfolio`,
the only template that draws a board today, from seeding to 409. invincible-agent-5f refused
that dispatch item twice on exactly this evidence rather than shipping the regression, and was
right both times.

A `SharedSlot`'s answer "binds into every panel that CONSUMES it". So the population the seeder
must demand values for is the CONSUMED set, never the declared set: a declared slot nobody
consumes cannot make a panel refuse, and must not make the template refuse either.

AND THE TWO FAULTS ARE KEPT APART. A panel consuming a slot the template never declared is a
broken TEMPLATE — no binding will ever satisfy a typo — and it now answers 422. A declared and
consumed slot with nothing to bind it is the §3 carry and answers 409. Collapsing them into one
status told a reader to wait for a carry that could not help them.

Run: uv run --frozen pytest tests/planning/test_shared_slots_are_template_scoped.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Req:
    headers = {"Authorization": "Bearer t"}


def _template(tid, shared, panels):
    """Build a CanvasTemplate through its REAL model, so a field rename fails here too."""
    from iagent.canvas_template import CanvasTemplate, Panel, SharedSlot

    return CanvasTemplate(
        template_id=tid,
        title=f"{tid} board",
        description=f"{tid} description for the ratified row",
        shared_slots=[
            SharedSlot(name=n, description=f"the {n} this board is about", required=r)
            for n, r in shared
        ],
        panels=[
            Panel(verb=v, role="pair", slots={}, consumes=list(c))
            for v, c in panels
        ],
    )


@pytest.fixture()
def seed(monkeypatch):
    """Call the REAL `/canvas/seed` with only template resolution and the inner seeder faked."""
    import iagent.gateway as gw

    async def _go(tmpl):
        # PATCHED AT THE SOURCE MODULE, NOT THE GATEWAY NAMESPACE. `canvas_seed` imports
        # `load_template` INSIDE the function body, so the gateway module never holds the
        # name and patching it there silently does nothing — the real loader runs and the
        # fixture is a decoration. Found by this test failing with AttributeError rather
        # than by it passing for the wrong reason, which is the lucky direction.
        import iagent.canvas_template as ct

        monkeypatch.setattr(ct, "load_template", lambda _tid: tmpl)
        monkeypatch.setattr(ct, "ratified_template_ids", lambda: [tmpl.template_id])

        async def _inner(inner_req, http_request, current_user):
            n = len(tmpl.panels)
            return {
                "seeded": n, "total": n,
                "artifact_ids": [f"id-{i}" for i in range(n)],
                "results": [{"slot": i, "status": "ok", "detail": None} for i in range(n)],
            }

        monkeypatch.setattr(gw, "seed_portfolio_canvas", _inner)
        req = gw.CanvasSeedRequest(template_id=tmpl.template_id)
        try:
            return 200, await gw.canvas_seed(req, _Req(), _User())
        except HTTPException as exc:
            return exc.status_code, exc.detail

    return _go


@pytest.mark.asyncio
async def test_a_DECLARED_but_unconsumed_slot_does_not_gate_the_seed(seed):
    """THE REGRESSION. `portfolio` may declare `program` for the carry and still seed, because
    none of its panels consume it. This is the assertion the ruling exists to make true."""
    status, body = await seed(_template(
        "portfolio",
        shared=[("program", True)],
        panels=[("mesh:planSchedule", []), ("mesh:planCostCurve", [])],
    ))
    assert status == 200, f"a declared-but-unconsumed shared slot still gated the seed: {body}"


@pytest.mark.asyncio
async def test_a_CONSUMED_and_unbound_slot_STILL_gates_the_seed(seed):
    """THE CONTROL, and without it the fix is indistinguishable from deleting the gate.

    Scoping a check to a smaller population is one edit away from scoping it to nothing. A
    panel that genuinely consumes an unbound slot must still refuse up front rather than
    spending minutes of sequential asks to arrive at a partial-seed refusal."""
    status, detail = await seed(_template(
        "program_finance",
        shared=[("program", True)],
        panels=[("mesh:finVarianceAnalysis", ["program"]), ("mesh:finBurnRate", [])],
    ))
    assert status == 409, f"a consumed, unbound shared slot no longer gates the seed: {detail}"
    assert "program" in str(detail)


@pytest.mark.asyncio
async def test_an_UNDECLARED_consumption_is_422_not_409(seed):
    """The two faults must be distinguishable. A typo in `consumes` is a broken template that no
    binding will ever satisfy; answering 409 tells the reader to wait for the §3 carry."""
    status, detail = await seed(_template(
        "program_finance",
        shared=[("program", True)],
        panels=[("mesh:finBurnRate", ["prgoram"])],
    ))
    assert status == 422, f"an undeclared consumption answered {status}, not 422"
    assert "prgoram" in str(detail) and "does not declare" in str(detail)


@pytest.mark.asyncio
async def test_the_three_outcomes_are_DISTINGUISHABLE(seed):
    """A collapse is a property of a SET. Each case above could pass against a route that
    answered one status if that case happened to expect it, and the defect being fixed is
    precisely two causes having become one."""
    seen = {
        (await seed(_template("portfolio", [("program", True)],
                              [("mesh:planSchedule", [])])))[0],
        (await seed(_template("program_finance", [("program", True)],
                              [("mesh:finBurnRate", ["program"])])))[0],
        (await seed(_template("program_finance", [("program", True)],
                              [("mesh:finBurnRate", ["prgoram"])])))[0],
    }
    assert seen == {200, 409, 422}, f"outcomes collapsed to {sorted(seen)}"


@pytest.mark.asyncio
async def test_a_template_with_no_shared_slots_is_untouched(seed):
    """The floor. Today's only seeding template declares none, and the ruling must not change
    what it does."""
    status, body = await seed(_template(
        "portfolio", shared=[],
        panels=[("mesh:planSchedule", []), ("mesh:planCostCurve", [])],
    ))
    assert status == 200 and body["seeded"] == 2
