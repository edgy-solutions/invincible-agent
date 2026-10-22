"""Spec 204: a leaf change at review REPLACES the promotion task (generational ids), the stale task's
act is 409 `stale_extraction`, the re-class / re-run split follows the registry's pass lists, the
manifest-leaf backstop rescues a pdf row that runs no passes, and a title candidate's crop is page
fractions. The row/ledger fakes are the leaf test's own; the act world is the row-edits test's."""
from __future__ import annotations

import asyncio
import json
from unittest import mock

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.test_a_promotion_takes_row_edits_behind_its_flag import (  # noqa: E402,F401
    INGEST_ID as WORLD_ID, PAYLOAD, world,
)
from tests.test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it import (  # noqa: E402,F401
    ALICE, BOB, DOCTOOLS, ID, PREFIX, REF, _as, _by_kind_pdn_reruns, _leaf, _title, db,
)

G0 = f"document_promotion:{ID}"
G1 = f"document_promotion:{ID}:g1"


def _filer(db, monkeypatch, error=None):
    """A find-or-file double that answers the REAL generational id and records the generation."""
    async def file_task(ingest_id, row, **kw):
        if error is not None:
            raise error
        db.filed.append({"content_kind": row.get("content_kind"), **kw})
        return gateway._promotion_task_id(ingest_id, kw.get("generation") or 0), "FILED"

    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", file_task)


def _review(db, **kw):
    return db.add(status="review", content_kind="pcn", leaf_source="title", extraction_ref=REF,
                  detail="d", extracted_count=3, **kw)


# ---------------------------------------------------------------------------------------------
# the task ids
# ---------------------------------------------------------------------------------------------
def test_the_task_id_is_unsuffixed_at_generation_zero_and_g_n_after():
    assert gateway._promotion_task_id(ID, 0) == G0
    assert gateway._promotion_task_id(ID, 1) == G1
    assert gateway._promotion_task_id(ID, 3) == f"{G0}:g3"
    assert gateway._current_promotion_task_id({"id": ID, "review_generation": 2}) == f"{G0}:g2"
    assert gateway._current_promotion_task_id({"id": ID}) == G0


# ---------------------------------------------------------------------------------------------
# re-class at review (same passes): the new task first, then the row, then the old task superseded
# ---------------------------------------------------------------------------------------------
def test_a_reclass_at_review_files_g1_moves_the_row_and_supersedes_g0(db, monkeypatch):
    _filer(db, monkeypatch)
    _review(db)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["task_id"] == G1 and b["superseded_task_id"] == G0 and b["review_task_id"] == G1
    assert b["stage"] == "review" and b["leaf"] == "pdn" and b["leaf_source"] == "corrected"
    assert [(f["content_kind"], f["generation"]) for f in db.filed] == [("pdn", 1)]
    row = db.rows[ID]
    assert row["status"] == "review" and row["review_generation"] == 1 and row["attempt"] == 1
    assert row["content_kind"] == "pdn" and row["leaf_source"] == "corrected"
    assert db.superseded == [G0]


def test_a_reclass_whose_filing_refuses_writes_nothing_to_the_row(db, monkeypatch):
    from fastapi import HTTPException
    _filer(db, monkeypatch, error=HTTPException(status_code=503, detail={"error": "x"}))
    _review(db)
    before = db.snap()
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 503, r.text
    assert db.snap() == before and db.superseded == []


def test_same_or_different_passes_is_derived_from_the_registry_not_a_constant(db, monkeypatch):
    _filer(db, monkeypatch)
    _review(db)
    assert gateway._same_passes("pcn", "pdn") is True          # equal passes -> re-class
    monkeypatch.setattr(ck, "by_kind", _by_kind_pdn_reruns)    # other passes -> the SAME change re-runs
    assert gateway._same_passes("pcn", "pdn") is False
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "received" and db.filed == []


def test_a_rerun_at_review_goes_to_received_bumps_the_generation_and_supersedes_g0(db, monkeypatch):
    _filer(db, monkeypatch)
    monkeypatch.setattr(ck, "by_kind", _by_kind_pdn_reruns)
    _review(db)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stage"] == "received" and b["attempt"] == 2
    assert b["task_id"] is None and b["superseded_task_id"] == G0 and b["review_task_id"] is None
    row = db.rows[ID]
    assert row["status"] == "received" and row["review_generation"] == 1 and row["attempt"] == 2
    assert db.superseded == [G0] and db.filed == []
    # the extraction's return to review files the CURRENT generation's task
    assert gateway._current_promotion_task_id(row) == G1


