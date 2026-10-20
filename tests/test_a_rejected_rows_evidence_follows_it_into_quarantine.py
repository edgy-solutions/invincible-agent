"""A rejected row's evidence stays readable for audit.

`/extraction` and `/source` follow a REJECTED row into `rejected/<ingest_id>/`, and the rejection
record stores the new prefix, so nothing is guessed. Same readers as before (the gate is not
touched).

WHAT THESE DEFEND:
  * the record names where the move goes (`quarantine.from` / `.to`), and the move really lands
    under it (the join between the record and `S3Quarantine`).
  * `PgDecisionLedger.record_for` reads it back; a store fault raises.
  * the two readers relocate through the record for a REJECTED row only; a record without the
    field is 404 `rejected_evidence_unlocated` (never a guessed prefix); a ledger fault is 503.
"""
from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion, promotion_stores  # noqa: E402

HEX = "5b15f205fc605c240c9ee37215d862bd977940eb26c74d73b739c538afa97091"
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
GEN = PREFIX + "generated/PCN26-119_pdf/doc-tools@61f74dc/"
REF = GEN + "manifest.json"
REVIEW_KEY = GEN + "review.json"
SRC_KEY = PREFIX + "PCN26-119.pdf"
TO = f"rejected/{ID}/"
PDF_BYTES = b"%PDF-1.7\n" + bytes(range(256)) * 20
DROPPER = "alice@example.com"

MANIFEST = {"doc_id": "PCN26-119", "filename": "PCN26-119.pdf", "source_key": SRC_KEY,
            "pipeline_version": "doc-tools@61f74dc", "ingest_id": ID}
REVIEW = {"doc_id": "PCN26-119", "doc_id_raw": "PCN #26-119", "pages": [],
          "review_items": [{"field_path": "parts[0].affected_mpn", "value": "ABC123",
                            "source_snippet": "s", "page_number": 2,
                            "bboxes": [[1.0, 2.0, 3.0, 4.0]], "page_dims": [612, 792],
                            "match_method": "text_layer_cell", "match_confidence": 0.9,
                            "needs_review": False, "review_reason": None}]}
SUBJECT = promotion.PromotionSubject(
    ingest_id=ID, object_ref=SRC_KEY, content_kind="pcn", pipeline_version="doc-tools@61f74dc",
    format_fingerprint="pdf:pcn:v1", standing="supervised", extraction_ref=REF, notice_id="n")
GOVERNING = {"ruleset_ref": "task_kind:document_promotion@x", "trust_table_ref": "trust@t"}


def _record(decision="rejected"):
    return promotion.build_record(SUBJECT, decision=decision, acted_by="steward", audience="a",
                                  comment="", governing=GOVERNING, era="commissioning")


# -- the record ----------------------------------------------------------------------------------

def test_a_rejection_record_names_where_the_objects_go():
    assert _record()["quarantine"] == {"from": PREFIX, "to": TO}


def test_a_promoted_record_carries_no_quarantine_key():
    assert "quarantine" not in _record("promoted")


class _S3Move:
    def __init__(self, keys):
        self.objects = {k: b"x" for k in keys}

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)],
                "IsTruncated": False}

    def copy_object(self, *, Bucket, Key, CopySource):
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, *, Bucket, Key):
        del self.objects[Key]


def test_the_move_lands_under_the_prefix_the_record_names():
    s3 = _S3Move([SRC_KEY, PREFIX + "manifest.json", REF])
    moved = promotion_stores.S3Quarantine(lambda: s3, "b").quarantine(ID, SRC_KEY)
    to = _record()["quarantine"]["to"]
    assert moved and all(k.startswith(to) for k in moved), (moved, to)


# -- the ledger read -----------------------------------------------------------------------------

class _Cur:
    def __init__(self, row):
        self.row, self.executed = row, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self.cur


def _ledger(row):
    cur = _Cur(row)
    return promotion_stores.PgDecisionLedger(connect=lambda: _Conn(cur)), cur


@pytest.mark.parametrize("row,want", [
    ((json.dumps({"a": 1}),), {"a": 1}),
    ((json.dumps({"a": 1}).encode(),), {"a": 1}),
    (({"a": 1},), {"a": 1}),
    (None, None),
])
def test_record_for_returns_the_stored_record_or_none(row, want):
    led, cur = _ledger(row)
    assert led.record_for(ID) == want
    sql, params = cur.executed[0]
    assert "FROM document_decision_record WHERE ingest_id = %s" in sql and params == (ID,)


def test_record_for_RAISES_on_a_store_fault():
    def boom():
        raise RuntimeError("pg down")
    with pytest.raises(RuntimeError):
        promotion_stores.PgDecisionLedger(connect=boom).record_for(ID)


# -- the readers ---------------------------------------------------------------------------------

class _Body:
    def __init__(self, data):
        self._d, self._p = data, 0

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._d)
        out = self._d[self._p:self._p + n]
        self._p += n
        return out

    def close(self):
        pass


class FakeS3:
    def __init__(self, objects):
        self.objects, self.calls = dict(objects), []

    def get_object(self, Bucket, Key):
        self.calls.append(Key)
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": _Body(self.objects[Key])}


