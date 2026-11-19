"""Promoting a record starts the workflow its content kind declares (ruled 2026-11-16).

The row lives on the content kind (`on_promotion.starts`); the start mode lives in the workflow's
own yaml (`start.from`). The SDK carries neither field yet, so both are stand-ins here. The REAL
`promotion.act` runs through the gateway's act route against fake stores; the extraction reads and
the Restate ingress are doubled. The Restate double models single-use keys: a second send with a
seen key returns the first result and records no new review.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds, gateway, human_tasks, ingest_status, promotion  # noqa: E402
from src.iagent import promotion_start  # noqa: E402
from tests.viewer_double import route_viewer_tasks_through  # noqa: E402

_LAB = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "openddil-lab" / "content_kinds"

HEX = "cd" * 32
INGEST_ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
PAYLOAD = {
    "ingest_id": INGEST_ID, "object_ref": PREFIX + "NOTICE-1.pdf", "content_kind": "pcn",
    "pipeline_version": "doc-tools@61f74dc", "format_fingerprint": "fp-1", "standing": "supervised",
    "extraction_ref": PREFIX + "generated/NOTICE-1_pdf/doc-tools@61f74dc/manifest.json",
    "notice_id": "NOTICE-1", "dropped_by": {"authz_id": "alice"}}
WF = "wf-under-test"
REVIEW_KEY = PREFIX + "generated/NOTICE-1_pdf/doc-tools@61f74dc/review.json"
REVIEW_JSON = {
    "doc_id": "NOTICE-1", "needs_review": False, "source_sha256": HEX,
    "review_items": [{"field_path": "parts[0].affected_mpn", "value": "A-1", "needs_review": False}]}


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

    def attest_origin(self, ingest_id, *, owner_domain, record_id, **_kw):
        return {"ok": True}


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


class _Restate:
    """Records each start; dedupes by the ingress idempotency key AND by the composed workflow
    key, the way Restate does (a workflow key is single-use)."""

    def __init__(self):
        self.reviews = {}      # dedupe key -> first result
        self.sends = []        # every call, deduped or not
        self.raises = False

    def post(self, url, json=None, headers=None):
        self.sends.append({"url": url, "body": dict(json or {}), "headers": dict(headers or {})})
        if self.raises:
            raise ConnectionError("ingress down")
        b = json or {}
        wf_key = (f"pcn-review-{b.get('notice_id')}-{b.get('approver')}-"
                  f"{hashlib.sha1((b.get('request_key') or '').encode()).hexdigest()[:10]}")
        keys = [wf_key] + ([headers["idempotency-key"]]
                           if headers and headers.get("idempotency-key") else [])
        for k in keys:
            if k in self.reviews:
                return _Resp(self.reviews[k])
        out = {"status": "STARTED", "workflow_id": wf_key}
        for k in keys:
            self.reviews[k] = out
        return _Resp(out)

    @property
    def started(self):
        return {v["workflow_id"]: v for v in self.reviews.values()}


class _Row:
    """A stand-in registration: the real row's fields, plus `on_promotion` only when given."""

    def __init__(self, real, **extra):
        self._real, self._extra = real, extra

    def __getattr__(self, name):
        if name in self._extra:
            return self._extra[name]
        if name == "on_promotion":
            raise AttributeError(name)
        return getattr(self._real, name)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("CONTENT_KIND_OVERLAY_DIRS", str(_LAB))
    monkeypatch.setattr(content_kinds, "_REGISTRATIONS_CACHE", None)
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    w = SimpleNamespace(ledger=_Ledger(), restate=_Restate(), resolved=[], manifest_reads=[])
    real_by_kind = content_kinds.by_kind
    w.real_by_kind = real_by_kind

    def declare(row_extra):
        def by_kind(kind):
            real = real_by_kind(kind)
            return _Row(real, **row_extra) if kind == "pcn" else real
        monkeypatch.setattr(content_kinds, "by_kind", by_kind)
    w.declare = declare
    w.declare({"on_promotion": SimpleNamespace(starts=WF)})

    # the workflow definition stand-in: declares the `extraction` start mode
    import agent_fleet.restate_analyst.workflow_definition as wd
    monkeypatch.setattr(wd, "get_workflow_definition",
                        lambda wf_id: SimpleNamespace(start=SimpleNamespace(from_="extraction")))

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return w.restate.post(url, json=json, headers=headers)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    stores = promotion.PromotionStores(ledger=w.ledger, graph=_Graph())
    monkeypatch.setattr(human_tasks, "list_tasks_for", lambda caller, status="pending": [
        {"task_id": "t-1", "kind": promotion.KIND, "audience": "document_promotion:SUSTAINMENT",
         "payload": dict(PAYLOAD)}])
    route_viewer_tasks_through(monkeypatch)
    monkeypatch.setattr(human_tasks, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(human_tasks, "mark_task_resolved",
                        lambda tid, **kw: w.resolved.append((tid, kw)) or 1)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    monkeypatch.setattr(gateway, "_review_mpns_for_payload", lambda subject: ["A-1"])
    monkeypatch.setattr(gateway, "_read_extraction_manifest",
                        lambda key: w.manifest_reads.append(key) or {"manifest": key})
    monkeypatch.setattr(gateway, "_review_json_key", lambda manifest, ref: REVIEW_KEY)
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: dict(REVIEW_JSON))
    monkeypatch.setattr(gateway, "_review_on_behalf_of", lambda uri: "")
    monkeypatch.setattr(ingest_status, "get_row", lambda _id: None)
    monkeypatch.setattr(ingest_status, "update_status", lambda *a, **k: None)

    def as_(who):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: SimpleNamespace(
            authz_id=who, sub=who, email=f"{who}@x", persona=None,
            entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    w.as_ = as_
    as_("bob")
    with TestClient(gateway.app) as c:
        w.client = c
        w.act = lambda: c.post("/human_tasks/t-1/act", json={"decision": "promoted", "comment": ""},
                               headers={"authorization": "Bearer tok"})
        yield w
    gateway.app.dependency_overrides.clear()


def test_1_a_drop_by_A_promoted_by_B_opens_exactly_one_review(world):
    r = world.act()
    assert r.status_code == 200, r.text
    body = r.json()
    (rid,) = world.ledger.records.keys()
    key = f"promotion:{body['record_id']}:{WF}"
    assert rid == body["record_id"]
    assert body["review"] == {"status": "started", "workflow": WF, "request_key": key,
                              "outcome": "STARTED"}
    (sent,) = world.restate.sends
    assert sent["body"]["approver"] == "bob" and sent["body"]["request_key"] == key
    # The wire carries no `domain` key: the review start folds the domain into `audience`.
    assert sent["body"]["ingest_id"] == INGEST_ID
    assert sent["body"]["audience"].rsplit(":", 1)[1] == "SUSTAINMENT"
    assert sent["body"]["artifact_uri"] == f"s3://{gateway._ARTIFACT_BUCKET}/{REVIEW_KEY}"
    assert len(world.restate.started) == 1


def test_2_once_the_same_promoter_acting_again_starts_nothing_new(world):
    first = world.act().json()
    again = world.act()
    assert again.status_code == 200, again.text
    assert again.json()["replayed"] is True
    assert again.json()["review"]["status"] == "retried"
    assert again.json()["review"]["request_key"] == first["review"]["request_key"]
    assert len(world.restate.started) == 1          # the double holds exactly one review


def test_3_another_persons_replay_does_not_re_send_the_start(world):
    world.act()
    sends = len(world.restate.sends)
    world.as_("carol")
    r = world.act()
    assert r.status_code == 200, r.text
    assert r.json()["review"] == {
        "status": "not_restarted", "reason": "only the promoter's retry re-sends the start"}
    assert len(world.restate.sends) == sends
    assert len(world.restate.started) == 1


def test_4_a_kind_without_the_row_behaves_as_it_does_today(world, monkeypatch):
    # unpatched route: the real registration, no stand-in at all
    monkeypatch.setattr(content_kinds, "by_kind", world.real_by_kind)
    unpatched = world.act().json()
    assert "review" not in unpatched and world.restate.sends == []
    # a stand-in row that declares nothing: the same
    world.ledger.records.clear()
    world.declare({})
    r = world.act()
    assert r.status_code == 200, r.text
    assert "review" not in r.json() and world.restate.sends == []
    assert set(r.json()) == set(unpatched)


def _defs(mode="extraction", present=True, unknown=False):
    def get(wf_id):
        if unknown:
            raise LookupError(f"no definition {wf_id}")
        return SimpleNamespace(start=SimpleNamespace(from_=mode) if present else None)
    return get


def _regs(*rows):
    return [SimpleNamespace(kind=k, **extra) for k, extra in rows]


def test_5_a_misdeclared_row_is_refused_at_load():
    row = _regs(("k", {"on_promotion": SimpleNamespace(starts=WF)}))
    modes = promotion_start.MODES
    for bad in (_defs(unknown=True), _defs(present=False), _defs(mode="no-such-mode")):
        with pytest.raises(promotion_start.PromotionStartUndeclared) as e:
            promotion_start.check_declared_starts(row, get_definition=bad, modes=modes)
        assert "'k'" in str(e.value) and WF in str(e.value)
    promotion_start.check_declared_starts(row, get_definition=_defs(), modes=modes)
    promotion_start.check_declared_starts(_regs(("k", {}), ("j", {})),
                                          get_definition=_defs(unknown=True), modes=modes)


def test_5b_the_yaml_spelling_from_is_read_too():
    d = SimpleNamespace(start={"from": "extraction"})
    got = promotion_start.declared_start(
        "k", by_kind=lambda k: SimpleNamespace(on_promotion=SimpleNamespace(starts=WF)),
        get_definition=lambda wf: d)
    assert got == promotion_start.DeclaredStart(WF, "extraction")


def test_6_a_failed_start_does_not_undo_the_promotion(world):
    world.restate.raises = True
    r = world.act()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "promoted" and len(world.ledger.records) == 1
    assert body["review"] == {"status": "failed", "reason": "review_start_unreachable"}
    assert world.resolved                                  # the task still resolved
    world.restate.raises = False
    again = world.act().json()                             # acting again re-sends the start
    assert again["review"]["status"] == "retried" and len(world.restate.started) == 1


def test_7_the_sensor_and_the_bff_share_one_builder():
    sensor = importlib.import_module("iagent.defs.extraction_review_sensor")
    pure = importlib.import_module("iagent.review_payload")
    assert sensor.build_start_review_payload is pure.build_start_review_payload