def test_a_reclass_at_awaiting_origin_keeps_the_stage_and_files_nothing(db, monkeypatch):
    _filer(db, monkeypatch)
    db.add(status="awaiting_origin", content_kind="pcn", leaf_source="title", extraction_ref=REF)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    row = db.rows[ID]
    assert row["status"] == "awaiting_origin" and row["content_kind"] == "pdn"
    assert row["leaf_source"] == "corrected" and row["attempt"] == 1 and row["review_generation"] == 0
    assert db.filed == [] and db.superseded == []


def test_the_steward_gate_honours_the_current_generation(db, monkeypatch):
    _filer(db, monkeypatch)
    db.add(status="review", content_kind="pcn", leaf_source="title", extraction_ref=REF,
           review_generation=1)
    asked = []

    def state(task_id):
        asked.append(task_id)
        return {"open": True, "audience": "document_promotion:SUSTAINMENT"} if task_id == G1 else None

    monkeypatch.setattr(ht, "get_task_open_state", state)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, caller: True)
    assert _leaf(_as(BOB), "pdn").status_code == 200
    assert G1 in asked and G0 not in asked
    # a holder of the OLD task only is not a holder now
    db.rows[ID].update(content_kind="pcn", leaf_source="title", review_generation=1)
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: {"open": True, "audience": "document_promotion:SUSTAINMENT"}
                        if t == G0 else None)
    assert _leaf(_as(BOB), "pdn").status_code == 403


# ---------------------------------------------------------------------------------------------
# the act on a stale task
# ---------------------------------------------------------------------------------------------
def _settle_superseded(monkeypatch):
    """The caller no longer has the task pending; their own row says superseded."""
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [])
    monkeypatch.setattr(ht, "get_task_resolution", lambda t, caller_id: {
        "task_id": t, "kind": "document_promotion", "status": ht.SUPERSEDED, "decision": None,
        "acted_by": None, "acted_at": None, "audience": "document_promotion:SUSTAINMENT",
        "payload": json.dumps({**PAYLOAD, "ingest_id": WORLD_ID})})


def _row_at(gen, status="review", kind="pcn"):
    return {"id": WORLD_ID, "content_kind": kind, "status": status, "leaf_source": "corrected",
            "leaf_set_by": "bob", "review_generation": gen}


def test_acting_on_a_superseded_task_is_409_stale_extraction_naming_the_new_task(world, monkeypatch):
    g0, g1 = f"document_promotion:{WORLD_ID}", f"document_promotion:{WORLD_ID}:g1"
    _settle_superseded(monkeypatch)
    monkeypatch.setattr(ist, "get_row", lambda i: _row_at(1))
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: {"open": True, "audience": "x"} if t == g1 else None)
    r = world.client.post(f"/human_tasks/{g0}/act", json={"decision": "promoted"})
    d = r.json()["detail"]
    assert r.status_code == 409 and d["error"] == "stale_extraction", r.text
    assert d["new_task_id"] == g1 and d["task_id"] == g0 and str(d["message"]).strip()
    assert world.act_kwargs == [] and world.resolved == [] and world.ledger.records == {}


def test_acting_on_a_superseded_task_while_re_extracting_names_no_new_task(world, monkeypatch):
    g0 = f"document_promotion:{WORLD_ID}"
    _settle_superseded(monkeypatch)
    monkeypatch.setattr(ist, "get_row", lambda i: _row_at(1, status="received"))
    r = world.client.post(f"/human_tasks/{g0}/act", json={"decision": "promoted"})
    d = r.json()["detail"]
    assert r.status_code == 409 and d["error"] == "stale_extraction" and d["new_task_id"] is None
    assert d["stage"] == "received" and str(d["message"]).strip()
    assert world.act_kwargs == []


def test_acting_on_the_current_generation_task_proceeds(world, monkeypatch):
    g1 = f"document_promotion:{WORLD_ID}:g1"
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [
        {"task_id": g1, "kind": "document_promotion", "audience": "document_promotion:SUSTAINMENT",
         "payload": dict(PAYLOAD)}])
    monkeypatch.setattr(ist, "get_row", lambda i: _row_at(1))
    r = world.client.post(f"/human_tasks/{g1}/act", json={"decision": "promoted"})
    assert r.status_code == 200, r.text
    assert len(world.act_kwargs) == 1


