"""A document promotion takes steward row_edits, behind a server flag that defaults OFF
(architect ruling 2026-10-18: "197 accepts row_edits on document_promotion (validated shape,
obtained_via=steward-corrected, extraction_defect filed), server-flagged off.").

The REAL `promotion.act` runs against fake stores, so the decision record's check inputs are asserted
to carry the corrections. Review reading, the defect audience and the task registry are doubled; no
network, no Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks, ingest_status, promotion  # noqa: E402

HEX = "cd" * 32
INGEST_ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": PREFIX + "PCN26-119.pdf", "content_kind": "pcn",
    "pipeline_version": "doc-tools@61f74dc", "format_fingerprint": "fp-1", "standing": "supervised",
    "extraction_ref": PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/manifest.json",
    "notice_id": "PCN26-119"}
EXTRACTED = ["A-1", "B-2"]
CORRECT = {"corrected": [{"mpn": "A-1", "corrected_mpn": "A-100", "evidence": "page 2, row 1"}]}
FLAG = "IAGENT_PROMOTION_ROW_EDITS"
STRUCT = {"page": 2, "bbox": [10, 20.5, 110, 220], "note": "  the cell  "}
STRUCT_NORM = {"page": 2, "bbox": [10, 20.5, 110, 220], "note": "the cell"}
STRUCT_NO_NOTE = {"page": 3, "bbox": [1, 2, 3, 4]}


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


class _Outbox:
    """Records the correction records a promotion leaves for 7f (build 201)."""

    def __init__(self):
        self.emitted = []

    def emit(self, record):
        self.emitted.append(record)
        return f"corrections/{record['ingest_id'][7:]}/{record['record_id']}.json"


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
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    w = SimpleNamespace(resolved=[], registered=[], statuses=[], ledger=_Ledger(),
                        actors=["steward-1"], exists=False, register_error=None,
                        mpns=list(EXTRACTED), act_kwargs=[])

    def list_tasks(caller, status="pending"):
        return [{"task_id": "t-1", "kind": promotion.KIND, "audience": "document_promotion:SUSTAINMENT",
                 "payload": dict(PAYLOAD)}]

    real_act = promotion.act

    def spy_act(payload, **kw):
        w.act_kwargs.append(kw)
        return real_act(payload, **kw)

    def register(**kw):
        if w.register_error:
            raise w.register_error
        w.registered.append(kw)

    w.corrections = _Outbox()
    stores = promotion.PromotionStores(ledger=w.ledger, graph=_Graph(), corrections=w.corrections)
    monkeypatch.setattr(human_tasks, "list_tasks_for", list_tasks)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: w.resolved.append((tid, kw)) or 1)
    monkeypatch.setattr(human_tasks, "_resolve_audience_actors", lambda aud: list(w.actors))
    monkeypatch.setattr(human_tasks, "task_exists", lambda tid: w.exists)
    monkeypatch.setattr(human_tasks, "register_task", register)
    monkeypatch.setattr(promotion, "act", spy_act)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    monkeypatch.setattr(gateway, "_review_mpns_for_payload", lambda subject: list(w.mpns))
    monkeypatch.setattr(ingest_status, "update_status",
                        lambda iid, stage, *, detail=None: w.statuses.append((iid, stage, detail)))
    user = SimpleNamespace(authz_id="bob", sub="bob", email="bob@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        w.client = c
        yield w
    gateway.app.dependency_overrides.clear()


def _promote(w, edits=CORRECT, decision="promoted"):
    body = {"decision": decision}
    if edits is not None:
        body["row_edits"] = edits
    return w.client.post("/human_tasks/t-1/act", json=body)


def _nothing_written(w):
    assert w.act_kwargs == [] and w.ledger.records == {}
    assert w.registered == [] and w.resolved == [] and w.statuses == []


@pytest.mark.parametrize("flag", ["true", "TRUE", " true "])
def test_flag_on_a_correction_rides_the_record_and_files_one_defect(world, monkeypatch, flag):
    """Arm 1 (and the ON side of 2): the corrected entry is stamped steward-corrected, lands on the
    decision record's human_review inputs, one extraction_defect is filed, the task resolves once."""
    monkeypatch.setenv(FLAG, flag)
    r = _promote(world)
    assert r.status_code == 200, r.text
    got = world.act_kwargs[0]["row_edits"]
    assert len(got) == 1 and got[0]["op"] == "corrected"
    assert got[0]["obtained_via"] == "steward-corrected" and got[0]["corrected_by"] == "bob"
    assert got[0]["extracted_value"] == "A-1" and got[0]["corrected_value"] == "A-100"
    (stored,) = world.ledger.records.values()
    check = stored["record"]["checks"][0]
    assert check["inputs"]["row_edits"] == got
    body = r.json()
    rid = body["record_id"]
    assert len(world.registered) == 1
    reg = world.registered[0]
    assert reg["kind"] == "extraction_defect" and reg["audience"] == "dispatch_failure:SUSTAINMENT"
    assert reg["task_id"] == f"extraction-defect:PCN26-119:{rid}"
    assert body["extraction_defect"] == reg["task_id"]
    assert body["row_edits"] == {"corrected": 1, "added": 0, "deleted": 0, "header": 0}
    assert body["corrections"] == got
    assert len(world.resolved) == 1


