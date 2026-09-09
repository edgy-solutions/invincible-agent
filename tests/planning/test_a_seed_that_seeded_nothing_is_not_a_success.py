"""`/canvas/seed` — nothing seeded is a FAILURE, not a partial seed, and not a 200.

MEASURED 2026-09-09, AND IT MADE A SEAL LIE. All five seeded asks returned HTTP 403 in ~0.1s
each, this route answered **200**, and ADR-0050's canvas-determinism seal compared two empty
boards, found them equal, and reported **PASS in 2.48 seconds** against a run that takes
fifty minutes. Four tests passed. No assertion fired. The only wrong-looking thing was the
clock — and reporting on the exit code would have said "seal 3 passes today", which is the
opposite of true and would have deleted the entire case for the seeder change it exists to
justify.

THE GUARD INHERITED THE CASE IT WAS WRITTEN FOR. Refusing a PARTIAL seed with 200-and-empty
is correct and stays: cortex has a no-canvas path, and compacting would shift every card
after the failed slot up one and draw a board that looks plausible and is wrong. But
`seeded != total` is also true when `seeded == 0`, and a caller who seeded NOTHING has not
received a refusal to compose — they have received a failure. `seeded`/`total` carried the
truth in the body while the status line said success, and the status line is what a headless
caller reads. That is what a status is for.

**A GUARD THAT EXEMPTS A CASE INHERITS THAT CASE'S FAILURE MODE** — invincible-agent-5f's
formulation, from finding the same shape one layer up in the same hour: their arm voided when
a *seeded* panel recorded no verb and exempted panels the seeder reported as failed, which is
right and holds only while something succeeded. Two total failures were two empty sets scored
as agreement.

THE CAUSE TRAVELS, because the two total failures have opposite repairs. Five upstream 403s
mean the caller is not entitled to the cell these panels' subjects live in — `policy/groups.yaml`
warns of exactly this, where a non-holder "grounds to nothing and routes nowhere, while every
engine reports healthy". That is the caller's answer, and it is a 403. Anything else upstream
is a 502: the seed could not be performed, and that is ours.

Run: uv run --frozen pytest tests/planning/test_a_seed_that_seeded_nothing_is_not_a_success.py -v
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
    authz_id = "alice"
    email = "alice@example.com"


class _Req:
    headers = {"Authorization": "Bearer t"}


@pytest.fixture()
def seed(monkeypatch):
    """Call the REAL `/canvas/seed`, faking only the inner seeding route.

    The fake sits at the boundary the defect did NOT live at: the disposition under test is
    `canvas_seed`'s reading of `seeded`/`total`/`results`, and that code runs for real.
    """
    import iagent.gateway as gw

    async def _go(seeded: int, total: int, details: list[str]):
        async def _inner(inner_req, http_request, current_user):
            return {
                "seeded": seeded,
                "total": total,
                "artifact_ids": [f"id-{i}" if i < seeded else None for i in range(total)],
                "results": [
                    {
                        "slot": i,
                        "status": "ok" if i < seeded else "failed",
                        "detail": None if i < seeded else details[i - seeded],
                    }
                    for i in range(total)
                ],
            }

        monkeypatch.setattr(gw, "seed_portfolio_canvas", _inner)
        try:
            return 200, await gw.canvas_seed(gw.CanvasSeedRequest(), _Req(), _User())
        except HTTPException as exc:
            return exc.status_code, exc.detail

    return _go


@pytest.mark.asyncio
async def test_nothing_seeded_because_UNENTITLED_is_403(seed):
    """THE LIVE CASE. Five 403s upstream is the caller's answer, not a server fault, and it
    names the cell rather than leaving a reader to infer it from five identical log lines."""
    status, detail = await seed(0, 5, ["HTTP 403"] * 5)
    assert status == 403, f"a fully-refused seed returned {status}"
    assert "0 of 5" in detail and "entitled" in detail


@pytest.mark.asyncio
async def test_nothing_seeded_for_MIXED_reasons_is_502(seed):
    """Not every total failure is an entitlement answer. A 500 among the refusals means the
    seed could not be performed, which is ours to fix and must not be reported to the caller
    as their permissions."""
    status, detail = await seed(0, 5, ["HTTP 500", "HTTP 403", "HTTP 500", "HTTP 500",
                                       "HTTP 500"])
    assert status == 502, f"a mixed-cause total failure returned {status}"
    assert "403" in detail and "500" in detail, (
        "the refusal does not carry what actually happened upstream"
    )


@pytest.mark.asyncio
async def test_a_PARTIAL_seed_still_refuses_with_200_and_empty(seed):
    """UNCHANGED, AND THE CONTROL ON BOTH TESTS ABOVE. The partial-seed ruling stands:
    cortex has a no-canvas path, and compacting would shift every card after the failed slot
    up one. A fix that turned every incomplete seed into an error would break the live
    client, and it would pass the two tests above."""
    status, body = await seed(3, 5, ["HTTP 500", "HTTP 500"])
    assert status == 200, f"a partial seed now errors: {body}"
    assert body["artifact_ids"] == [] and body["seeded"] == 3 and body["total"] == 5


@pytest.mark.asyncio
async def test_a_COMPLETE_seed_is_untouched(seed):
    """The other control. Every refusal above must leave the working path working."""
    status, body = await seed(5, 5, [])
    assert status == 200
    assert body["artifact_ids"] == [f"id-{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_the_four_outcomes_are_DISTINGUISHABLE(seed):
    """A collapse is a property about a SET. Each case above could pass against a route that
    returned one status if that case happened to expect it — and the defect being fixed is
    precisely two outcomes having become one."""
    seen = {
        (await seed(0, 5, ["HTTP 403"] * 5))[0],
        (await seed(0, 5, ["HTTP 500"] * 5))[0],
        (await seed(3, 5, ["HTTP 500"] * 2))[0],
    }
    assert len(seen) == 3, f"outcomes collapsed to {sorted(seen)}"


@pytest.mark.asyncio
async def test_a_zero_panel_template_is_not_reported_as_unentitled(seed):
    """THE BOUNDARY. `seeded == 0` is only a failure when something was ATTEMPTED. A template
    with no panels seeds nothing correctly, and reporting that as a 403 would accuse the
    caller of lacking a permission nobody asked for."""
    status, body = await seed(0, 0, [])
    assert status == 200, f"an empty template was reported as a failure: {body}"