def test_a_pending_task_that_is_not_the_current_generation_is_stale(world, monkeypatch):
    g0 = f"document_promotion:{WORLD_ID}"
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [
        {"task_id": g0, "kind": "document_promotion", "audience": "document_promotion:SUSTAINMENT",
         "payload": dict(PAYLOAD)}])
    monkeypatch.setattr(ist, "get_row", lambda i: _row_at(1))
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: None)
    r = world.client.post(f"/human_tasks/{g0}/act", json={"decision": "promoted"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "stale_extraction", r.text
    assert world.act_kwargs == []


# ---------------------------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------------------------
class _Cur:
    def __init__(self):
        self.sql = None
        self.params = None
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.sql, self.params = " ".join(sql.split()), params


def test_supersede_open_task_touches_only_pending_rows():
    cur = _Cur()
    conn = mock.MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = cur
    with mock.patch.object(ht, "_pg_connect", return_value=conn):
        assert ht.supersede_open_task(G1) == 1
    assert "status = 'superseded'" in cur.sql and "status = 'pending'" in cur.sql
    assert "decision" not in cur.sql and cur.params[1] == G1


def test_a_superseded_decision_is_not_a_resolution():
    with pytest.raises(ValueError):
        ht.mark_task_resolved(G0, caller_id="bob", decision=ht.SUPERSEDED)


# ---------------------------------------------------------------------------------------------
# the manifest-leaf backstop
# ---------------------------------------------------------------------------------------------
KEY = f"ingress-user/pdf/{'a' * 64}/generated/doc_pdf/doc-tools@61f74dc/manifest.json"


def _backstop(db, monkeypatch, manifests, s3_error=None, older=300):
    class S3:
        def list_objects_v2(self, **kw):
            if s3_error:
                raise s3_error
            return {"Contents": [{"Key": k, "LastModified": i} for i, k in enumerate(manifests)],
                    "IsTruncated": False}

        # the title relaunch rewrites the drop's sidecar first: served from the fixture's fake S3
        def get_object(self, **kw):
            return db.s3.get_object(**kw)

        def put_object(self, **kw):
            return db.s3.put_object(**kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: S3())
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda k: manifests[k])
    monkeypatch.setattr(ist, "list_leafless_extracting", lambda **kw: [db.get_row(ID)])
    return asyncio.run(gateway._ingest_leaf_backstop_tick(older))


def _block(**kw):
    return {"ingest_id": ID, "leaf": {"leaf": "PCN", "outcome": "title", **kw}}


def test_a_confident_manifest_leaf_relaunches_the_stuck_pdf_row_as_that_kind(db, monkeypatch):
    db.add(status="extracting")
    assert _backstop(db, monkeypatch, {KEY: {"ingest_id": ID,
                                             "leaf": {"leaf": "PCN", "outcome": "title"}}}) == [ID]
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["content_kind"] == "pcn" and row["leaf_source"] == "title"
    assert row["leaf_set_by"] == gateway._LEAF_BACKSTOP_ACTOR
    # the relaunch reads the drop's sidecar, so it was rewritten to the leaf BEFORE the row re-opened
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED
    side = json.loads(db.s3.objects[PREFIX + "manifest.json"])
    assert side["content_kind"] == "pcn" and side["metadata"]["content_kind"] == "pcn"
    assert db.s3.puts == [PREFIX + "manifest.json"]


def test_an_ambiguous_manifest_leaf_holds_the_row_with_mapped_candidates(db, monkeypatch):
    db.add(status="extracting")
    cands = [
        {"leaf": "PDN", "score": 0.6,
         "evidence_ref": {"page": 1, "bbox": [0.1, 0.1, 0.5, 0.2], "note": " title "}},
        {"leaf": "pcn", "score": 0.35, "evidence_ref": {"page_number": 1,                 # old form
                                                       "bbox": [300, 200, 1400, 260]}},
        {"leaf": "pcn", "score": 0.3, "evidence_ref": {"page": 1,                         # pixels
                                                      "bbox": [300, 200, 1400, 260]}},
        {"leaf": "pcn", "score": 0.3, "evidence_ref": {"page": 1,                         # no area
                                                      "bbox": [0.2, 0.2, 0.2, 0.4]}},
        {"leaf": "bogus", "score": 0.9, "evidence_ref": {"page": 1, "bbox": [0, 0, 1, 1]}},
        {"leaf": "pcn", "score": 0.2, "evidence_ref": {"page": 2, "bbox": [0, 0, 1, 1],
                                                      "note": "  "}},                      # edges ok
    ]
    m = {"ingest_id": ID,
         "leaf": {"leaf": "PCN", "outcome": "title-ambiguous", "candidates": cands}}
    assert _backstop(db, monkeypatch, {KEY: m}) == [ID]
    row = db.rows[ID]
    assert row["status"] == "awaiting_kind" and row["content_kind"] == "pdf"
    assert ist._parse_candidates(row["leaf_candidates"]) == [
        {"leaf": "pdn", "score": 0.6,
         "evidence_ref": {"page": 1, "bbox": [0.1, 0.1, 0.5, 0.2], "note": "title"}},
        {"leaf": "pcn", "score": 0.2, "evidence_ref": {"page": 2, "bbox": [0, 0, 1, 1]}}]


def test_the_candidate_mapping_never_falls_back_to_page_number():
    old = {"leaf": "pcn", "score": 0.5,
           "evidence_ref": {"page_number": 1, "bbox": [0.1, 0.1, 0.5, 0.2]}}
    assert gateway._backstop_candidates([old]) == []
    assert gateway._backstop_candidates("nope") == []


def test_a_row_that_already_has_a_leaf_is_untouched(db, monkeypatch):
    db.add(status="extracting", content_kind="pcn", leaf_source="declared")
    before = db.snap()
    assert _backstop(db, monkeypatch, {KEY: _block()}) == []
    assert db.snap() == before


def test_a_manifest_for_another_ingest_id_is_untouched(db, monkeypatch):
    db.add(status="extracting")
    before = db.snap()
    other = {"ingest_id": "sha256:" + "c" * 64, "leaf": {"leaf": "PCN", "outcome": "title"}}
    assert _backstop(db, monkeypatch, {KEY: other}) == []
    assert db.snap() == before


def test_an_s3_error_leaves_the_row_untouched_and_never_raises(db, monkeypatch):
    db.add(status="extracting")
    before = db.snap()
    assert _backstop(db, monkeypatch, {KEY: _block()}, s3_error=RuntimeError("s3 down")) == []
    assert db.snap() == before


def test_a_disabled_backstop_reads_nothing(db, monkeypatch):
    db.add(status="extracting")
    before = db.snap()
    assert _backstop(db, monkeypatch, {KEY: _block()}, older=0) == []
    assert db.snap() == before


def test_the_backstop_asks_only_for_rows_quiet_for_the_threshold(monkeypatch):
    seen = {}
    monkeypatch.setattr(ist, "list_leafless_extracting", lambda **kw: seen.update(kw) or [])
    asyncio.run(gateway._ingest_leaf_backstop_tick(123))
    assert seen["older_than_seconds"] == 123


# ---------------------------------------------------------------------------------------------
# Part F: a title candidate's crop is page fractions
# ---------------------------------------------------------------------------------------------
def _title_with(db, bbox):
    db.add(status="extracting")
    body = {"doc_type": "PCN", "doc_type_source": "defaulted",
            "candidates": [{"leaf": "pcn", "score": 0.5, "evidence_ref": {"page": 1, "bbox": bbox}}]}
    return _title(_as(DOCTOOLS), body)


@pytest.mark.parametrize("bbox", [[300, 200, 1400, 260], [0.2, 0.2, 0.2, 0.4], [0.5, 0.2, 0.4, 0.4],
                                  [0.1, 0.1, 1.2, 0.4], [-0.1, 0.1, 0.5, 0.4], [0.1, 0.1, 0.5]])
def test_a_title_candidate_with_a_pixel_or_degenerate_box_is_422(db, bbox):
    r = _title_with(db, bbox)
    assert r.status_code == 422, r.text
    assert db.rows[ID]["status"] == "extracting"


def test_the_edges_zero_and_one_are_accepted(db):
    r = _title_with(db, [0, 0, 1, 1])
    assert r.status_code == 200, r.text
    assert r.json()["leaf_candidates"][0]["evidence_ref"]["bbox"] == [0, 0, 1, 1]


def test_only_the_title_candidate_is_bounded_the_steward_evidence_ref_is_unchanged():
    gateway.EvidenceRef(page=1, bbox=[300, 200, 1400, 260])
    with pytest.raises(Exception):
        gateway.TitleEvidenceRef(page=1, bbox=[300, 200, 1400, 260])


# ---------------------------------------------------------------------------------------------
# lane review of 204: the re-class miss and the stale answer's own id
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("winner, withdrawn", [("review", False), ("received", True)])
def test_a_reclass_that_loses_the_row_withdraws_g1_only_if_the_winner_left_it_orphaned(
        db, monkeypatch, winner, withdrawn):
    """A concurrent RE-CLASS at the same generation makes g1 the row's live task: keep it. A concurrent
    RE-RUN also lands on generation 1 but at received, where no task belongs: withdraw it."""
    _filer(db, monkeypatch)
    _review(db)
    real = ist.set_leaf
    rounds = []

    def _beaten_once(*a, **k):
        if not rounds:
            db.rows[ID].update(status=winner, content_kind="pdn", leaf_source="corrected",
                               review_generation=1)
        rounds.append(k.get("expect_generation"))
        return real(*a, **k)

    monkeypatch.setattr(ist, "set_leaf", _beaten_once)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code < 500, r.text
    assert rounds[0] == 0
    assert (G1 in db.superseded) is withdrawn, db.superseded


def test_the_stale_answer_never_names_the_acted_on_task_as_its_replacement(monkeypatch):
    """The legacy kind-mismatch case: the acted-on task IS the current generation's id and open."""
    g0 = f"document_promotion:{WORLD_ID}"
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: {"open": True, "audience": "x"})
    exc = asyncio.run(gateway._stale_extraction(g0, _row_at(0, kind="pdn")))
    assert exc.status_code == 409 and exc.detail["error"] == "stale_extraction"
    assert exc.detail["new_task_id"] is None and exc.detail["task_id"] == g0
    assert str(exc.detail["message"]).strip()


