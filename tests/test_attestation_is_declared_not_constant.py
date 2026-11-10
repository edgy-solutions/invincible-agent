"""Attestation is a declared property of a promotion, not a constant (ruled 2026-11-09).

`attestation: self | second_party`, default `self`. Under `second_party` the dropper (and whom it
was dropped for) cannot promote: 403 `dropper_cannot_attest_origin`. The task carries the rule it
was filed under; a task filed before the stamp reads the row. The record and the origin write
name who attested.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/test_attestation_is_declared_not_constant.py
"""
from __future__ import annotations

import pytest

from src.iagent import promotion
from tests.test_promotion_records_origin import PAYLOAD, Graph, Ledger, _act, _stores

CK = PAYLOAD["content_kind"]
DROPPED = {"authz_id": "alice", "on_behalf_of": "carol"}


def _payload(mode=None, **extra):
    p = {**PAYLOAD, "dropped_by": dict(DROPPED), **extra}
    if mode is not None:
        p["attestation"] = {"mode": mode, "excluded": []}
    return p


def _seam(monkeypatch, value):
    monkeypatch.setattr(promotion, "_declared_attestation", lambda ck: value)


def _inputs(ledger):
    return ledger.appends[0]["checks"][0]["inputs"]


@pytest.mark.parametrize("actor", ["alice", "carol"])
def test_1_2_under_self_the_dropper_and_on_behalf_of_may_promote(actor):
    ledger, graph = Ledger(), Graph()
    out = _act(_stores(ledger, graph), acted_by=actor, payload=_payload("self"))
    assert out["origin"] == "written"
    assert _inputs(ledger)["attestation"] == {
        "mode": "self", "attested_by": actor, "self_attested": True}
    assert graph.attest_kw == {"attested_by": actor, "self_attested": True}


@pytest.mark.parametrize("actor", ["alice", "carol"])
def test_3_under_second_party_the_dropper_and_on_behalf_of_are_refused(actor):
    ledger, graph = Ledger(), Graph()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(ledger, graph), acted_by=actor, payload=_payload("second_party"))
    assert ei.value.error == "dropper_cannot_attest_origin" and ei.value.status == 403
    assert ledger.appends == [] and graph.writes == 0 and graph.attests == []


def test_4_CONTROL_under_second_party_a_different_steward_promotes():
    ledger, graph = Ledger(), Graph()
    _act(_stores(ledger, graph), acted_by="bob", payload=_payload("second_party"))
    assert _inputs(ledger)["attestation"] == {
        "mode": "second_party", "attested_by": "bob", "self_attested": False}
    assert graph.attest_kw == {"attested_by": "bob", "self_attested": False}


def test_5_the_dropper_REJECTING_under_second_party_is_not_refused():
    out = _act(_stores(), decision="rejected", acted_by="alice", payload=_payload("second_party"))
    assert out["decision"] == "rejected"


def test_a_rejected_record_carries_no_attestation_key():
    ledger = Ledger()
    _act(_stores(ledger), decision="rejected", acted_by="alice", payload=_payload("second_party"))
    assert "attestation" not in _inputs(ledger)


@pytest.mark.parametrize("declared,refused", [("second_party", True), (None, False)])
def test_6_a_legacy_task_reads_the_row(monkeypatch, declared, refused):
    _seam(monkeypatch, declared)
    payload = _payload()
    assert "attestation" not in payload
    if refused:
        with pytest.raises(promotion.PromotionRefused) as ei:
            _act(_stores(), acted_by="alice", payload=payload)
        assert ei.value.error == "dropper_cannot_attest_origin" and ei.value.status == 403
    else:
        assert _act(_stores(), acted_by="alice", payload=payload)["origin"] == "written"


def test_7_the_stamp_wins_over_a_later_row_change(monkeypatch):
    """A task carries the rule it was filed under (stated semantics); flipping it is a ruling."""
    _seam(monkeypatch, "second_party")
    assert _act(_stores(), acted_by="alice", payload=_payload("self"))["origin"] == "written"


def test_8_malformed_declarations_fail_closed_with_no_write(monkeypatch):
    ledger, graph = Ledger(), Graph()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(ledger, graph), acted_by="bob", payload=_payload("two_party"))
    assert ei.value.error == "attestation_undeclarable" and ei.value.status == 503
    assert ledger.appends == [] and graph.writes == 0 and graph.attests == []

    for bad in ("junk", ["self"], 5):
        p = _payload()
        p["attestation"] = bad
        with pytest.raises(promotion.PromotionRefused) as ei:
            _act(_stores(ledger, graph), acted_by="bob", payload=p)
        assert ei.value.error == "attestation_undeclarable" and ei.value.status == 503

    _seam(monkeypatch, "two_party")
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(_stores(ledger, graph), acted_by="bob", payload=_payload())
    assert ei.value.error == "attestation_undeclarable" and ei.value.status == 503
    assert ledger.appends == [] and graph.writes == 0 and graph.attests == []

    _seam(monkeypatch, 123)
    with pytest.raises(promotion.PromotionRefused) as ei:
        promotion.attestation_for(CK)
    assert ei.value.error == "attestation_undeclarable" and ei.value.status == 503


def test_9_the_served_block(monkeypatch):
    payload = _payload()
    assert promotion.attestation_block(CK, payload) == {"mode": "self", "excluded": []}
    _seam(monkeypatch, "second_party")
    assert promotion.attestation_block(CK, payload) == {
        "mode": "second_party", "excluded": ["alice", "carol"]}
    blanks = {**payload, "dropped_by": {"authz_id": "alice", "on_behalf_of": ""}}
    assert promotion.attestation_block(CK, blanks)["excluded"] == ["alice"]
