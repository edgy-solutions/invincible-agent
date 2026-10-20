"""header_edits on the document-promotion wire (architect ruling 10-20, Q8 amended):
"header fields are correctable on the same wire as rows. header_edits: [{field in
mfr|notice_id|notice_date, value, evidence_ref, reason}] alongside row_edits, same flag, same
obtained_via=steward-corrected, same extraction_defect filing."

The REAL `promotion.act` runs against fake stores; the bound review read, the defect audience and the
task registry are doubled. No network, no Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.restate_analyst import steward_correction as sc  # noqa: E402
from src.iagent import gateway, human_tasks, ingest_status, promotion  # noqa: E402

HEX = "cd" * 32
INGEST_ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": PREFIX + "PCN26-119.pdf", "content_kind": "pcn",
    "pipeline_version": "doc-tools@61f74dc", "format_fingerprint": "fp-1", "standing": "supervised",
    "extraction_ref": PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/manifest.json",
    "notice_id": "PCN26-119"}
FLAG = "IAGENT_PROMOTION_ROW_EDITS"
MFR = {"field": "mfr", "value": "TYC", "evidence_ref": "p1", "reason": "text layer dropped ti"}
ROW = {"corrected": [{"mpn": "A-1", "corrected_mpn": "A-100", "evidence": "page 2, row 1"}]}


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

    def write_fact(self, ingest_id, fact):
        return None

    def attest_origin(self, ingest_id, *, owner_domain, record_id):
        return {"ok": True}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    w = SimpleNamespace(resolved=[], registered=[], statuses=[], ledger=_Ledger(),
                        actors=["steward-1"], kind=promotion.KIND, act_kwargs=[],
                        header={"notice_id": None, "mfr": None, "notice_date": None})

    def list_tasks(caller, status="pending"):
        return [{"task_id": "t-1", "kind": w.kind, "audience": "document_promotion:SUSTAINMENT",
                 "payload": dict(PAYLOAD)}]

    real_act = promotion.act

    def spy_act(payload, **kw):
        w.act_kwargs.append(kw)
        return real_act(payload, **kw)

    stores = promotion.PromotionStores(ledger=w.ledger, graph=_Graph())
    monkeypatch.setattr(human_tasks, "list_tasks_for", list_tasks)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: w.resolved.append((tid, kw)) or 1)
    monkeypatch.setattr(human_tasks, "_resolve_audience_actors", lambda aud: list(w.actors))
    monkeypatch.setattr(human_tasks, "task_exists", lambda tid: False)
    monkeypatch.setattr(human_tasks, "register_task", lambda **kw: w.registered.append(kw))
    monkeypatch.setattr(promotion, "act", spy_act)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    monkeypatch.setattr(gateway, "_review_mpns_for_payload", lambda subject: ["A-1", "B-2"])
    monkeypatch.setattr(
        gateway, "_review_header_for_payload",
        lambda subject: {"mfr_source": "header" if w.header.get("mfr") else None,
                         "mfr_identity": None, **w.header})
    monkeypatch.setattr(ingest_status, "update_status",
                        lambda iid, stage, *, detail=None: w.statuses.append((iid, stage, detail)))
    user = SimpleNamespace(authz_id="bob", sub="bob", email="bob@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        w.client = c
        yield w
    gateway.app.dependency_overrides.clear()


def _act(w, header=None, rows=None, decision="promoted", comment=""):
    body = {"decision": decision, "comment": comment}
    if header is not None:
        body["header_edits"] = header
    if rows is not None:
        body["row_edits"] = rows
    return w.client.post("/human_tasks/t-1/act", json=body)


def _nothing_written(w):
    assert w.act_kwargs == [] and w.ledger.records == {}
    assert w.registered == [] and w.resolved == [] and w.statuses == []


def test_arm1_a_missed_mfr_is_corrected_and_one_defect_is_filed(world):
    r = _act(world, [MFR])
    assert r.status_code == 200, r.text
    (c,) = world.act_kwargs[0]["row_edits"]
    assert c["op"] == "header_corrected" and c["field"] == "mfr"
    assert c["obtained_via"] == "steward-corrected" and c["corrected_by"] == "bob"
    assert c["extracted_value"] is None and c["corrected_value"] == "TYC"
    (stored,) = world.ledger.records.values()
    assert stored["record"]["checks"][0]["inputs"]["row_edits"] == [c]
    (reg,) = world.registered
    assert reg["kind"] == "extraction_defect"
    (e,) = reg["payload"]["edits"]
    assert e["op"] == "header_corrected" and e["field"] == "mfr" and e["corrected"] == "TYC"
    assert r.json()["row_edits"]["header"] == 1
    assert "1 header field corrected" in reg["summary"]


def test_arm2_flag_off_is_refused_and_nothing_runs(world, monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    r = _act(world, [MFR])
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "header_edits_not_for_kind" and d["enabled"] is False
    _nothing_written(world)


def test_arm3_a_grouped_review_is_refused(world):
    world.kind = "grouped_review"
    r = _act(world, [MFR])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "header_edits_not_for_kind"
    _nothing_written(world)


def test_arm4_a_reject_with_header_edits_is_refused(world):
    r = _act(world, [MFR], decision="rejected", comment="unreadable")
    assert r.status_code == 422, r.text
    _nothing_written(world)


@pytest.mark.parametrize("bad", [
    [dict(MFR, field="pub_date")],
    [dict(MFR, extra="x")],
    [dict(MFR, evidence_ref=" ")],
    [MFR, dict(MFR, value="OTHER")],
], ids=["unknown_field", "extra_key", "blank_evidence", "duplicate_field"])
def test_arm5_malformed_header_edits_are_refused(world, bad):
    r = _act(world, bad)
    assert r.status_code == 422, r.text
    _nothing_written(world)


def test_arm6_a_value_equal_to_the_extracted_one_is_not_a_correction(world):
    world.header["mfr"] = "TYC"
    r = _act(world, [dict(MFR, value="tyc")])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "header_edits_refused"
    _nothing_written(world)


def test_arm7_the_field_mapping_records_the_reviews_value(world):
    world.header.update(notice_id="PCN#1", notice_date="2021-03-16", mfr="TI")
    r = _act(world, [
        {"field": "notice_date", "value": "2021-03-17", "evidence_ref": "p1", "reason": "r"},
        {"field": "notice_id", "value": "PCN#2", "evidence_ref": "p1", "reason": "r"},
    ])
    assert r.status_code == 200, r.text
    got = {c["field"]: c for c in world.act_kwargs[0]["row_edits"]}
    assert got["notice_date"]["extracted_value"] == "2021-03-16"
    assert got["notice_id"]["extracted_value"] == "PCN#1"


def test_arm8_header_and_row_edits_together_file_one_defect(world):
    r = _act(world, [MFR], rows=ROW)
    assert r.status_code == 200, r.text
    (reg,) = world.registered
    assert {e["op"] for e in reg["payload"]["edits"]} == {"corrected", "header_corrected"}
    assert r.json()["row_edits"] == {"corrected": 1, "added": 0, "deleted": 0, "header": 1}


def test_arm9_no_holder_of_the_defect_audience_is_unroutable(world):
    world.actors = []
    r = _act(world, [MFR])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "extraction_defect_unroutable"
    _nothing_written(world)


def test_empty_header_edits_is_treated_as_none(world):
    r = _act(world, [])
    assert r.status_code == 200, r.text
    assert world.registered == [] and "row_edits" not in r.json()


# ---- unit arms on the pure core

def _item(**kw):
    return dict(MFR, **kw)


@pytest.mark.parametrize("raw", [
    "x", {"field": "mfr"}, [_item(field="pub_date")], [dict(MFR, extra=1)],
    [_item(value="")], [_item(reason=" ")], [MFR, MFR],
])
def test_validate_header_edits_refuses(raw):
    with pytest.raises(sc.EditRefusal):
        sc.validate_header_edits(raw, extracted={"mfr": "TI"})


def test_validate_header_edits_refuses_the_extracted_value():
    with pytest.raises(sc.EditRefusal):
        sc.validate_header_edits([_item(value=" ti ")], extracted={"mfr": "TI"})


def test_validate_header_edits_accepts_a_miss_and_strips():
    (it,) = sc.validate_header_edits([_item(value=" TYC ")], extracted={"mfr": None})
    assert it["value"] == "TYC" and it["extracted"] is None


def test_is_empty_counts_header_and_the_log_and_summary_carry_it():
    hdr = sc.validate_header_edits([MFR], extracted={})
    edits = sc.RowEdits(header=hdr)
    assert not edits.is_empty() and sc.RowEdits().is_empty()
    (e,) = sc.edit_log(edits)
    assert e == {"op": "header_corrected", "field": "mfr", "extracted": None, "corrected": "TYC",
                 "evidence": "p1", "reason": "text layer dropped ti", "fallback": None}
    t = sc.defect_task(notice="N", decision_id="d", pipeline_version="v", edits=edits,
                       audience="a", requested_by="x", acted_by="y")
    assert "0 corrected, 0 added, 0 deleted, 1 header field corrected." in t["summary"]
    assert "(1 steward edit(s))" in t["title"]


# ---- the equality refusal is against header.mfr, never the identity fallback (architect ruling)

FB = {"source": "notice_identity", "value": "TYC"}


def test_arm_u1_a_value_equal_to_the_fallback_fills_a_missing_field():
    (it,) = sc.validate_header_edits([_item(value="TYC")], extracted={"mfr": None},
                                     fallback={"mfr": "TYC"})
    assert it["fallback"] == FB and it["extracted"] is None


def test_arm_u2_casefold_equality_to_the_fallback_does_not_refuse():
    (it,) = sc.validate_header_edits([_item(value="tyc")], extracted={"mfr": None},
                                     fallback={"mfr": "TYC"})
    assert it["value"] == "tyc" and it["fallback"] == FB


def test_arm_u3_a_present_header_value_still_refuses_an_equal_one():
    with pytest.raises(sc.EditRefusal):
        sc.validate_header_edits([_item(value="TYC")], extracted={"mfr": "TYC"},
                                 fallback={"mfr": "TYC"})


def test_arm_u4_a_present_header_value_leaves_no_fallback():
    (it,) = sc.validate_header_edits([_item(value="TYC")], extracted={"mfr": "Acme"},
                                     fallback={"mfr": "TYC"})
    assert it["fallback"] is None


def test_arm_u5_no_fallback_keyword_is_the_old_behaviour():
    items = sc.validate_header_edits([_item(value="TYC")], extracted={"mfr": None})
    assert [i["fallback"] for i in items] == [None]


def _review(header_mfr=None, ident_mfr=None, blank=False):
    items = []
    if header_mfr is not None:
        items.append({"field_path": "header.mfr", "value": header_mfr})
    r = {"review_items": items}
    if ident_mfr is not None:
        r["notice_identity"] = {"mfr": ident_mfr}
    return r


def test_arm_s6_header_mfr_present_is_sourced_header():
    s = gateway._review_notice_summary(_review("Acme", "TYC"))
    assert (s["mfr"], s["mfr_source"], s["mfr_identity"]) == ("Acme", "header", "TYC")


def test_arm_s7_header_absent_falls_back_to_identity():
    s = gateway._review_notice_summary(_review(None, "TYC"))
    assert (s["mfr"], s["mfr_source"], s["mfr_identity"]) == ("TYC", "identity", "TYC")


def test_arm_s8_a_blank_header_mfr_is_sourced_identity():
    s = gateway._review_notice_summary(_review("  ", "TYC"))
    assert (s["mfr"], s["mfr_source"], s["mfr_identity"]) == ("TYC", "identity", "TYC")


def test_arm_s9_neither_is_none():
    s = gateway._review_notice_summary(_review(None, None))
    assert (s["mfr"], s["mfr_source"], s["mfr_identity"]) == (None, None, None)


def _tyc(world, monkeypatch, header_mfr):
    review = _review(header_mfr, "TYC")
    monkeypatch.setattr(gateway, "_review_header_for_payload",
                        lambda subject: gateway._review_notice_summary(review))
    return review


def test_arm10_tyc_shaped_act_is_accepted_with_the_fallback_as_evidence(world, monkeypatch):
    _tyc(world, monkeypatch, None)
    r = _act(world, [MFR])
    assert r.status_code == 200, r.text
    (c,) = world.act_kwargs[0]["row_edits"]
    assert c["extracted_value"] is None and c["extracted_fallback"] == FB
    (reg,) = world.registered
    (e,) = reg["payload"]["edits"]
    assert e["fallback"] == FB


def test_arm11_tyc_with_a_header_mfr_still_refuses_equality(world, monkeypatch):
    _tyc(world, monkeypatch, "TYC")
    r = _act(world, [MFR])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "header_edits_refused"


def test_arm12_the_extraction_card_shows_the_fallback_as_one(world, monkeypatch):
    review = _review(None, "TYC")
    row = {"extraction_ref": PREFIX + "m.json", "object_prefix": PREFIX}

    async def access(*a, **k):
        return row, "dropper"

    monkeypatch.setattr(gateway, "_ingest_review_access", access)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda ref: {})
    monkeypatch.setattr(gateway, "_review_json_key", lambda m, ref: PREFIX + "review.json")
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: review)
    r = world.client.get(f"/ingest/{INGEST_ID}/extraction")
    assert r.status_code == 200, r.text
    n = r.json()["notice"]
    assert n["mfr"] == "TYC" and n["mfr_source"] == "identity"