@pytest.mark.parametrize("flag", [None, "", "false", "1", "yes"])
def test_flag_off_is_refused_by_name_and_nothing_runs(world, monkeypatch, flag):
    """Arm 2: only the exact string true is ON; every other spelling refuses before any write."""
    if flag is not None:
        monkeypatch.setenv(FLAG, flag)
    r = _promote(world)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "row_edits_not_for_kind" and d["enabled"] is False
    _nothing_written(world)


def test_a_corrected_mpn_that_is_not_a_row_is_refused_and_nothing_is_written(world, monkeypatch):
    """Arm 3."""
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, {"corrected": [{"mpn": "ZZ-9", "corrected_mpn": "ZZ-10", "evidence": "p1"}]})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "row_edits_refused", r.text
    _nothing_written(world)


def test_an_added_mpn_colliding_with_an_extracted_row_is_refused(world, monkeypatch):
    """Arm 4."""
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, {"added": [{"mpn": "b-2", "disposition": "affected", "reason": "missed",
                                    "evidence": "p3"}]})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "row_edits_refused", r.text
    _nothing_written(world)


def test_an_unroutable_defect_audience_refuses_before_the_act(world, monkeypatch):
    """Arm 5: nobody holds dispatch_failure:SUSTAINMENT -> 409, the act never ran."""
    monkeypatch.setenv(FLAG, "true")
    world.actors = []
    r = _promote(world)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "extraction_defect_unroutable" and d["audience"] == "dispatch_failure:SUSTAINMENT"
    _nothing_written(world)


def test_a_defect_that_cannot_be_filed_leaves_the_task_pending_and_a_retry_finishes(world, monkeypatch):
    """Arm 6: 503, not resolved; the second identical act replays the record and files the defect."""
    monkeypatch.setenv(FLAG, "true")
    world.register_error = RuntimeError("db down")
    r = _promote(world)
    assert r.status_code == 503, r.text
    d = r.json()["detail"]
    assert d["error"] == "extraction_defect_not_filed" and d["record_id"]
    assert world.resolved == [] and len(world.ledger.records) == 1
    world.register_error = None
    r2 = _promote(world)
    assert r2.status_code == 200, r2.text
    assert r2.json()["replayed"] is True
    assert len(world.registered) == 1 and len(world.resolved) == 1
    assert len(world.ledger.records) == 1


def test_a_no_requester_filing_the_defect_is_a_terminal_422_not_a_retried_503(world, monkeypatch):
    """Same fixture as arm 6 (RuntimeError -> 503, the control); it differs only in the exception
    type: a NoRequester is permanent, so 422 no_requester, never the retried 503."""
    monkeypatch.setenv(FLAG, "true")
    world.register_error = human_tasks.NoRequester("no requester")
    r = _promote(world)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_requester"
    assert world.resolved == []


def test_an_existing_defect_task_is_not_registered_again(world, monkeypatch):
    """Arm 7: idempotent on the task key."""
    monkeypatch.setenv(FLAG, "true")
    world.exists = True
    r = _promote(world)
    assert r.status_code == 200, r.text
    assert world.registered == [] and len(world.resolved) == 1


