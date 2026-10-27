"""Seal the published ingest-v1 API surface: no shape change without a version bump.

Seals: (1) the set of `ingest-v1` tagged routes in gateway.app is exactly V1_ROUTES and only the
preview route carries x-stability; (2) docs/api/ingest-v1.openapi.json is the generator's output
byte for byte; (3) docs/api/ingest-v1.shapes.lock holds the current shape hash for the current
version and every locked version has a CHANGELOG heading; (4) the annotation stripper keeps NAMES
(a field called "title") and the hash moves on shape changes only; (5) the lock writer refuses to
touch a row whose sha differs.

Run: uv run pytest tests/test_ingest_v1_is_stable.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent.ingest_api import (  # noqa: E402
    INGEST_API_VERSION, INGEST_V1_TAG, PREVIEW_ROUTES, V1_ROUTES,
)

_spec = importlib.util.spec_from_file_location(
    "_gen_ingest_openapi", ROOT / "scripts" / "generate_ingest_openapi.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)

PREVIEW_PATH, PREVIEW_METHOD = "/ingest/{ingest_id}/empty", "post"


@pytest.fixture(scope="module")
def full():
    return gateway.app.openapi()


@pytest.fixture(scope="module")
def doc(full):
    return gen.filter_openapi(full, INGEST_V1_TAG, INGEST_API_VERSION)


def test_tagged_routes_are_exactly_v1_routes():
    tagged = {
        (m, r.path)
        for r in gateway.app.routes
        if isinstance(r, APIRoute) and INGEST_V1_TAG in (r.tags or [])
        for m in r.methods
    }
    assert tagged == set(V1_ROUTES), (tagged ^ set(V1_ROUTES))


def test_v1_paths_and_preview_subset():
    assert len(V1_ROUTES) == 13
    assert all(p.startswith(("/ingest", "/human_tasks", "/me")) for _, p in V1_ROUTES)
    assert PREVIEW_ROUTES <= V1_ROUTES


def test_exactly_preview_operations_carry_x_stability(full):
    marked = {
        (m.upper(), p)
        for p, item in full["paths"].items()
        for m, op in item.items()
        if isinstance(op, dict) and op.get("x-stability") == "preview"
    }
    assert marked == set(PREVIEW_ROUTES)


def test_committed_document_matches_generator(doc):
    committed = gen._read(gen.DOC_PATH)
    assert committed == gen.serialise(doc), (
        "docs/api/ingest-v1.openapi.json is stale: run scripts/generate_ingest_openapi.py")


def test_lock_has_current_shape_hash(doc):
    rows = gen.read_lock(gen._read(gen.LOCK_PATH))
    assert INGEST_API_VERSION in rows, "no lock row for the current version"
    assert rows[INGEST_API_VERSION] == gen.shape_hash(doc)


def test_every_locked_version_has_changelog_heading():
    rows = gen.read_lock(gen._read(gen.LOCK_PATH))
    assert rows
    headings = {ln[3:].split()[0] for ln in
                (ROOT / "docs" / "api" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
                if ln.startswith("## ") and ln[3:].strip()}
    assert set(rows) <= headings, set(rows) - headings


def test_stripper_keeps_names_and_hash_ignores_wording():
    def mk(desc="a", typ="string"):
        return {"openapi": "3.1.0", "paths": {"/x": {"get": {
            "tags": [INGEST_V1_TAG], "summary": desc, "description": desc,
            "responses": {"200": {"description": desc, "content": {"application/json": {
                "schema": {"type": "object", "title": desc, "properties": {
                    "title": {"type": typ, "description": desc},
                    "description": {"type": "string"}}}}}}}}}}}
    stripped = gen.strip_annotations(mk())
    props = stripped["paths"]["/x"]["get"]["responses"]["200"]["content"][
        "application/json"]["schema"]["properties"]
    assert set(props) == {"title", "description"}
    assert "description" not in props["title"]
    assert gen.shape_hash(mk("a")) == gen.shape_hash(mk("b"))
    assert gen.shape_hash(mk(typ="string")) != gen.shape_hash(mk(typ="integer"))


def _first_schema_type_holder(node):
    """Find a dict with a 'type' key inside a requestBody of a stable operation."""
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            return node
        for v in node.values():
            r = _first_schema_type_holder(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _first_schema_type_holder(v)
            if r:
                return r
    return None


def test_hash_positive_controls(doc):
    base = gen.shape_hash(doc)

    d = copy.deepcopy(doc)
    holder = _first_schema_type_holder(d["paths"]["/ingest/{ingest_id}/status"]["get"]["parameters"])
    assert holder is not None
    holder["type"] = "__changed__"
    assert gen.shape_hash(d) != base

    d = copy.deepcopy(doc)
    holder = _first_schema_type_holder(d["paths"][PREVIEW_PATH][PREVIEW_METHOD]["parameters"])
    assert holder is not None
    holder["type"] = "__changed__"
    assert gen.shape_hash(d) == base

    d = copy.deepcopy(doc)
    del d["paths"]["/ingest/mine"]["get"]
    assert gen.shape_hash(d) != base


def test_lock_writer_refuses_changed_shape_and_leaves_file(tmp_path):
    lock = tmp_path / "x.lock"
    text = gen.LOCK_HEADER + f"{INGEST_API_VERSION} {'0' * 64}\n"
    lock.write_bytes(text.encode())
    before = lock.read_bytes()
    action, new = gen.plan_lock(lock.read_text(), INGEST_API_VERSION, "f" * 64)
    assert action == "refuse" and new is None
    assert lock.read_bytes() == before
    assert gen.plan_lock(text, INGEST_API_VERSION, "0" * 64)[0] == "noop"
    assert gen.plan_lock(text, "9.9.9", "f" * 64)[0] == "append"


# ---- the 200 bodies: declared, and enforced on every real response a test drives ----------------

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import ingest_api  # noqa: E402
from src.iagent.ingest_api import BINARY_ROUTES, RESPONSE_MODELS, check_v1_response  # noqa: E402

SOURCE = ("GET", "/ingest/{ingest_id}/source")


def test_every_v1_route_has_a_response_model_or_is_binary():
    assert set(RESPONSE_MODELS) | set(BINARY_ROUTES) == set(V1_ROUTES)
    assert not (set(RESPONSE_MODELS) & set(BINARY_ROUTES))


def test_every_json_v1_operation_declares_its_200_and_source_lists_its_media(full):
    for method, path in sorted(V1_ROUTES):
        ok = full["paths"][path][method.lower()]["responses"]["200"]
        if (method, path) in BINARY_ROUTES:
            # FastAPI also lists application/json (an empty schema) for a route with no response_class
            assert {"application/pdf", "application/xml",
                    "application/octet-stream"} <= set(ok["content"]), path
        else:
            schema = ok["content"]["application/json"]["schema"]
            assert "$ref" in schema or "anyOf" in schema, (method, path, schema)


def _status_body(**over):
    body = {"ingest_id": "i1", "stage": "received", "detail": None, "duplicate": None,
            "kind": "pdf", "sha256": "ab", "created_at": 1, "updated_at": 2,
            "dropped_by": {"authz_id": "alice"}, "origin_suggestion": None, "case_id": None,
            "content_kind": "pcn", "failure": None, "attempt": 1, "notice_id": None,
            "artifacts": [], "review_task_id": None, "review_shape": None, "account": None}
    body.update(over)
    return body


STATUS = ("GET", "/ingest/{ingest_id}/status")


def _check(body, *, key=STATUS, status=200, ctype="application/json", tags=(INGEST_V1_TAG,)):
    return check_v1_response(key[0], key[1], status, ctype, body, tags=tags)


def test_check_accepts_a_valid_status_body_with_and_without_the_leaf_keys():
    assert _check(_status_body()) is True
    assert _check(_status_body(leaf="pcn", leaf_source="title", corrected_by=None,
                               leaf_candidates=None, hold_reason=None)) is True


def test_check_refuses_an_extra_key_naming_it():
    with pytest.raises(AssertionError, match="bogus"):
        _check(_status_body(bogus=1))


def test_check_refuses_a_missing_required_key_naming_it():
    body = _status_body()
    del body["attempt"]
    with pytest.raises(AssertionError, match="attempt"):
        _check(body)


@pytest.mark.parametrize("field", ["kind", "sha256", "created_at", "updated_at"])
def test_check_refuses_a_null_in_a_field_the_row_always_has(field):
    # 208: NOT NULL columns; a null here is a producer defect, never "unknown"
    with pytest.raises(AssertionError, match=field):
        _check(_status_body(**{field: None}))


def test_check_accepts_an_empty_review_with_its_account_and_a_defect():
    acct = {"n_tables": 2, "grid_no_parts_col": 2, "grid_rows_emitted": 0,
            "review_reasons": ["no_parts_found"], "why": "no_parts_column"}
    assert _check(_status_body(stage="review", review_task_id="document_empty_confirm:i1:a1",
                               review_shape="empty", account=acct,
                               extraction_defect={"task_id": "d1", "edits": 0})) is True
    with pytest.raises(AssertionError, match="why"):
        _check(_status_body(review_shape="empty", account={**acct, "why": "guess"}))


def test_check_refuses_a_value_outside_a_closed_vocabulary():
    with pytest.raises(AssertionError, match="leaf"):
        _check(_status_body(leaf="xyz"))


def test_check_skips_what_is_not_a_v1_json_200():
    junk = {"bogus": 1}
    assert _check(junk, status=404) is False
    assert _check(junk, ctype="text/plain") is False
    assert _check(junk, tags=("other",)) is False
    assert _check(junk, key=SOURCE) is False


def _tiny_app(body):
    app = FastAPI()

    @app.get("/ingest/mine", tags=[INGEST_V1_TAG])
    def mine():
        return body

    @app.get("/elsewhere")
    def elsewhere():
        return {"bogus": 1}

    return app


def test_the_hook_fires_on_a_nonconforming_200_through_a_test_client():
    client = TestClient(_tiny_app({"items": [], "next": None, "bogus": 1}))
    with pytest.raises(AssertionError, match="bogus"):
        client.get("/ingest/mine")
    assert client.get("/elsewhere").json() == {"bogus": 1}   # an untagged route is not checked


def test_the_hook_lets_a_conforming_200_through():
    client = TestClient(_tiny_app({"items": [_status_body()], "next": None}))
    assert client.get("/ingest/mine").status_code == 200


def test_the_marker_refuses_a_blank_reason():
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            ingest_api.unconformant_reason(bad)
    assert ingest_api.unconformant_reason(" because ") == "because"


def test_me_routes_answer_in_their_declared_shape(monkeypatch):
    """Nothing else drives /me/entitlements or /me/human_tasks through a client."""
    import datetime

    from src.iagent import human_tasks
    from src.iagent.auth import User, get_current_user

    user = User(id="sub-1", email="a@x.example", authz_id="a", entitlement_source="none")
    row = {"id": 1, "kind": "access_request", "task_id": "t1", "workflow_id": None,
           "audience": "x", "status": "pending", "title": "t", "summary": "s",
           "requested_by": "r", "subject_ref": None, "payload": {"k": 1},
           "created_at": datetime.datetime(2026, 1, 1), "workflow_service": None,
           "promise_name": None, "case_id": None}
    monkeypatch.setattr(human_tasks, "list_tasks_for", lambda caller_id, **kw: [dict(row)])
    gateway.app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(gateway.app)
        ent = client.get("/me/entitlements")
        tasks = client.get("/me/human_tasks")
    finally:
        gateway.app.dependency_overrides.pop(get_current_user, None)
    assert ent.status_code == 200 and tasks.status_code == 200
    assert tasks.json()["tasks"][0]["declaration"]["kind"] == "access_request"
