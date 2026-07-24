"""PCN/PDN review STARTER sealed — the entry composition + workflow-start wiring.

Two things sealed offline (the entry handler's whole offline-sealable surface):
1. ``build_review_from_request`` over the SAME real-shaped IPCN25300X fixture the seam-diff seal uses
   produces the SAME batch shape — the entry point composes to exactly what the seam-diff seal
   validated (real ruleset at its live ruleset_ref, 3 residue, dispatchQualification, 2-resolve-1-
   abstain). If these two ever diverge, the entry path and the prediction have drifted.
2. ``start_review`` issues a workflow_send with the composed batch (STARTED) — and returns NO_RESIDUE
   honestly when nothing reaches residue (no empty task, no workflow).

The three live seams (rules-fetch, resolveInstance, Topaz can_act) are injected — the composition
boundary, not a mock in the data path: real-shaped parts flow through the real proposer/funnel/review.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio --with rdflib \
        pytest ../../tests/test_pcn_review_starter.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst import pcn_review_starter as starter  # noqa: E402
from agent_fleet.restate_analyst.pcn_rules_loader import load_disposition_rules  # noqa: E402

_TTL = _REPO / "setup" / "ontologies" / "pcn_disposition_rules.ttl"
_START = starter.start_review.__wrapped__


def _load_real_rules():
    import rdflib
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return load_disposition_rules(g)


# Same real-shaped IPCN25300X fixture as the seam-diff seal (test_pcn_review_builder).
_KNOWN_IRIS = {
    "NSR01L30NXT5G": "http://internal/components/NSR01L30NXT5G",
    "MPN-NEEDSREVIEW": "http://internal/components/MPN-NEEDSREVIEW",
}


def _request(impacted=None, in_scope=None):
    return {
        "notice_id": "IPCN25300X",
        "doc_type": "PCN",
        "categories": ["Process"],
        "impacted_parts": impacted if impacted is not None else [
            {"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": "NSR01L30NXT5G-R", "needs_review": False},
            {"affected_mpn": "MPN-NEEDSREVIEW", "replacement_mpn": "", "needs_review": True},
            {"affected_mpn": "MPN-OUTOFSCOPE", "replacement_mpn": "", "needs_review": False},
            {"affected_mpn": "MPN-UNRES", "replacement_mpn": "", "needs_review": False},
        ],
        "in_scope_mpns": in_scope if in_scope is not None else ["NSR01L30NXT5G", "MPN-NEEDSREVIEW", "MPN-UNRES"],
        "approver": "qa",
        "audience": "qualification",
        "user_jwt": "jwt-abc",
    }


def _fake_seams(can_act=lambda a, it: True):
    return {
        "load_rules": _load_real_rules,
        "resolve_subject": lambda mpn: _KNOWN_IRIS.get(mpn),
        "can_act": can_act,
    }


# ===========================================================================
# The entry composition == the seam-diff seal's validated batch
# ===========================================================================
def test_entry_composition_matches_seam_diff_prediction():
    out = starter.build_review_from_request(_request(), **_fake_seams())
    assert out["counts"] == {"input": 4, "residue": 3, "filtered": 1, "auto_disposed": 0, "review_forced": 1}
    assert out["ruleset_ref"].startswith("rules@")
    assert out["resolved"] == 2 and out["unresolved"] == 1
    mpns = {it["mpn"] for it in out["batch_items"]}
    assert mpns == {"NSR01L30NXT5G", "MPN-NEEDSREVIEW", "MPN-UNRES"}
    for it in out["batch_items"]:
        assert it["proposed_disposition"] == "dispatchQualification"
        assert it["proposed_by_ruleset"] == out["ruleset_ref"]


# ===========================================================================
# start_review — STARTED issues one workflow_send with the composed batch
# ===========================================================================
class _FakeContext:
    def __init__(self):
        self.sends: list = []

    async def run(self, name, fn):
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def workflow_send(self, tpe, key, arg, **kw):
        self.sends.append({"key": key, "arg": arg})


@pytest.mark.asyncio
async def test_start_review_starts_workflow_with_composed_batch(monkeypatch):
    monkeypatch.setattr(starter, "load_rules_via_engine_o", _load_real_rules)
    monkeypatch.setattr(starter, "resolve_subject_via_engine_o", lambda mpn: _KNOWN_IRIS.get(mpn))
    monkeypatch.setattr(starter, "can_act_via_topaz", lambda a, it: True)

    ctx = _FakeContext()
    out = await _START(ctx, _request())
    assert out["status"] == "STARTED"
    assert out["count"] == 3
    assert len(ctx.sends) == 1, "expected exactly one workflow_send"
    send = ctx.sends[0]
    assert send["key"] == "pcn-review-IPCN25300X-qa"
    assert {it["mpn"] for it in send["arg"]["batch_items"]} == {"NSR01L30NXT5G", "MPN-NEEDSREVIEW", "MPN-UNRES"}
    assert send["arg"]["notice_fingerprint"] == "IPCN25300X"
    assert send["arg"]["audience"] == "qualification"


@pytest.mark.asyncio
async def test_start_review_no_residue_starts_no_workflow(monkeypatch):
    """Every part out-of-scope -> all filtered -> nothing reaches residue -> NO_RESIDUE, no workflow,
    no empty task. The honest-empty path, not a silent success."""
    monkeypatch.setattr(starter, "load_rules_via_engine_o", _load_real_rules)
    monkeypatch.setattr(starter, "resolve_subject_via_engine_o", lambda mpn: None)
    monkeypatch.setattr(starter, "can_act_via_topaz", lambda a, it: True)

    all_out_of_scope = [
        {"affected_mpn": "OTHER-1", "replacement_mpn": "", "needs_review": False},
        {"affected_mpn": "OTHER-2", "replacement_mpn": "", "needs_review": False},
    ]
    ctx = _FakeContext()
    out = await _START(ctx, _request(impacted=all_out_of_scope, in_scope=[]))
    assert out["status"] == "NO_RESIDUE"
    assert out["counts"]["residue"] == 0
    assert ctx.sends == [], "started a workflow with an empty batch"