def test_control_promoted_without_row_edits_is_unchanged(world, monkeypatch):
    """Arm 8: no corrections, no defect, no new key on the record or in the body."""
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, edits=None)
    assert r.status_code == 200, r.text
    assert world.act_kwargs[0].get("row_edits") is None
    assert world.registered == []
    body = r.json()
    assert "extraction_defect" not in body and "row_edits" not in body and "corrections" not in body
    (stored,) = world.ledger.records.values()
    assert "row_edits" not in stored["record"]["checks"][0]["inputs"]


def test_an_empty_row_edits_is_treated_as_none(world, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, edits={})
    assert r.status_code == 200, r.text
    assert world.registered == [] and "extraction_defect" not in r.json()


def test_a_reject_with_row_edits_is_refused_by_the_verb_fields(world, monkeypatch):
    """Arm 9."""
    monkeypatch.setenv(FLAG, "true")
    r = world.client.post("/human_tasks/t-1/act", json={
        "decision": "rejected", "comment": "unreadable", "row_edits": CORRECT})
    assert r.status_code == 422, r.text
    _nothing_written(world)


def test_the_extraction_must_sit_under_the_documents_own_directory(monkeypatch):
    """The real helper: an extraction_ref outside the document's directory is extraction_unbound."""
    subject = promotion.subject_from_payload(dict(PAYLOAD, extraction_ref="ingress-user/pdf/other/m.json"))
    with pytest.raises(fastapi.HTTPException) as ei:
        gateway._review_mpns_for_payload(subject)
    assert ei.value.status_code == 422 and ei.value.detail["error"] == "extraction_unbound"


def test_build_record_carries_row_edits_only_when_there_are_some():
    subject = promotion.subject_from_payload(dict(PAYLOAD))
    kw = dict(decision="promoted", acted_by="bob", audience="document_promotion:SUSTAINMENT",
              comment="", governing={"ruleset_ref": "r", "trust_table_ref": "t"}, era="commissioning")
    edits = [{"op": "deleted", "mpn": "A-1", "reason": "x"}]
    with_edits = promotion.build_record(subject, row_edits=edits, **kw)
    without = promotion.build_record(subject, **kw)
    assert with_edits["checks"][0]["inputs"]["row_edits"] == edits
    assert "row_edits" not in without["checks"][0]["inputs"]
    assert "row_edits" not in promotion.build_record(subject, row_edits=[], **kw)["checks"][0]["inputs"]


OTHER = {"corrected": [{"mpn": "B-2", "corrected_mpn": "B-200", "evidence": "page 3, row 4"}]}


def _first_act_files_no_defect(world, monkeypatch, edits):
    """A first act that records `edits` and then fails to file its defect: 503, task pending."""
    monkeypatch.setenv(FLAG, "true")
    world.register_error = RuntimeError("db down")
    r = _promote(world, edits=edits)
    assert r.status_code == 503, r.text
    assert len(world.ledger.records) == 1 and world.resolved == []
    world.register_error = None


def test_a_retry_with_different_corrections_is_refused_and_the_record_stands(world, monkeypatch):
    """A replay re-applies the STORED record, so corrections that are not the record's would be
    answered and filed as the defect without ever being recorded."""
    _first_act_files_no_defect(world, monkeypatch, CORRECT)
    (stored,) = world.ledger.records.values()
    before = stored["record"]
    r = _promote(world, edits=OTHER)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "row_edits_differ_from_the_record"
    assert world.registered == [] and world.resolved == []
    assert stored["record"] is before


def test_a_retry_without_the_recorded_corrections_is_refused(world, monkeypatch):
    """The other direction: dropping the edits on the retry would resolve with no defect filed."""
    _first_act_files_no_defect(world, monkeypatch, CORRECT)
    r = _promote(world, edits=None)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "row_edits_differ_from_the_record"
    assert world.registered == [] and world.resolved == []


def test_a_replay_whose_stored_record_is_unreadable_refuses_corrections(world, monkeypatch):
    """Fail closed: a conflict row that does not return its record cannot confirm the edits."""
    _first_act_files_no_defect(world, monkeypatch, CORRECT)
    (stored,) = world.ledger.records.values()
    stored.pop("record")
    r = _promote(world, edits=CORRECT)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "row_edits_differ_from_the_record"
    assert world.registered == [] and world.resolved == []


