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


def _ok_rules():
    """The client's 'ok' envelope over the real ruleset — what load_policy_rules returns live."""
    ruleset, category_classes, ruleset_ref = _load_real_rules()
    return {"status": "ok", "ruleset": ruleset, "category_classes": category_classes,
            "ruleset_ref": ruleset_ref, "valid": True, "validation_errors": [], "registration_checked": True}


def _wire(monkeypatch, rules=None, resolve=None, can_act=lambda a, it: True):
    monkeypatch.setattr(starter, "load_policy_rules", lambda: rules if rules is not None else _ok_rules())
    monkeypatch.setattr(starter, "resolve_subject_via_engine_o", resolve or (lambda mpn: _KNOWN_IRIS.get(mpn)))
    monkeypatch.setattr(starter, "can_act_via_topaz", can_act)


# ===========================================================================
# The entry composition == the seam-diff seal's validated batch
# ===========================================================================
def test_entry_composition_matches_seam_diff_prediction():
    ruleset, category_classes, ruleset_ref = _load_real_rules()
    out = starter.build_review_from_request(
        _request(), ruleset=ruleset, category_classes=category_classes, ruleset_ref=ruleset_ref,
        resolve_subject=lambda mpn: _KNOWN_IRIS.get(mpn), can_act=lambda a, it: True,
    )
    assert out["counts"] == {"input": 4, "residue": 3, "filtered": 1, "auto_disposed": 0, "review_forced": 1}
    assert out["ruleset_ref"] == "rules@2915ddb229e4"
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
    _wire(monkeypatch)
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
    _wire(monkeypatch, resolve=lambda mpn: None)
    all_out_of_scope = [
        {"affected_mpn": "OTHER-1", "replacement_mpn": "", "needs_review": False},
        {"affected_mpn": "OTHER-2", "replacement_mpn": "", "needs_review": False},
    ]
    ctx = _FakeContext()
    out = await _START(ctx, _request(impacted=all_out_of_scope, in_scope=[]))
    assert out["status"] == "NO_RESIDUE"
    assert out["counts"]["residue"] == 0
    assert ctx.sends == [], "started a workflow with an empty batch"


@pytest.mark.asyncio
async def test_no_entitled_action_when_residue_but_approver_denied_all(monkeypatch):
    """Residue EXISTS but Topaz denies this approver every item -> NO_ENTITLED_ACTION, LOUD, no
    workflow. Distinct from NO_RESIDUE (genuinely nothing to review) — the deny-for-everyone misconfig
    must not hide behind 'nothing to review'. The join-that-can-never-complete, surfaced not parked."""
    _wire(monkeypatch, can_act=lambda a, it: False)  # deny everyone
    ctx = _FakeContext()
    out = await _START(ctx, _request())
    assert out["status"] == "NO_ENTITLED_ACTION"
    assert out["counts"]["residue"] == 3, "residue exists (3) — this is not an empty review"
    assert ctx.sends == [], "started a review no approver can action"


@pytest.mark.asyncio
async def test_review_state_unsourced_bites_the_graph_laundering(monkeypatch):
    """THE TRIPWIRE: a request with doc-level needs_review TRUE but no part carrying the per-part flag
    was built from the lossy graph projection (both graphs drop per-part needs_review) -> REVIEW_STATE_
    UNSOURCED, no workflow. If a future wiring/BFF builds the request from the graph 'because it's right
    there', THIS goes red instead of an unverified MPN riding accept-all through five sealed layers."""
    _wire(monkeypatch)
    # Graph-derived shape: parts carry mpn/replacement but NO per-part needs_review (both graphs drop it).
    graph_shaped = [
        {"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": "", "needs_review": False},
        {"affected_mpn": "MPN-NEEDSREVIEW", "replacement_mpn": "", "needs_review": False},
    ]
    req = _request(impacted=graph_shaped, in_scope=["NSR01L30NXT5G", "MPN-NEEDSREVIEW"])
    req["doc_needs_review"] = True  # ...but the extraction's doc-level flag says something needs review
    ctx = _FakeContext()
    out = await _START(ctx, req)
    assert out["status"] == "REVIEW_STATE_UNSOURCED"
    assert ctx.sends == [], "started a review that laundered an unsourced needs_review flag"


@pytest.mark.asyncio
async def test_review_state_sourced_proceeds(monkeypatch):
    """doc-level TRUE and a part actually carries needs_review=True -> sourced from the extraction ->
    proceeds (the flagged part is forced to residue downstream by §3). And doc-level FALSE/absent (the
    IPCN25300X case) proceeds normally."""
    _wire(monkeypatch)
    req = _request()
    req["doc_needs_review"] = True
    req["impacted_parts"][1]["needs_review"] = True  # MPN-NEEDSREVIEW carries the flag (sourced)
    ctx = _FakeContext()
    out = await _START(ctx, req)
    assert out["status"] == "STARTED", "a properly-sourced review-state request must proceed"


@pytest.mark.asyncio
async def test_start_review_invalid_ruleset_halts_honestly(monkeypatch):
    """An invalid ruleset (client status 'invalid') -> RULESET_INVALID with reasons, NO batch, NO
    workflow. report-don't-reject reaches its terminus at the caller's policy: don't dispatch under a
    corrupt ruleset."""
    _wire(monkeypatch, rules={"status": "invalid", "ruleset": [{"id": "x"}], "category_classes": {},
                              "ruleset_ref": "rules@bad", "valid": False,
                              "validation_errors": ["rule x: subsumes y with a different disposition"],
                              "registration_checked": True})
    ctx = _FakeContext()
    out = await _START(ctx, _request())
    assert out["status"] == "RULESET_INVALID"
    assert out["validation_errors"]
    assert ctx.sends == [], "dispatched under an invalid ruleset"


@pytest.mark.asyncio
async def test_start_review_rules_not_found_halts_honestly(monkeypatch):
    """No rules in the graph (client status 'not_found') -> RULES_NOT_FOUND, no batch, no workflow."""
    _wire(monkeypatch, rules={"status": "not_found", "ruleset": [], "category_classes": {},
                              "ruleset_ref": "", "valid": True, "validation_errors": [],
                              "registration_checked": False})
    ctx = _FakeContext()
    out = await _START(ctx, _request())
    assert out["status"] == "RULES_NOT_FOUND"
    assert ctx.sends == []