def _objects(base):
    return {base + REF[len(PREFIX):]: json.dumps(MANIFEST).encode(),
            base + REVIEW_KEY[len(PREFIX):]: json.dumps(REVIEW).encode(),
            base + "manifest.json": json.dumps({"object_ref": SRC_KEY}).encode(),
            base + SRC_KEY[len(PREFIX):]: PDF_BYTES}


def _row(**over):
    r = {"id": ID, "status": "rejected", "kind": "pdf", "content_kind": "pcn", "attempt": 1,
         "object_prefix": PREFIX, "extraction_ref": REF, "submitted_by": DROPPER,
         "on_behalf_of": None, "notice_id": "n"}
    r.update(over)
    return r


class Ledger:
    """Stands in for PgDecisionLedger; `rec` is what record_for answers, or raises when an Exception."""
    calls = 0
    rec = None

    def __init__(self, *a, **k):
        pass

    def record_for(self, ingest_id):
        type(self).calls += 1
        if isinstance(type(self).rec, Exception):
            raise type(self).rec
        return type(self).rec


def _rig(monkeypatch, *, row, objects, rec):
    fake = FakeS3(objects)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: None)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: False)
    Ledger.calls, Ledger.rec = 0, rec
    monkeypatch.setattr(promotion_stores, "PgDecisionLedger", Ledger)
    user = type("U", (), {"authz_id": DROPPER, "id": DROPPER, "sub": DROPPER, "email": DROPPER,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    gateway.app.dependency_overrides.clear()


def _get(path):
    with TestClient(gateway.app) as c:
        return c.get(path)


def _rejected_rec(**over):
    r = {"outcome": "rejected", "quarantine": {"from": PREFIX, "to": TO}}
    r.update(over)
    return r


def _err(r, code, error):
    assert r.status_code == code, (r.status_code, r.text[:200])
    assert r.json()["detail"]["error"] == error, r.text[:200]


def test_extraction_of_a_rejected_row_is_read_from_quarantine(monkeypatch):
    fake = _rig(monkeypatch, row=_row(), objects=_objects(TO), rec=_record())
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["rows"] and j["relocated_to"] == TO and j["review_ref"] == REVIEW_KEY
    assert fake.calls and all(k.startswith(TO) for k in fake.calls), fake.calls


def test_source_of_a_rejected_row_is_the_relocated_bytes(monkeypatch):
    fake = _rig(monkeypatch, row=_row(), objects=_objects(TO), rec=_record())
    r = _get(f"/ingest/{ID}/source")
    assert r.status_code == 200 and r.content == PDF_BYTES
    assert 'filename="PCN26-119.pdf"' in r.headers["content-disposition"]
    assert all(k.startswith(TO) for k in fake.calls), fake.calls


@pytest.mark.parametrize("path", ["extraction", "source"])
@pytest.mark.parametrize("rec", [
    {"outcome": "rejected"}, {"outcome": "rejected", "quarantine": {"from": PREFIX}},
    {"outcome": "promoted", "quarantine": {"from": PREFIX, "to": TO}}, None])
def test_a_record_that_does_not_say_where_is_404_and_nothing_is_guessed(monkeypatch, path, rec):
    # The objects ARE at the conventional destination: a guess would find them and answer 200.
    fake = _rig(monkeypatch, row=_row(), objects=_objects(TO), rec=rec)
    _err(_get(f"/ingest/{ID}/{path}"), 404, "rejected_evidence_unlocated")
    assert fake.calls == []


@pytest.mark.parametrize("path", ["extraction", "source"])
def test_a_ledger_that_raises_is_503(monkeypatch, path):
    _rig(monkeypatch, row=_row(), objects=_objects(TO), rec=RuntimeError("pg down"))
    _err(_get(f"/ingest/{ID}/{path}"), 503, "decision_ledger_unreachable")


@pytest.mark.parametrize("path", ["extraction", "source"])
def test_a_review_rejected_row_moves_nothing_and_never_asks_the_ledger(monkeypatch, path):
    _rig(monkeypatch, row=_row(status="review_rejected"), objects=_objects(PREFIX),
         rec=RuntimeError("must not be called"))
    r = _get(f"/ingest/{ID}/{path}")
    assert r.status_code == 200, r.text
    assert Ledger.calls == 0
    if path == "extraction":
        assert r.json()["relocated_to"] is None


def test_a_non_rejected_row_never_asks_the_ledger_and_relocates_nowhere(monkeypatch):
    _rig(monkeypatch, row=_row(status="review"), objects=_objects(PREFIX),
         rec=RuntimeError("must not be called"))
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200 and r.json()["relocated_to"] is None
    assert Ledger.calls == 0


def test_a_from_that_does_not_prefix_the_extraction_ref_is_unbound(monkeypatch):
    other = f"ingress-user/pdf/{'cd' * 32}/"
    _rig(monkeypatch, row=_row(), objects=_objects(TO),
         rec=_rejected_rec(quarantine={"from": other, "to": TO}))
    _err(_get(f"/ingest/{ID}/extraction"), 422, "extraction_unbound")
