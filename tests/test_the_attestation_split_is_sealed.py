"""The attestation split, sealed (ruled 2026-11-10): under `self` the dropper promotes; under
`second_party` EXACTLY the ids the served block excludes are refused (no excluded id gets through,
no other id is refused); a malformed block is a 503 with nothing promoted and nothing written.

This does not repeat `test_attestation_is_declared_not_constant.py`, which pins the semantics case
by case. This file pins the SET: the refused population is measured over a population whose
members differ from each other only in whether the block names them.

Mode names come from `promotion.ATTESTATION_*`; excluded ids come from `attestation_block` run on
the payload (the loader's own answer), never from a list typed here. Ids are synthetic.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/test_the_attestation_split_is_sealed.py
"""
from __future__ import annotations

import pytest

from src.iagent import promotion
from tests.test_promotion_records_origin import PAYLOAD, Graph, Ledger, _act, _stores

CK = PAYLOAD["content_kind"]
REFUSAL_FOR_AN_EXCLUDED_ID = "dropper_cannot_attest_origin"
UNDECLARABLE = "attestation_undeclarable"


def _dropped() -> dict:
    return {"authz_id": "drop-0", "on_behalf_of": "behalf-0"}


def _task(mode, monkeypatch, dropped=None, extra_excluded=()):
    """A task whose attestation block is the one filing would stamp under `mode` (served by the
    loader), optionally widened by ids the block excludes though they dropped nothing."""
    monkeypatch.setattr(promotion, "_declared_attestation", lambda ck: mode)
    p = {**PAYLOAD, "dropped_by": dropped or _dropped()}
    block = promotion.attestation_block(CK, p)
    block["excluded"] = sorted({*block["excluded"], *extra_excluded})
    p["attestation"] = block
    return p


def _outcome(payload, actor):
    """'promoted', or the refusal's (error, status); plus whatever was written."""
    ledger, graph = Ledger(), Graph()
    try:
        _act(_stores(ledger, graph), acted_by=actor, payload=payload)
    except promotion.PromotionRefused as exc:
        return (exc.error, exc.status), ledger, graph
    return "promoted", ledger, graph


def _nothing_written(ledger, graph):
    return ledger.appends == [] and graph.writes == 0 and graph.attests == []


# --- self: the dropper promotes ---------------------------------------------------------------

def test_under_self_everyone_including_the_dropper_promotes(monkeypatch):
    p = _task(promotion.ATTESTATION_SELF, monkeypatch)
    droppers = set(p["dropped_by"].values())
    for actor in [*sorted(droppers), "someone-else", "another-one"]:
        out, _ledger, graph = _outcome(p, actor)
        assert out == "promoted", (actor, out)
        assert graph.attest_kw["attested_by"] == actor
        assert graph.attest_kw["self_attested"] is (actor in droppers)


# --- second_party: exactly the excluded ids are refused ---------------------------------------

@pytest.mark.parametrize("dropped,extra", [
    (None, ()),                                   # dropper and on-behalf-of
    ({"authz_id": "drop-0"}, ()),                 # a lone dropper
    (None, ("steward-x", "steward-y")),           # the block excludes more than dropped it
    ({"authz_id": "drop-0"}, ("steward-x",)),
])
def test_under_second_party_exactly_the_excluded_ids_are_refused(monkeypatch, dropped, extra):
    p = _task(promotion.ATTESTATION_SECOND_PARTY, monkeypatch, dropped, extra)
    excluded = set(p["attestation"]["excluded"])
    assert excluded, "the fixture must exclude someone or the arm proves nothing"
    # The control population: ids that differ from an excluded id only in not being listed.
    others = {f"{e}-not-listed" for e in excluded} | {"bystander"}
    assert not (others & excluded)

    refused, promoted = set(), set()
    for actor in sorted(excluded | others):
        out, ledger, graph = _outcome(p, actor)
        if out == "promoted":
            promoted.add(actor)
        else:
            assert out == (REFUSAL_FOR_AN_EXCLUDED_ID, 403), (actor, out)
            assert _nothing_written(ledger, graph), actor
            refused.add(actor)
    assert refused == excluded, f"refused {sorted(refused)}, block excludes {sorted(excluded)}"
    assert promoted == others


