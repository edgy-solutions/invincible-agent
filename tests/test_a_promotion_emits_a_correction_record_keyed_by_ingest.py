"""A promotion that changes the notice's parts leaves a self-contained correction record in S3,
keyed by ingest id, for 7f (doc-tools) to apply to RDF (build 201).

The ruling: "Corrected parts reach BOTH stores." The BFF writes Neo4j; 7f's producer owns RDF. We
emit the record; 7f builds the consumer. The record is pure of clock and randomness, so a replay
writes the same bytes to the same key.

Run: uv run --frozen pytest tests/test_a_promotion_emits_a_correction_record_keyed_by_ingest.py -q
"""
from __future__ import annotations

import json
import re

import pytest

from src.iagent import promotion, promotion_stores

HEX = "ab" * 32
INGEST_ID = "sha256:" + HEX
AUDIENCE = "document_promotion:SUSTAINMENT"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": f"ingress-user/pdf/{HEX}/pcn-4471.pdf",
    "content_kind": "work-instructions", "pipeline_version": "doc-tools@7f-33",
    "format_fingerprint": "pdf:pcn:v1", "standing": "supervised",
    "extraction_ref": "s3://extractions/pcn-4471/review.json", "notice_id": "PCN-4471",
}
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}
KEY_RE = re.compile(r"^corrections/[0-9a-f]{64}/[^/]+\.json$")


