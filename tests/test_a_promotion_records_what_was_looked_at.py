"""A promotion records what the steward looked at (ruled 2026-10-29: a sampled promote is legal if it
is recorded). `review_coverage` is declared on the act, checked against the extraction's part set
(every part opened, or folded into a named group), and carried on the decision record's
human_review inputs. Without the declaration the act dropped it silently: 200 and no provenance.

The REAL `promotion.act` runs against fake stores; the extraction's part set is doubled. No network,
no Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks, ingest_status, promotion  # noqa: E402

HEX = "ef" * 32
INGEST_ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": PREFIX + "PCN26-120.pdf", "content_kind": "pcn",
    "pipeline_version": "doc-tools@61f74dc", "format_fingerprint": "fp-1", "standing": "supervised",
    "extraction_ref": PREFIX + "generated/PCN26-120_pdf/doc-tools@61f74dc/manifest.json",
    "notice_id": "PCN26-120"}
PARTS = [0, 1, 2, 3, 4, 5]          # the fixture's part set (distinct part_index of the extraction)


def _cov(**over):
    base = {"rules_version": "cortex.reviewRuns.v1", "looked_at": [0, 1, 5], "sampled": [1, 3],
            "flagged": [2],
            "groups": [{"rule": "same_shape_run", "key": "FK25->FK25", "parts": [2, 3, 4]}],
            "shared": [{"rule": "same_inherited_crop", "page": 1, "bbox": [0.1, 0.2, 0.9, 0.8],
                        "parts": [2, 3], "confirmed": True}],
            "sample": {"seed": "abc", "per_run": 2, "min_run": 3, "all": False}}
    base.update(over)
    return base


class _Ledger:
    def __init__(self):
        self.records = {}

    def append(self, record, *, acted_by, acted_at):
        rid = record["record_id"]
        if rid in self.records:
            return {"ok": False, "reason": "immutable_conflict", "existing": self.records[rid]}
        self.records[rid] = {"decision": record["outcome"], "acted_by": acted_by,
                             "acted_at": acted_at, "record": record}
        return {"ok": True}


class _Graph:
    def node_exists(self, ingest_id):
        return True

    def notice_mpns(self, ingest_id, *, domain):
        return None

    def write_fact(self, ingest_id, fact):
        return None

    def apply_row_edits(self, ingest_id, row_edits, *, domain, record_id):
        return {"deleted": 0, "corrected": 0, "added": 0, "not_applied": []}

    def attest_origin(self, ingest_id, *, owner_domain, record_id):
        return {"ok": True}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    w = SimpleNamespace(resolved=[], statuses=[], ledger=_Ledger(), kind=promotion.KIND,
                        act_kwargs=[], parts=list(PARTS), part_reads=[], unreadable=False, unbound=False)

    def list_tasks(caller, status="pending"):
        return [{"task_id": "t-1", "kind": w.kind, "audience": "document_promotion:SUSTAINMENT",
                 "payload": dict(PAYLOAD)}]

    real_act = promotion.act

    def spy_act(payload, **kw):
        w.act_kwargs.append(kw)
        return real_act(payload, **kw)

    def read_parts(subject):
        w.part_reads.append(subject.ingest_id)
        if w.unbound:
            raise HTTPException(status_code=422, detail={"error": "extraction_unbound"})
        if w.unreadable:
            raise HTTPException(status_code=503, detail={"error": "artifact_store_unreachable"})
        return list(w.parts)

    stores = promotion.PromotionStores(ledger=w.ledger, graph=_Graph())
    monkeypatch.setattr(human_tasks, "list_tasks_for", list_tasks)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: w.resolved.append((tid, kw)) or 1)
    monkeypatch.setattr(promotion, "act", spy_act)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    monkeypatch.setattr(gateway, "_review_mpns_for_payload", lambda subject: ["A-1", "B-2"])
    monkeypatch.setattr(gateway, "_review_parts_for_payload", read_parts)
    monkeypatch.setattr(ingest_status, "get_row", lambda _id: None)
    monkeypatch.setattr(ingest_status, "update_status",
                        lambda iid, stage, *, detail=None: w.statuses.append((iid, stage, detail)))
    user = SimpleNamespace(authz_id="bob", sub="bob", email="bob@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        w.client = c
        yield w
    gateway.app.dependency_overrides.clear()


def _act(w, coverage=None, decision="promoted", comment=""):
    body = {"decision": decision, "comment": comment}
    if coverage is not None:
        body["review_coverage"] = coverage
    return w.client.post("/human_tasks/t-1/act", json=body)


def _nothing_written(w):
    assert w.act_kwargs == [] and w.ledger.records == {}
    assert w.resolved == [] and w.statuses == []


def _inputs(w):
    (stored,) = w.ledger.records.values()
    (check,) = [c for c in stored["record"]["checks"] if c["name"] == "human_review"]
    return check["inputs"]


def _invalid(r, check):
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "review_coverage_invalid" and d["check"] == check, d


def test_c1_a_valid_coverage_is_recorded_on_the_human_review_inputs(world):
    r = _act(world, _cov())
    assert r.status_code == 200, r.text
    assert world.part_reads == [INGEST_ID]
    assert _inputs(world)["review_coverage"] == gateway.ReviewCoverage(**_cov()).model_dump()


def test_c2_no_coverage_leaves_the_inputs_exactly_as_before(world):
    r = _act(world)
    assert r.status_code == 200, r.text
    assert _inputs(world) == {
        "extraction_ref": PAYLOAD["extraction_ref"], "content_kind": "pcn",
        "reviewed_by": "human:bob", "audience": "document_promotion:SUSTAINMENT", "comment": ""}
    assert world.part_reads == []


def test_c3_an_unknown_part_is_refused(world):
    _invalid(_act(world, _cov(looked_at=[0, 1, 5, 99])), "unknown_part")
    _nothing_written(world)


@pytest.mark.parametrize("over", [
    {"looked_at": [0, 1, 1, 5]},
    {"sampled": [1, 1]},
    {"groups": [{"rule": "r", "key": "k", "parts": [2, 3, 3, 4]}]},
], ids=["looked_at", "sampled", "group"])
def test_c4_a_repeated_part_is_refused(world, over):
    _invalid(_act(world, _cov(**over)), "duplicate_part")
    _nothing_written(world)


@pytest.mark.parametrize("over", [
    {"groups": [{"rule": "r", "key": "k", "parts": [1, 2, 3, 4]}]},                  # opened and folded
    {"groups": [{"rule": "r", "key": "k", "parts": [2, 3, 4]},
                {"rule": "r", "key": "j", "parts": [4]}]},                          # two groups
], ids=["looked_at_and_group", "two_groups"])
def test_c5_a_part_opened_and_folded_is_refused(world, over):
    _invalid(_act(world, _cov(**over)), "overlap")
    _nothing_written(world)


def test_c6_a_part_neither_opened_nor_grouped_is_refused(world):
    # the fixture's part 4 is neither opened nor in a group
    _invalid(_act(world, _cov(groups=[{"rule": "r", "key": "k", "parts": [2, 3]}])), "uncovered")
    _nothing_written(world)


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(surprise=1),
    lambda c: c["groups"][0].update(surprise=1),
    lambda c: c["shared"][0].update(surprise=1),
    lambda c: c["looked_at"].__setitem__(0, "0"),
    lambda c: c.update(rules_version=""),
], ids=["top", "group", "shared", "strict_int", "blank_rules_version"])
def test_c7_an_unknown_key_or_a_loose_value_is_refused_not_dropped(world, mutate):
    c = _cov()
    mutate(c)
    r = _act(world, c)
    assert r.status_code == 422, r.text
    _nothing_written(world)


def test_c8_coverage_needs_a_promote_and_a_promotion_kind(world):
    r = _act(world, _cov(), decision="rejected", comment="unreadable")
    assert r.status_code == 422, r.text
    _nothing_written(world)
    world.kind = "grouped_review"
    r = _act(world, _cov())
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "review_coverage_not_for_kind"
    _nothing_written(world)


def test_c9_an_unreadable_extraction_is_a_503_and_nothing_is_written(world):
    world.unreadable = True
    r = _act(world, _cov())
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "review_coverage_unverifiable"
    _nothing_written(world)


def test_c9b_an_unbound_extraction_stays_a_422_not_a_retryable_503(world):
    # A 503 tells the card to retry; an extraction outside the document's directory never heals.
    world.unbound = True
    r = _act(world, _cov())
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "extraction_unbound"
    _nothing_written(world)


def test_c10_a_replay_must_carry_the_recorded_coverage(world):
    assert _act(world, _cov()).status_code == 200
    again = _act(world, _cov())
    assert again.status_code == 200, again.text
    assert again.json().get("replayed") is True or len(world.ledger.records) == 1
    other = _act(world, _cov(flagged=[1]))
    assert other.status_code == 409, other.text
    assert other.json()["detail"]["error"] == "review_coverage_differs_from_the_record"
    none = _act(world)
    assert none.status_code == 409, none.text
    assert none.json()["detail"]["error"] == "review_coverage_differs_from_the_record"
    assert len(world.ledger.records) == 1


def test_c11_a_refused_coverage_writes_no_record_and_calls_no_store(world):
    for bad in (_cov(looked_at=[0, 1, 5, 99]), _cov(looked_at=[0, 0, 1, 5]),
                _cov(groups=[{"rule": "r", "key": "k", "parts": [1, 2, 3, 4]}]),
                _cov(groups=[])):
        assert _act(world, bad).status_code == 422
    _nothing_written(world)


def test_c12_control_every_part_opened_and_no_groups_passes(world):
    r = _act(world, _cov(looked_at=list(PARTS), groups=[], shared=[], sampled=[], flagged=[]))
    assert r.status_code == 200, r.text
    assert _inputs(world)["review_coverage"]["groups"] == []