def test_control_a_replay_without_corrections_on_a_record_without_them_finishes(world, monkeypatch):
    """The control for the three above: same gate, same replay, no edits on either side."""
    monkeypatch.setenv(FLAG, "true")
    first = _promote(world, edits=None)
    assert first.status_code == 200, first.text
    (stored,) = world.ledger.records.values()
    stored.pop("record")   # unreadable is fine when nothing is being held to it
    r = _promote(world, edits=None)
    assert r.status_code == 200, r.text
    assert r.json()["replayed"] is True


# -- evidence_ref on every row op (build 201): optional on the wire, blank is a 422 ---------------

_OPS = {
    "corrected": {"corrected": [{"mpn": "A-1", "corrected_mpn": "A-100", "evidence": "p2"}]},
    "added": {"added": [{"mpn": "C-3", "disposition": "affected", "reason": "missed",
                         "evidence": "p3"}]},
    "deleted": {"deleted": [{"mpn": "B-2", "reason": "not on the notice"}]},
}


def _with(op, **extra):
    edits = {k: [dict(r, **extra) for r in rows] for k, rows in _OPS[op].items()}
    return edits


@pytest.mark.parametrize("op", sorted(_OPS))
def test_a_legacy_string_evidence_ref_is_recorded_stripped_as_the_note(world, monkeypatch, op):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, _with(op, evidence_ref="  s3://ev/p2.png  "))
    assert r.status_code == 200, r.text
    got = world.act_kwargs[0]["row_edits"]
    assert len(got) == 1 and got[0]["op"] == op and got[0]["evidence_ref"] == {"note": "s3://ev/p2.png"}
    (stored,) = world.ledger.records.values()
    assert stored["record"]["checks"][0]["inputs"]["row_edits"] == got
    # and the extraction_defect's edit log carries it
    (edit,) = world.registered[0]["payload"]["edits"]
    assert edit["evidence_ref"] == {"note": "s3://ev/p2.png"}


@pytest.mark.parametrize("op", sorted(_OPS))
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_row_op_evidence_ref_is_a_422_and_nothing_is_written(world, monkeypatch, op, blank):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, _with(op, evidence_ref=blank))
    assert r.status_code == 422, r.text
    _nothing_written(world)


@pytest.mark.parametrize("op", sorted(_OPS))
def test_a_row_op_without_evidence_ref_records_exactly_todays_dict(world, monkeypatch, op):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, _with(op))
    assert r.status_code == 200, r.text
    got = world.act_kwargs[0]["row_edits"]
    assert len(got) == 1 and "evidence_ref" not in got[0]
    (edit,) = world.registered[0]["payload"]["edits"]
    assert "evidence_ref" not in edit


def test_the_defect_payload_names_the_ingest_and_the_response_names_the_correction(world, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world)
    assert r.status_code == 200, r.text
    assert world.registered[0]["payload"]["ingest_id"] == PAYLOAD["ingest_id"]
    assert r.json()["correction"]["key"] == (
        f"corrections/{PAYLOAD['ingest_id'][7:]}/{r.json()['record_id']}.json")


# -- evidence_ref takes the SDK struct {page, bbox, note?}; the legacy string becomes `note` -----
# (architect 2026-10-21)

def _surfaces(w):
    """The three places a row edit is recorded: the act's row_edits (= the ledger's check inputs),
    the extraction_defect's edit log, and the correction record 7f reads."""
    (stored,) = w.ledger.records.values()
    got = w.act_kwargs[0]["row_edits"]
    assert stored["record"]["checks"][0]["inputs"]["row_edits"] == got
    (rec,) = w.corrections.emitted
    assert rec["row_edits"] == got
    return got, w.registered[0]["payload"]["edits"], rec["row_edits"]