# ---------------------------------------------------------------------------------------------
# spec 205: a null bbox ("stated on this page, no box we can draw"); a page is never optional
# ---------------------------------------------------------------------------------------------
def _title_ev(db, ev):
    db.add(status="extracting")
    body = {"doc_type": "PCN", "doc_type_source": "defaulted",
            "candidates": [{"leaf": "pcn", "score": 0.5, "evidence_ref": ev}]}
    return _title(_as(DOCTOOLS), body)


@pytest.mark.parametrize("ev", [{"page": 2, "bbox": None}, {"page": 2}], ids=["null", "absent"])
def test_spec_205_title_leaf_stores_a_null_or_absent_bbox_as_none(db, ev):
    r = _title_ev(db, ev)
    assert r.status_code == 200, r.text
    assert r.json()["leaf_candidates"][0]["evidence_ref"] == {"page": 2, "bbox": None}
    (stored,) = ist._parse_candidates(db.rows[ID]["leaf_candidates"])
    assert stored["evidence_ref"] == {"page": 2, "bbox": None}


@pytest.mark.parametrize("ev", [{"bbox": None}, {"bbox": [0.1, 0.1, 0.5, 0.2]}, {"page": 0, "bbox": None},
                                {"page": 1, "bbox": [300, 200, 1400, 260]}],
                         ids=["no_page", "no_page_with_box", "page0", "pixel_box"])
