"""The review serves an abstention's reason and its candidate dispositions (lane 74, item 2).

The order (architect via Chris, 11-19): "Serve an abstention's reason and candidate dispositions on
the review." The reviewer of a conflict should see "rules disagree: <a> or <b>", not a blank.

The cause: `policy_evaluator.evaluate_rules` knew WHY a part had no proposal (`unclassifiable`: no rule
matched; `conflict`: matching rules disagree) and WHICH dispositions disagreed, but `build_part_items`
kept only `disposition` and `ruleset_ref`, so the card read only "needs a disposition". The outcome and
the candidates now ride PartItem -> workflow state -> GET /reviews/{id}/batch.

Run:  LOCKED_SDK=no_overlay_venv_is_0920 .venv/Scripts/python.exe <locked_pytest.py> <log> \
        tests/test_the_review_serves_why_a_row_has_no_proposal.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.restate_analyst import policy_evaluator as pe  # noqa: E402
from agent_fleet.restate_analyst.grouped_review_workflow import (  # noqa: E402
    _partitem_from_dict, _partitem_to_dict, batch_items_to_state,
)
from agent_fleet.restate_analyst.review_composer import build_review_batch  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import PartItem  # noqa: E402
from src.iagent import gateway  # noqa: E402
from tests.test_review_composer import _load_real_ruleset  # noqa: E402
from tests.test_cases_route import _user  # noqa: E402

RULESET, CATEGORY_CLASSES, REF = _load_real_ruleset()


def _classes(categories):
    return {CATEGORY_CLASSES[c] for c in categories if c in CATEGORY_CLASSES}


def _held(doc_type, has_replacement, categories):
    """The dispositions of the rules `_rule_matches` says hold, computed independently of evaluate_rules."""
    cc = _classes(categories)
    return sorted({r.get("proposesDisposition") for r in RULESET
                   if pe._rule_matches(r, doc_type=doc_type, has_replacement=has_replacement, change_classes=cc)})


def _eval(doc_type, has_replacement, categories):
    return pe.evaluate_rules(doc_type=doc_type, has_replacement=has_replacement, categories=categories,
                             ruleset=RULESET, category_classes=CATEGORY_CLASSES, ruleset_ref=REF)


def _find(predicate):
    """Search the loaded seed ruleset's category space for a (doc_type, has_replacement, categories) whose
    held dispositions satisfy `predicate`. Derived, not hard-coded."""
    names = sorted(CATEGORY_CLASSES)
    combos = [[]] + [[a] for a in names] + [[a, b] for i, a in enumerate(names) for b in names[i + 1:]]
    for doc_type in ("PCN", "PDN"):
        for rep in (False, True):
            for cats in combos:
                held = _held(doc_type, rep, cats)
                if predicate(held):
                    return doc_type, rep, cats
    return None


def _conflict_case():
    found = _find(lambda held: len(held) > 1)
    assert found, "the seed ruleset has no conflicting category set; the conflict arm has no subject"
    return found


def test_conflict_abstains_and_names_the_disagreeing_dispositions():
    doc_type, rep, cats = _conflict_case()
    p = _eval(doc_type, rep, cats)
    held = _held(doc_type, rep, cats)
    assert p.disposition is None and p.outcome == pe.CONFLICT
    assert list(p.candidates) == held and len(p.candidates) >= 2


def test_unclassifiable_has_no_candidates():
    found = _find(lambda held: not held)
    if found is None:  # the seed ruleset matches everything: an unknown doc type matches no rule
        doc_type, rep, cats = "ZZZ", False, []
        assert _held(doc_type, rep, cats) == []
    else:
        doc_type, rep, cats = found
    p = _eval(doc_type, rep, cats)
    assert p.outcome == pe.UNCLASSIFIABLE and p.disposition is None and p.candidates == ()


def test_matched_carries_its_one_disposition():
    found = _find(lambda held: len(held) == 1)
    assert found, "the seed ruleset has no single-disposition case"
    doc_type, rep, cats = found
    p = _eval(doc_type, rep, cats)
    assert p.outcome == pe.MATCHED and p.candidates == (p.disposition,) == tuple(_held(doc_type, rep, cats))


def test_matched_for_a_pdn_part():
    p = _eval("PDN", False, [])
    held = _held("PDN", False, [])
    if len(held) == 1:
        assert p.outcome == pe.MATCHED and p.candidates == (held[0],) and p.disposition == held[0]
    else:  # the seed ruleset gives a PDN no single answer: the arm is then carried by the derived search
        pytest.skip("PDN with no categories is not a single-disposition case in the seed ruleset")


def _parts(*mpns):
    return [{"affected_mpn": m, "replacement_mpn": "", "needs_review": False} for m in mpns]


def _items(doc_type, cats):
    return pe.build_part_items(_parts("MPN-1"), doc_type=doc_type, categories=cats, in_scope_mpns={"MPN-1"},
                               ruleset=RULESET, category_classes=CATEGORY_CLASSES, ruleset_ref=REF)


def test_build_part_items_carries_both_fields_onto_partitem():
    doc_type, rep, cats = _conflict_case()
    (it,) = _items(doc_type, cats) if not rep else (None,)
    if it is None:
        pytest.skip("the derived conflict needs a replacement; build_part_items parts here carry none")
    assert it.proposal_outcome == pe.CONFLICT
    assert list(it.candidate_dispositions) == _held(doc_type, False, cats)


def test_state_round_trip_and_the_served_reason():
    doc_type, rep, cats = _conflict_case()
    for item_args in ((doc_type, cats), ("ZZZ", [])):
        (it,) = _items(*item_args)
        d = _partitem_to_dict(it)
        back = _partitem_from_dict(d)
        assert back.proposal_outcome == it.proposal_outcome
        assert back.candidate_dispositions == it.candidate_dispositions
        assert d["abstention_reason"] == pe.ABSTENTION_REASON.get(it.proposal_outcome)
    matched = PartItem(mpn="m", proposed_disposition="x", proposal_outcome=pe.MATCHED, candidate_dispositions=("x",))
    assert _partitem_to_dict(matched)["abstention_reason"] is None
    assert _partitem_from_dict(_partitem_to_dict(matched)).candidate_dispositions == ("x",)


def test_a_legacy_state_dict_without_the_keys_still_loads():
    legacy = {"mpn": "m", "relevance": 1.0, "subject": None, "proposed_disposition": None,
              "needs_review": False, "proposed_by_ruleset": None}
    it = _partitem_from_dict(legacy)
    assert it.proposal_outcome is None and it.candidate_dispositions == ()


def test_the_reason_phrases_are_bounded_and_cover_exactly_the_abstentions():
    assert set(pe.ABSTENTION_REASON) == {pe.UNCLASSIFIABLE, pe.CONFLICT}
    for v in pe.ABSTENTION_REASON.values():
        assert isinstance(v, str) and "\n" not in v and 0 < len(v) <= 40


# -- the BFF route ---------------------------------------------------------------------------
class _Restate:
    def __init__(self, body):
        self.body = body

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        return httpx.Response(200, json=self.body, request=httpx.Request("POST", url))


def _route(monkeypatch, items):
    async def _pending(user, actor, route):
        return [{"workflow_id": "wf-1", "kind": "grouped_review", "task_id": "t-1"}]
    monkeypatch.setattr(gateway, "_pending_for_actor", _pending)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Restate({"notice_id": "n", "items": items}))
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user("bob")
    try:
        return TestClient(gateway.app).get("/reviews/wf-1/batch")
    finally:
        gateway.app.dependency_overrides.clear()


def test_the_route_serves_the_three_keys_unchanged(monkeypatch):
    r = _route(monkeypatch, [{"mpn": "m", "subject": None, "proposed_disposition": None, "needs_review": False,
                              "proposal_outcome": "conflict", "candidate_dispositions": ["a", "b"],
                              "abstention_reason": "rules disagree"}])
    assert r.status_code == 200
    (it,) = r.json()["items"]
    assert (it["proposal_outcome"], it["candidate_dispositions"], it["abstention_reason"]) == (
        "conflict", ["a", "b"], "rules disagree")


def test_the_route_serves_absent_keys_as_none_and_empty(monkeypatch):
    r = _route(monkeypatch, [{"mpn": "m", "subject": None, "proposed_disposition": None, "needs_review": False}])
    (it,) = r.json()["items"]
    assert it["proposal_outcome"] is None and it["candidate_dispositions"] == [] and it["abstention_reason"] is None


# -- end to end, offline ---------------------------------------------------------------------
def test_composed_batch_state_agrees_with_evaluate_rules_per_part():
    doc_type, _rep, cats = _conflict_case()
    impacted = _parts("MPN-A", "MPN-B")
    build = build_review_batch(
        impacted_parts=impacted, doc_type=doc_type, categories=cats, in_scope_mpns={"MPN-A", "MPN-B"},
        ruleset=RULESET, category_classes=CATEGORY_CLASSES, ruleset_ref=REF, approver="qa",
        resolve_subject=lambda m: f"http://internal/{m}", can_act=lambda a, i: True)
    state = batch_items_to_state(build.batch)
    assert len(state) == 2
    for d in state:
        p = _eval(doc_type, False, cats)
        assert d["proposal_outcome"] == p.outcome
        assert d["candidate_dispositions"] == list(p.candidates)
        assert d["abstention_reason"] == pe.ABSTENTION_REASON.get(p.outcome)
