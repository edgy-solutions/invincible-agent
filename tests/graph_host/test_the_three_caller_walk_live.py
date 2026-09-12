"""5.3's live half — three REAL callers against the deployed graph, gated on the Topaz cells.

The fixture harness (`test_the_three_caller_walk.py`) proves the GRAPH branches correctly given
each entitlement outcome. **It cannot prove that Topaz scopes a caller**, because its outcomes
are chosen by a stub. Only a real credential against the real mesh can do that, and the two are
routinely conflated — a green fixture suite reads as "entitlement works" when it only ever
showed "the graph handles a 403".

WHAT NEEDS TO EXIST BEFORE THIS RUNS. Three persona cells, a human write (the classifier refuses
an authz mutation from an agent, correctly):

    LG_CALLER_FULL      entitled to fin_variance_analysis, fin_burn_rate, fin_funding_status
    LG_CALLER_PARTIAL   the same MINUS fin_burn_rate
    LG_CALLER_NONE      entitled to none of them

Each is a bearer token for that persona. They are passed as env vars rather than minted here:
identity is an ARGUMENT, and a test that minted its own callers would be asserting against
credentials it invented.

── THE SKIP IS NOT A PASS, AND THIS FILE SAYS SO WHERE IT SKIPS ────────────────────────────
Without the cells these tests skip, and the reason NAMES THE MISSING CELLS rather than reading
as an environment quirk. Nothing here should be cited as evidence that entitlement scopes the
graph unless it actually ran — which is why the fixture file carries the claim it CAN support
and this one carries the claim it cannot.

── WHAT EVEN THIS CANNOT DISTINGUISH ───────────────────────────────────────────────────────
A 403 because the caller is unentitled and a 403 because engine-fin is misconfigured are the
same status code. The live walk narrows it — the FULL caller succeeding on the same verb the
PARTIAL caller is refused is what separates "this caller is not entitled" from "this verb is
broken" — and that pairing is the only thing here that can. A partial-caller refusal with no
full-caller success beside it is not evidence about entitlement.
"""

from __future__ import annotations

import os

import pytest

_HOST = os.environ.get("GRAPH_HOST_URL")
_FULL = os.environ.get("LG_CALLER_FULL")
_PARTIAL = os.environ.get("LG_CALLER_PARTIAL")
_NONE = os.environ.get("LG_CALLER_NONE")

needs_cells = pytest.mark.skipif(
    not (_HOST and _FULL and _PARTIAL and _NONE),
    reason=(
        "the three Topaz persona cells are not available. Set GRAPH_HOST_URL plus "
        "LG_CALLER_FULL / LG_CALLER_PARTIAL / LG_CALLER_NONE. A SKIP HERE IS NOT A PASS: the "
        "fixture harness proves the graph handles a 403, NOT that Topaz scopes a caller."
    ),
)

_PROGRAM = os.environ.get("LG_TEST_PROGRAM_ID", "PGM-001")


def _brief(token: str) -> dict:
    import httpx

    r = httpx.post(
        f"{_HOST.rstrip('/')}/graphs/fin_program_brief",
        json={"params": {"program_id": _PROGRAM}, "thread_id": "three-caller-walk"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180.0,
    )
    assert r.status_code < 500, f"the host failed rather than the entitlement: {r.status_code} {r.text[:300]}"
    return r.json()


@needs_cells
def test_the_FULL_caller_gets_every_finding():
    """The positive control for both tests below. Without a caller who SUCCEEDS on these verbs,
    a refusal proves nothing about entitlement — it is equally consistent with the verbs being
    broken for everyone."""
    out = _brief(_FULL)
    summary = out.get("summary", "")
    assert "NOT AVAILABLE" not in summary, f"the fully entitled caller got a hole:\n{summary}"
    assert _PROGRAM in summary


@needs_cells
def test_the_PARTIAL_caller_gets_burn_rate_NAMED_ABSENT():
    """The load-bearing row. It must be read TOGETHER with the full-caller test above: the same
    verb succeeding for one caller and refused for another is what attributes the refusal to
    the entitlement rather than to the verb."""
    out = _brief(_PARTIAL)
    summary = out.get("summary", "")
    assert "NOT AVAILABLE" in summary, f"the partially entitled caller got no hole:\n{summary}"
    assert "burn" in summary.lower(), f"the hole does not name the missing finding:\n{summary}"
    assert "variance" in summary.lower() or "funding" in summary.lower(), (
        f"the partial caller got NOTHING — that is the unentitled outcome, so either the cell "
        f"is wrong or the graph refused wholesale:\n{summary}"
    )


@needs_cells
def test_the_UNENTITLED_caller_is_told_it_answered_nothing():
    out = _brief(_NONE)
    summary = out.get("summary", "")
    assert "no finding was retrievable" in summary, (
        f"a brief with nothing in it did not say so — a total narrowing presented as a brief "
        f"is the worst form of the silently-narrowed answer:\n{summary}"
    )
