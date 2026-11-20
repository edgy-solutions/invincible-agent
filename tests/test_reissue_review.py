"""A grouped review is re-issued from its own source reference, under a DERIVED request key.

Restate workflow keys are single-use and the BFF's ingress idempotency key derives from
`(request_key, approver)`, so re-driving a spent artifact attaches to the old admission. The re-issue
carries `reissue_request_key(...)`: a new workflow key, a new task id, pointing back. Assertions are on
the REQUEST that is sent, with Restate and Postgres doubled.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.restate_analyst import review_keys, review_starter  # noqa: E402
from src.iagent import gateway, human_tasks  # noqa: E402

APPROVER = "svc:review-starter"
NOTICE = "PCN-1"
RK = "1234abcd-reviews/PCN-1/review.json"
OLD = review_keys.compose_workflow_id(NOTICE, APPROVER, RK)
NEW_ID = "pcn-review-PCN-1-svc:review-starter-newhash000"


# -- the pure derivation -----------------------------------------------------------------------

def test_reissue_request_key_is_deterministic_and_marked():
    a = review_keys.reissue_request_key(RK, OLD)
    assert a == review_keys.reissue_request_key(RK, OLD)
    assert a == f"{RK}|{review_keys.REISSUE_MARKER}:{OLD}"
    assert review_keys.reissue_request_key("", OLD) == f"reissued-from:{OLD}"


@pytest.mark.parametrize("old", ["", "   ", None])
def test_reissue_request_key_refuses_an_empty_old_id(old):
    with pytest.raises(ValueError):
        review_keys.reissue_request_key(RK, old)


def test_the_derived_key_gives_a_different_workflow_key():
    derived = review_keys.reissue_request_key(RK, OLD)
    assert review_keys.compose_workflow_id(NOTICE, APPROVER, derived) != OLD


def test_review_starter_still_exposes_the_moved_names():
    # Other tests put the flat dir on sys.path, so review_starter may hold the FLAT `review_keys`
    # module object (the container's import form); compare against whichever module it imported.
    mod = sys.modules[review_starter.compose_workflow_id.__module__]
    assert mod.__name__.split(".")[-1] == "review_keys"
    assert review_starter.compose_workflow_id is mod.compose_workflow_id
    assert review_starter.escalation_request_key is mod.escalation_request_key
    assert review_starter.ESCALATION_MARKER == review_keys.ESCALATION_MARKER


# -- the BFF, Restate and Postgres doubled -----------------------------------------------------

class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._b, self.text = status, body, ""

    def json(self):
        return self._b


class _World:
    def __init__(self, monkeypatch, *, statuses, restate_body):
        self.posts, self.supersedes, self.asked = [], [], []
        world = self

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                world.posts.append({"url": url, "json": json, "headers": headers or {}})
                return _Resp(restate_body)

        monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(gateway, "_review_on_behalf_of", lambda uri: "")

        def _statuses(tid):
            world.asked.append(tid)
            return list(statuses)
        monkeypatch.setattr(human_tasks, "task_row_statuses", _statuses)

        def _sup(task_id, superseded_by=None):
            world.supersedes.append((task_id, superseded_by))
            return 2
        monkeypatch.setattr(human_tasks, "supersede_open_task", _sup)


def _req(**kw):
    base = dict(notice_id=NOTICE, impacted_parts=[{"affected_mpn": "A"}], request_key=RK)
    base.update(kw)
    return gateway.ReviewStartRequest(**base)


def _run(req):
    user = SimpleNamespace(authz_id=APPROVER)
    return asyncio.run(gateway._start_review_core(req, current_user=user, raw_token="tok"))


def _started():
    return {"status": "STARTED", "workflow_id": NEW_ID}


def test_a_good_reissue_forwards_the_derived_key_and_supersedes(monkeypatch):
    w = _World(monkeypatch, statuses=["pending", "pending"], restate_body=_started())
    out = _run(_req(reissue_of=OLD))
    derived = review_keys.reissue_request_key(RK, OLD)
    (post,) = w.posts
    assert post["json"]["request_key"] == derived
    assert post["headers"] == {"idempotency-key": gateway._ingress_idempotency_key(derived, APPROVER)}
    assert post["headers"] != {"idempotency-key": gateway._ingress_idempotency_key(RK, APPROVER)}
    assert w.asked == ["grouped:" + OLD]
    assert w.supersedes == [("grouped:" + OLD, NEW_ID)]
    assert out["reissue"] == {"superseded_workflow_id": OLD, "superseded_task_id": "grouped:" + OLD,
                              "rows_superseded": 2}


def test_a_source_mismatch_is_422_with_no_call_and_no_supersede(monkeypatch):
    w = _World(monkeypatch, statuses=["pending"], restate_body=_started())
    with pytest.raises(HTTPException) as ei:
        _run(_req(reissue_of=OLD, request_key="a-different-artifact"))
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "reissue_source_mismatch"
    assert ei.value.detail["reissue_of"] == OLD
    assert ei.value.detail["derived"] == review_keys.compose_workflow_id(
        NOTICE, APPROVER, "a-different-artifact")
    assert w.posts == [] and w.supersedes == []


def test_a_decided_review_is_409_with_no_call(monkeypatch):
    w = _World(monkeypatch, statuses=["pending", "approved"], restate_body=_started())
    with pytest.raises(HTTPException) as ei:
        _run(_req(reissue_of=OLD))
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "reissue_of_a_resolved_review"
    assert ei.value.detail["statuses"] == ["pending", "approved"]
    assert w.posts == [] and w.supersedes == []


def test_no_old_rows_is_409(monkeypatch):
    w = _World(monkeypatch, statuses=[], restate_body=_started())
    with pytest.raises(HTTPException) as ei:
        _run(_req(reissue_of=OLD))
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "reissue_nothing_to_supersede"
    assert w.posts == []


def test_a_retry_after_partial_success_may_complete(monkeypatch):
    w = _World(monkeypatch, statuses=["superseded"], restate_body=_started())
    out = _run(_req(reissue_of=OLD))
    assert out["reissue"]["superseded_workflow_id"] == OLD and len(w.posts) == 1


def test_no_residue_supersedes_nothing(monkeypatch):
    w = _World(monkeypatch, statuses=["pending"], restate_body={"status": "NO_RESIDUE"})
    out = _run(_req(reissue_of=OLD))
    assert w.supersedes == [] and "reissue" not in out
    assert len(w.posts) == 1


def test_a_collided_workflow_id_is_500_and_supersedes_nothing(monkeypatch):
    w = _World(monkeypatch, statuses=["pending"],
               restate_body={"status": "STARTED", "workflow_id": OLD})
    with pytest.raises(HTTPException) as ei:
        _run(_req(reissue_of=OLD))
    assert ei.value.status_code == 500 and ei.value.detail["error"] == "reissue_collided"
    assert w.supersedes == []


def test_without_reissue_of_the_request_is_what_it_always_was(monkeypatch):
    w = _World(monkeypatch, statuses=["pending"], restate_body=_started())
    out = _run(_req())
    (post,) = w.posts
    assert post["json"]["request_key"] == RK
    assert "reissue_of" not in post["json"]
    assert post["headers"] == {"idempotency-key": gateway._ingress_idempotency_key(RK, APPROVER)}
    assert w.asked == [] and w.supersedes == [] and "reissue" not in out


# -- supersede_open_task: the SQL and its params -----------------------------------------------

class _Cur:
    rowcount = 3

    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        pass


def test_supersede_without_the_argument_is_the_old_statement(monkeypatch):
    log = []
    monkeypatch.setattr(human_tasks, "_pg_connect", lambda: _Conn(log))
    assert human_tasks.supersede_open_task("grouped:x") == 3
    ((sql, params),) = log
    assert sql == ("UPDATE human_task_projection SET status = 'superseded', updated_at = %s "
                   "WHERE task_id = %s AND status = 'pending'")
    assert params[1:] == ("grouped:x",) and len(params) == 2


def test_supersede_with_the_argument_records_it_on_the_payload(monkeypatch):
    log = []
    monkeypatch.setattr(human_tasks, "_pg_connect", lambda: _Conn(log))
    human_tasks.supersede_open_task("grouped:x", superseded_by="wf-new")
    ((sql, params),) = log
    assert "payload = COALESCE(payload, '{}'::jsonb) || jsonb_build_object('superseded_by', %s" in sql
    assert "WHERE task_id = %s AND status = 'pending'" in sql
    assert params[1:] == ("wf-new", "grouped:x") and len(params) == 3


# -- the Dagster op ----------------------------------------------------------------------------

def _drive_op(monkeypatch, **cfg):
    from dagster import build_op_context
    from src.iagent.defs import extraction_review_sensor as ers
    review = {"doc_id": NOTICE, "doc_type": "PCN", "needs_review": False,
              "review_items": [{"field_path": "parts[0].affected_mpn", "value": "MPN-A"},
                               {"field_path": "parts[0].replacement_mpn", "value": "MPN-B"}]}

    class _Body:
        def read(self):
            return json.dumps(review).encode()

    class _S3:
        def get_object(self, Bucket, Key):
            return {"Body": _Body(), "ETag": '"abc"'}

    posted = []
    monkeypatch.setattr(ers, "_s3_client", lambda: _S3())
    monkeypatch.setattr(ers, "mint_service_token", lambda: "tok")
    monkeypatch.setattr(ers, "_emit_record", lambda *a, **k: None)
    monkeypatch.setenv("CORTEX_BFF_URL", "http://bff")

    def _submit(payload, **k):
        posted.append(dict(payload))
        return "started", "", {"status": "STARTED"}
    monkeypatch.setattr(ers, "submit_review", _submit)
    ers.start_review_op(build_op_context(), ers.StartReviewConfig(
        review_json_url="s3://processing-artifacts/x/review.json", **cfg))
    return posted


def test_the_op_posts_reissue_of_when_set(monkeypatch):
    (p,) = _drive_op(monkeypatch, reissue_of=OLD)
    assert p["reissue_of"] == OLD


def test_the_op_posts_no_reissue_of_key_otherwise(monkeypatch):
    (p,) = _drive_op(monkeypatch)
    assert "reissue_of" not in p