def _dump(record):
    """The S3 outbox's exact serialisation."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Ledger:
    def __init__(self):
        self.records, self.appends = {}, 0

    def append(self, record, *, acted_by, acted_at):
        self.appends += 1
        rid = record["record_id"]
        if rid in self.records:
            return {"ok": False, "reason": "immutable_conflict", "existing": self.records[rid]}
        self.records[rid] = {"decision": record["outcome"], "acted_by": acted_by,
                             "acted_at": acted_at, "record": record}
        return {"ok": True}

    def only_record(self):
        return next(iter(self.records.values()))["record"]


class Graph:
    def __init__(self, edges=None):
        self.edges = None if edges is None else list(edges)

    def node_exists(self, iid):
        return True

    def notice_mpns(self, ingest_id, *, domain):
        return None if self.edges is None else list(self.edges)

    def apply_row_edits(self, ingest_id, row_edits, *, domain, record_id):
        return {"deleted": 0, "corrected": 0, "added": 0, "not_applied": []}

    def remove_notice_edges(self, ingest_id, mpns, *, domain):
        return len(mpns)

    def write_fact(self, iid, fact):
        pass

    def attest_origin(self, iid, *, owner_domain, record_id):
        return "written"

    def delete_carrying(self, iid):
        return 0


class Outbox:
    def __init__(self, fail=False):
        self.emitted, self.fail = [], fail

    def emit(self, record):
        if self.fail:
            raise RuntimeError("s3 down")
        self.emitted.append(record)
        return promotion.correction_key(record["ingest_id"], record["record_id"])


class _Idx:
    def delete_carrying(self, iid):
        return 0


class _Obj:
    def quarantine(self, iid, ref):
        return []


def _act(ledger, outbox, *, graph=None, row_edits=None, reviewed=None, decision="promoted",
         now_ms=1_000):
    stores = promotion.PromotionStores(ledger=ledger, graph=graph or Graph(), corrections=outbox,
                                       indexes=_Idx(), objects=_Obj())
    return promotion.act(
        dict(PAYLOAD), decision=decision, acted_by="bob", audience=AUDIENCE, comment="why",
        can_act=lambda a, c: True, stores=stores, governing=GOVERNING, era="commissioning",
        now_ms=now_ms, row_edits=row_edits, reviewed_mpns=reviewed, earlier_ingests=[])


def _deleted(mpn):
    return {"op": "deleted", "mpn": mpn, "reason": "not on the notice"}


def _human_review(ledger):
    for c in ledger.only_record()["checks"]:
        if c["name"] == "human_review":
            return c["inputs"]
    raise AssertionError("no human_review check")


def _reconciled_mpns(ledger):
    rec = _human_review(ledger).get("reconciliation") or {}
    return [e["mpn"] for e in rec.get("removed", [])]


# -- arm 1 ----------------------------------------------------------------------------------------

def test_a_promotion_with_row_edits_emits_exactly_one_record_keyed_by_ingest():
    ledger, box = Ledger(), Outbox()
    out = _act(ledger, box, graph=Graph(["R1", "R2", "S1"]), reviewed=["R1"],
               row_edits=[_deleted("R2")])
    assert len(box.emitted) == 1
    rec = box.emitted[0]
    key = promotion.correction_key(INGEST_ID, out["record_id"])
    assert KEY_RE.match(key) and key == f"corrections/{HEX}/{out['record_id']}.json"
    assert out["correction"] == {"key": key}
    assert rec == promotion.correction_record(
        promotion.subject_from_payload(PAYLOAD), record_id=out["record_id"], domain="SUSTAINMENT",
        acted_by="bob", acted_at=1_000, row_edits=_human_review(ledger)["row_edits"],
        reconcile_mpns=_reconciled_mpns(ledger))
    assert rec["ingest_id"] == INGEST_ID and rec["record_id"] == out["record_id"]
    assert rec["row_edits"] == _human_review(ledger)["row_edits"] == [_deleted("R2")]
    assert rec["reconciled"]["removed"] == _reconciled_mpns(ledger) == ["S1"]
    assert rec["kind"] == "promotion_correction" and rec["schema_version"] == "1"


# -- arm 2 / 3 ------------------------------------------------------------------------------------

def test_a_reconcile_alone_emits_a_record_with_no_row_edits():
    ledger, box = Ledger(), Outbox()
    _act(ledger, box, graph=Graph(["R1", "S1"]), reviewed=["R1"])
    (rec,) = box.emitted
    assert rec["row_edits"] == [] and rec["reconciled"]["removed"] == ["S1"]


def test_nothing_to_change_emits_nothing_and_needs_no_outbox():
    box = Outbox()
    out = _act(Ledger(), box, graph=Graph(["R1"]), reviewed=["R1"])
    assert box.emitted == [] and "correction" not in out
    out = _act(Ledger(), None, graph=Graph(["R1"]), reviewed=["R1"])
    assert out["decision"] == "promoted" and "correction" not in out
    out = _act(Ledger(), None, graph=Graph(None))       # no notice node, no edits at all
    assert out["decision"] == "promoted" and "correction" not in out


# -- arm 4 ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"graph": Graph(["R1", "R2"]), "reviewed": ["R1"], "row_edits": [_deleted("R2")]},
    {"graph": Graph(["R1", "S1"]), "reviewed": ["R1"]},
], ids=["row_edits", "reconcile_only"])
def test_wanting_a_record_with_no_outbox_is_refused_503_before_the_ledger(kw):
    ledger = Ledger()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(ledger, None, **kw)
    assert ei.value.status == 503 and ei.value.error == "promotion_store_unconfigured"
    assert "corrections" in str(ei.value)
    assert ledger.appends == 0 and ledger.records == {}


# -- arm 5 ----------------------------------------------------------------------------------------

def test_a_replay_emits_a_body_byte_identical_to_the_first_act():
    ledger = Ledger()
    first_box, replay_box = Outbox(), Outbox()
    first = _act(ledger, first_box, graph=Graph(["R1", "R2", "S1"]), reviewed=["R1"],
                 row_edits=[_deleted("R2")], now_ms=1_000)
    # the replay arrives later, against a graph that no longer holds the pruned edges
    again = _act(ledger, replay_box, graph=Graph(["R1"]), reviewed=["R1"],
                 row_edits=[_deleted("R2")], now_ms=9_999)
    assert again["replayed"] is True and ledger.appends == 2
    assert replay_box.emitted and _dump(first_box.emitted[0]) == _dump(replay_box.emitted[0])
    assert first["correction"] == again["correction"]


# -- arm 6 ----------------------------------------------------------------------------------------

def test_an_outbox_that_raises_is_a_retryable_refusal_naming_the_step():
    ledger = Ledger()
    with pytest.raises(promotion.PromotionRefused) as ei:
        _act(ledger, Outbox(fail=True), graph=Graph(["R1", "S1"]), reviewed=["R1"])
    assert ei.value.status == 503 and ei.value.error == "promotion_effect_incomplete"
    assert "corrections" in str(ei.value)
    assert len(ledger.records) == 1     # the record stands; acting again completes it


# -- arm 7 ----------------------------------------------------------------------------------------

def test_a_rejection_never_emits():
    box = Outbox()
    out = _act(Ledger(), box, decision="rejected", row_edits=[_deleted("R2")])
    assert out["decision"] == "rejected" and box.emitted == []


# -- arm 8 ----------------------------------------------------------------------------------------

class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def test_the_s3_outbox_puts_sorted_compact_json_at_the_key_and_returns_it():
    s3 = FakeS3()
    box = promotion_stores.S3CorrectionOutbox(lambda: s3, "artifacts")
    rec = promotion.correction_record(
        promotion.subject_from_payload(PAYLOAD), record_id="r-1", domain="SUSTAINMENT",
        acted_by="bob", acted_at=7, row_edits=[_deleted("R2")], reconcile_mpns=["S2", "S1"])
    key = box.emit(rec)
    assert key == f"corrections/{HEX}/r-1.json"
    (put,) = s3.puts
    assert put["Bucket"] == "artifacts" and put["Key"] == key
    assert put["ContentType"] == "application/json"
    assert json.loads(put["Body"].decode("utf-8")) == rec
    assert put["Body"].decode("utf-8") == _dump(rec)
    assert rec["reconciled"]["removed"] == ["S1", "S2"]     # sorted, so the bytes are stable


@pytest.mark.parametrize("bad", ["", "abc", "sha256:" + "ab" * 31, "sha256:" + "AB" * 32,
                                 HEX, "sha256:" + "ab" * 32 + "/x", None])
def test_correction_key_refuses_anything_but_sha256_hex64(bad):
    with pytest.raises(ValueError):
        promotion.correction_key(bad, "r-1")


def test_correction_record_is_pure_the_same_inputs_give_the_same_dict():
    subj = promotion.subject_from_payload(PAYLOAD)
    kw = dict(record_id="r-1", domain="D", acted_by="bob", acted_at=7, row_edits=None,
              reconcile_mpns=None)
    a, b = promotion.correction_record(subj, **kw), promotion.correction_record(subj, **kw)
    assert _dump(a) == _dump(b) and a["row_edits"] == [] and a["reconciled"]["removed"] == []