def test_spec_205_title_leaf_still_refuses_no_page_page0_and_a_pixel_box(db, ev):
    r = _title_ev(db, ev)
    assert r.status_code == 422, r.text
    assert db.rows[ID]["status"] == "extracting"


def test_spec_205_the_backstop_keeps_null_and_absent_bbox_and_still_drops_the_rest():
    c = lambda ev, leaf="pcn": {"leaf": leaf, "score": 0.5, "evidence_ref": ev}  # noqa: E731
    got = gateway._backstop_candidates([
        c({"page": 2, "bbox": None}), c({"page": 3}, "pdn"),
        c({"page_number": 1}), c({"page_number": 1, "bbox": None}),
        c({"page": 1, "bbox": [300, 200, 1400, 260]}), c({"bbox": None}), c({"page": 0})])
    assert [x["evidence_ref"] for x in got] == [{"page": 2, "bbox": None}, {"page": 3, "bbox": None}]


def test_spec_205_the_steward_evidence_ref_takes_a_null_or_absent_bbox_but_needs_a_page():
    w = gateway._wire_evidence_ref
    assert w({"page": 3, "bbox": None}) == {"page": 3, "bbox": None}
    assert w({"page": 3}) == {"page": 3, "bbox": None}
    assert w({"page": 3, "bbox": [1, 2, 3, 4], "note": " n "}) == {
        "page": 3, "bbox": [1, 2, 3, 4], "note": "n"}
    for bad in ({"bbox": None}, {"page": 3, "bbox": [1, 2, 3]}):
        with pytest.raises(Exception):
            w(bad)
