"""Observe the gate on the NEW /lineage_by_platform endpoint.

WHY THIS EXISTS, SEPARATELY FROM THE SANDBOX SEAL. The sandbox three-caller
probe sealed the SHARED gate helper (on /query_metadata). That the new
endpoint inherits it "by construction (same helper)" is an ARGUMENT — only
as good as the new call site actually threading the right identity into the
right branch with fail-closed semantics. The DA-read gate was broken-closed
for MONTHS with exactly that shape: the helper was correct, the call site
passed the wrong identity. So the transfer must be OBSERVED, not asserted.

This exercises the real endpoint function with the DataHub walk stubbed, so
it observes the WIRING (does the gate block on this path?) with no cluster.
It does NOT replace the deployed-HTTP re-seal on sandbox after the image
rebuilds — that observes the deployed path — but it converts "transfers by
construction" into "transfers, observed in-process" today.

Pins the IN-CODE branch (ENABLE_AGENTIC_AUTH False), the one sealed on
sandbox. The Topaz branch is a cold path with no armed environment; it is
sealed at the terminal flip, not here.
"""
from __future__ import annotations

import asyncio

import pytest

# Skip cleanly if the service module can't import standalone in this env —
# the point is to run where it can, not to fail the suite where it can't.
main = pytest.importorskip("agent_fleet.datahub_wrapper.main")


def _call(monkeypatch, entitled_domains):
    async def _fake_scroll(client, urn, platforms):
        # Allow path must reach HERE; return an empty walk so no cluster is
        # touched. The gate decision is what's under test, not the answer.
        return [], False

    monkeypatch.setattr(main, "_scroll_lineage_upstream", _fake_scroll)
    monkeypatch.setattr(main, "ENABLE_AGENTIC_AUTH", False)  # the sealed branch
    monkeypatch.setattr(main, "_ENGINE_D_SERVED_DOMAIN", "DATA_ENGINEERING")

    req = main.LineageByPlatformRequest(
        subject_urn="urn:li:dashboard:(authored_bi_tool,1)",
        platforms=["warehouse_a"],
        entitled_domains=entitled_domains,
        caller_email="seal-test@example.invalid",
    )
    return asyncio.run(main.lineage_by_platform(req))


def test_new_endpoint_gate_three_caller_discrimination(monkeypatch):
    entitled = _call(monkeypatch, ["DATA_ENGINEERING"])   # served domain
    empty = _call(monkeypatch, [])                        # no entitlement
    wrong = _call(monkeypatch, ["MAINTENANCE"])           # wrong domain

    # Allowed caller REACHES the walk (gate passed) — distinguishable from a
    # deny by access_denied being False.
    assert entitled["access_denied"] is False

    # Unentitled AND wrong-domain are both blocked. The wrong-domain case is
    # the load-bearing one: it proves the gate checks the SPECIFIC served
    # domain, not the mere presence of an entitlement list. A gate that
    # denied everyone, or allowed anyone with any entitlement, fails here.
    assert empty["access_denied"] is True
    assert wrong["access_denied"] is True

    # Deny is fail-closed and cheap: it returns BEFORE the walk, so nothing
    # was considered.
    assert empty["considered_count"] == 0
    assert wrong["considered_count"] == 0

    # And it names the branch it exercised, so a green here can't be
    # over-read as covering the (unsealed) Topaz path.
    assert empty["gate_basis"] == "in_code_entitled_domains"


def test_new_endpoint_honest_empty_shape_on_deny(monkeypatch):
    denied = _call(monkeypatch, [])
    # Same discriminating shape as the other metadata-plane denials:
    # access_denied True, empty matches, zero considered — never an
    # exception, never a fabricated result.
    assert denied["access_denied"] is True
    assert denied["matches"] == []
    assert denied["match_count"] == 0
