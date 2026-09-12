"""The host ENFORCES the row — `refusal`, and admission before the first node.

Ruled 2026-09-12, on a clause this lane filed rather than fixed: **`refusal` was honoured by
each graph MODULE and enforced by NOTHING.** A row could declare `fail`, its module could return
partial results, and nothing anywhere went red. The declaration described behaviour it did not
constrain — the Engine B shape moved from a class name to a contract clause.

The host is the party that holds BOTH the row and the output, so the host is where it is checked.

── THE CONTROL IS WHAT MAKES THIS A SEAL ───────────────────────────────────────────────────
    mutation:  a module returns holes under `refusal: fail`        -> REJECTED
    control:   the same holes under `refusal: named-hole`          -> PASSES

Without the second, "the host enforces `fail`" is indistinguishable from "the host rejects
partial output from everyone" — and the second would break `fin_program_brief`, whose declared
disposition IS to answer with named holes, while looking like success.

**The two graphs differing on the clause is what makes both directions testable today.** They
were chosen to differ before this increment existed; a third graph would otherwise have had to
be invented to prove the enforcement is conditional.

── TWO LAYERS ON IDENTITY, AND THE INNER ONE MATTERS IF THE OUTER REGRESSES ────────────────
An UNENTITLED caller is identified and gets an answer shaped by what they may see. An
UNIDENTIFIED call is a different thing and gets nothing, named — refused at the host before the
first node. Each graph's nodes ALSO refuse to call out without an initiator, so a wrapper
failure cannot launder access; that inner property is what the fixture harness's fourth outcome
proves. This file asserts the outer check, and asserts that REMOVING it makes the inner
behaviour observable — which is how we know both layers exist rather than one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "policy" / "graphs"
_IDENT = {"Authorization": "Bearer caller-token", "X-Originator-Email": "alice@example.com"}


@pytest.fixture()
def client(monkeypatch):
    """The real app, with both graphs admitted and no registration attempted."""
    sys.path.insert(0, str(_ROOT))
    monkeypatch.setenv("GRAPH_POLICY_DIR", str(_POLICY))
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)

    import importlib

    from fastapi.testclient import TestClient

    from agent_fleet.graph_host import main as host

    importlib.reload(host)
    host._LOADED = host.load_graphs()
    return TestClient(host.app), host


def _stub_graph(returns: dict):
    """A graph whose output the test chooses, so the HOST's behaviour is what is measured.

    The point is enforcement, not the modules: using a real graph would make this depend on
    engine-fin and on the module honouring its own row, which is the thing under test.
    """
    class _G:
        async def ainvoke(self, state, config=None):
            return returns

    return _G()


def test_both_dispositions_are_present_to_be_distinguished(client):
    """POSITIVE CONTROL, first. With both rows declaring the same disposition, every assertion
    below is satisfied by a host that treats them identically — which is the defect."""
    _c, host = client
    refusals = {gid: m.refusal for gid, (m, _g) in host._LOADED.items()}
    assert set(refusals.values()) >= {"fail", "named-hole"}, (
        f"the admitted rows do not cover both dispositions: {refusals}. The enforcement cannot "
        f"be shown CONDITIONAL, only present."
    )


def test_a_FAIL_row_returning_holes_is_REJECTED(client):
    c, host = client
    m, _real = host._LOADED["cost_lot_costing_review"]
    assert m.refusal == "fail", "this test's subject changed its disposition"
    host._LOADED["cost_lot_costing_review"] = (m, _stub_graph(
        {"summary": "two of three views", "holes": [{"source": "cost_rate_comparison",
                                                     "reason": "not entitled"}]}
    ))

    r = c.post("/graphs/cost_lot_costing_review",
               json={"params": {"lot": 1, "rate_vintage": "2026-Q1"}}, headers=_IDENT)

    assert r.status_code == 502, f"a fail-row's partial output was passed through: {r.status_code} {r.text[:200]}"
    detail = r.json()["detail"]
    assert "refusal=fail" in detail and "cost_rate_comparison" in detail, (
        f"the rejection does not name the row's clause and which hole caused it: {detail}"
    )
    assert "contract disagreement" in detail, (
        "the rejection reads as a runtime error. It is a disagreement between a row and its "
        "module, and the reader needs to know which of the two to change."
    )


def test_a_NAMED_HOLE_row_returning_the_SAME_holes_PASSES(client):
    """THE CONTROL. Without it, the test above is satisfied by a host that rejects partial
    output from every graph — which would break fin_program_brief, whose declared disposition
    IS to answer with named holes, while looking like the enforcement working."""
    c, host = client
    m, _real = host._LOADED["fin_program_brief"]
    assert m.refusal == "named-hole", "this control's subject changed its disposition"
    host._LOADED["fin_program_brief"] = (m, _stub_graph(
        {"summary": "two of three findings\n  - cash burn: NOT AVAILABLE — not entitled",
         "holes": [{"source": "fin_burn_rate", "reason": "not entitled"}]}
    ))

    r = c.post("/graphs/fin_program_brief",
               json={"params": {"program_id": "PGM-001"}}, headers=_IDENT)

    assert r.status_code == 200, (
        f"a named-hole row's declared output was rejected: {r.status_code} {r.text[:200]}. The "
        f"host is rejecting partials from everyone rather than enforcing the row."
    )
    assert r.json()["holes"], "the hole was stripped from an output whose row declares it"


def test_an_UNIDENTIFIED_call_is_refused_BEFORE_the_first_node(client):
    c, host = client

    called: list[int] = []

    class _G:
        async def ainvoke(self, state, config=None):
            called.append(1)
            return {"summary": "should never run"}

    m, _real = host._LOADED["fin_program_brief"]
    host._LOADED["fin_program_brief"] = (m, _G())

    r = c.post("/graphs/fin_program_brief", json={"params": {"program_id": "PGM-001"}})

    assert r.status_code == 401, f"an unidentified call reached the graph: {r.status_code}"
    assert called == [], (
        "the graph RAN for a call carrying no identity. Its nodes would refuse to call out, so "
        "nothing leaks — but the refusal belongs before the first node, because an unidentified "
        "caller has no subject to scope a governed read to at all."
    )
    assert "INITIATOR" in r.json()["detail"]


def test_an_IDENTIFIED_caller_still_gets_through(client):
    """The admission check's own positive control — otherwise "unidentified is refused" is
    indistinguishable from "everything is refused", which passes the test above."""
    c, host = client
    m, _real = host._LOADED["fin_program_brief"]
    host._LOADED["fin_program_brief"] = (m, _stub_graph({"summary": "ran"}))

    r = c.post("/graphs/fin_program_brief",
               json={"params": {"program_id": "PGM-001"}}, headers=_IDENT)
    assert r.status_code == 200, f"an identified caller was refused: {r.status_code} {r.text[:200]}"