def test_exactly_one_mode_refuses_an_excluded_id_and_it_is_second_party(monkeypatch):
    refusing = []
    for mode in promotion.ATTESTATION_MODES:
        p = _task(mode, monkeypatch)
        p["attestation"]["excluded"] = ["listed-id"]
        if _outcome(p, "listed-id")[0] != "promoted":
            refusing.append(mode)
    assert refusing == [promotion.ATTESTATION_SECOND_PARTY]


def test_a_refusal_is_the_actors_alone(monkeypatch):
    """After the dropper is refused, a different steward still promotes the same task."""
    p = _task(promotion.ATTESTATION_SECOND_PARTY, monkeypatch)
    assert _outcome(p, "drop-0")[0] == (REFUSAL_FOR_AN_EXCLUDED_ID, 403)
    assert _outcome(p, "steward-z")[0] == "promoted"


# --- a malformed block is a 503 ---------------------------------------------------------------

def _malformed_blocks():
    mode, second = promotion.ATTESTATION_SELF, promotion.ATTESTATION_SECOND_PARTY
    return {
        "empty_dict": {},
        "no_mode": {"excluded": []},
        "mode_none": {"mode": None, "excluded": []},
        "mode_unknown": {"mode": mode + "-and-more", "excluded": []},
        "mode_wrong_case": {"mode": second.upper(), "excluded": []},
        "mode_a_list": {"mode": [mode], "excluded": []},
        "mode_a_number": {"mode": 5, "excluded": []},
        "no_excluded": {"mode": second},
        "excluded_none": {"mode": second, "excluded": None},
        "excluded_a_string": {"mode": second, "excluded": "someone"},
        "excluded_a_dict": {"mode": second, "excluded": {"someone": 1}},
        "excluded_non_string_member": {"mode": second, "excluded": ["someone", 5]},
        "excluded_none_member": {"mode": mode, "excluded": [None]},
        "block_a_string": "second-party",
        "block_a_list": [{"mode": mode, "excluded": []}],
        "block_a_number": 5,
        "block_false": False,
    }


@pytest.mark.parametrize("shape", sorted(_malformed_blocks()))
@pytest.mark.parametrize("actor", ["drop-0", "steward-z"])
def test_a_malformed_block_is_503_for_everyone_and_writes_nothing(shape, actor):
    p = {**PAYLOAD, "dropped_by": _dropped(), "attestation": _malformed_blocks()[shape]}
    out, ledger, graph = _outcome(p, actor)
    assert out == (UNDECLARABLE, 503), (shape, actor, out)
    assert _nothing_written(ledger, graph)


def test_a_malformed_block_does_not_stop_a_rejection():
    """The 503 guards a PROMOTION; rejecting writes no origin and attests nothing."""
    p = {**PAYLOAD, "dropped_by": _dropped(), "attestation": {"mode": None}}
    ledger, graph = Ledger(), Graph()
    out = _act(_stores(ledger, graph), decision="rejected", acted_by="drop-0", payload=p)
    assert out["decision"] == "rejected" and graph.attests == []


@pytest.mark.parametrize("declared", ["", "SELF", " self", "two_party", 123, ["self"], {}, False])
def test_a_malformed_declaration_is_503_at_filing_and_at_the_read(monkeypatch, declared):
    monkeypatch.setattr(promotion, "_declared_attestation", lambda ck: declared)
    for call in (lambda: promotion.attestation_for(CK),
                 lambda: promotion.attestation_block(CK, {"dropped_by": _dropped()})):
        with pytest.raises(promotion.PromotionRefused) as ei:
            call()
        assert (ei.value.error, ei.value.status) == (UNDECLARABLE, 503), declared


def test_a_legacy_task_with_a_malformed_declaration_is_503_not_a_default(monkeypatch):
    """No stored block: the act decides on the block filing would stamp today. A malformed row
    there fails closed; it is never guessed to be the default mode."""
    monkeypatch.setattr(promotion, "_declared_attestation", lambda ck: "two_party")
    p = {**PAYLOAD, "dropped_by": _dropped()}
    out, ledger, graph = _outcome(p, "steward-z")
    assert out == (UNDECLARABLE, 503) and _nothing_written(ledger, graph)