@pytest.mark.parametrize("op", sorted(_OPS))
@pytest.mark.parametrize("sent,want", [
    (STRUCT, STRUCT_NORM), (STRUCT_NO_NOTE, STRUCT_NO_NOTE),
    ("  legacy ref ", {"note": "legacy ref"}),
], ids=["struct", "struct_no_note", "legacy_string"])
def test_every_surface_records_the_normalized_evidence_ref(world, monkeypatch, op, sent, want):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, _with(op, evidence_ref=sent))
    assert r.status_code == 200, r.text
    got, log, rec = _surfaces(world)
    assert len(got) == len(log) == len(rec) == 1
    assert got[0]["evidence_ref"] == want
    assert log[0]["evidence_ref"] == want
    assert rec[0]["evidence_ref"] == want
    assert ("note" in got[0]["evidence_ref"]) == ("note" in want)     # never a `note: None`


@pytest.mark.parametrize("op", sorted(_OPS))
@pytest.mark.parametrize("bad", [
    "", "   ", 5, [], {}, {"bbox": [1, 2, 3, 4]}, {"page": 1},
    {"page": 0, "bbox": [1, 2, 3, 4]}, {"page": -1, "bbox": [1, 2, 3, 4]},
    {"page": True, "bbox": [1, 2, 3, 4]}, {"page": "1", "bbox": [1, 2, 3, 4]},
    {"page": 1.5, "bbox": [1, 2, 3, 4]},
    {"page": 1, "bbox": [1, 2, 3]}, {"page": 1, "bbox": [1, 2, 3, 4, 5]},
    {"page": 1, "bbox": [True, 2, 3, 4]}, {"page": 1, "bbox": ["1", 2, 3, 4]},
    {"page": 1, "bbox": "1,2,3,4"},
    {"page": 1, "bbox": [1, 2, 3, 4], "extra": "x"},
    {"page": 1, "bbox": [1, 2, 3, 4], "note": " "}, {"page": 1, "bbox": [1, 2, 3, 4], "note": 7},
], ids=["blank", "spaces", "int", "list", "empty_obj", "no_page", "no_bbox", "page0", "page_neg",
        "page_bool", "page_str", "page_float", "bbox3", "bbox5", "bbox_bool", "bbox_str",
        "bbox_not_list", "extra_key", "blank_note", "note_not_str"])
def test_a_malformed_evidence_ref_is_a_wire_422_and_nothing_is_written(world, monkeypatch, op, bad):
    monkeypatch.setenv(FLAG, "true")
    r = _promote(world, _with(op, evidence_ref=bad))
    assert r.status_code == 422, r.text
    _nothing_written(world)


@pytest.mark.parametrize("sent", [STRUCT, "legacy ref"], ids=["struct", "legacy_string"])
def test_the_same_act_twice_writes_byte_identical_correction_records(world, monkeypatch, sent):
    monkeypatch.setenv(FLAG, "true")
    body = _with("corrected", evidence_ref=sent)
    assert _promote(world, body).status_code == 200
    r2 = _promote(world, body)
    assert r2.status_code == 200 and r2.json()["replayed"] is True, r2.text
    import json as _json
    blobs = {_json.dumps(e, sort_keys=True) for e in world.corrections.emitted}
    assert len(world.corrections.emitted) >= 2 and len(blobs) == 1
    (stored,) = world.ledger.records.values()
    assert _json.dumps(world.corrections.emitted[0]["row_edits"], sort_keys=True) == _json.dumps(
        stored["record"]["checks"][0]["inputs"]["row_edits"], sort_keys=True)


def test_a_record_stored_with_a_legacy_string_still_replays(world, monkeypatch):
    """Recorded data is never re-parsed into the new shape: a record written before the struct
    holds `evidence_ref: "<string>"`, and the same act arriving now must still replay it."""
    monkeypatch.setenv(FLAG, "true")
    body = _with("corrected", evidence_ref="p2 legacy")
    assert _promote(world, body).status_code == 200
    (stored,) = world.ledger.records.values()
    (e,) = stored["record"]["checks"][0]["inputs"]["row_edits"]
    assert e["evidence_ref"] == {"note": "p2 legacy"}
    e["evidence_ref"] = "p2 legacy"                  # the record as an earlier build wrote it
    r2 = _promote(world, body)
    assert r2.status_code == 200 and r2.json()["replayed"] is True, r2.text
    assert stored["record"]["checks"][0]["inputs"]["row_edits"][0]["evidence_ref"] == "p2 legacy"
