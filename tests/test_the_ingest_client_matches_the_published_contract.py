"""samples/ingest_client.py cannot drift from the published ingest-v1 contract.

The client is what the work team copies, so it is held to the committed OpenAPI file two ways.

STATIC ARMS (read the client, read `docs/api/ingest-v1.openapi.json`):
  1. every `ROUTES` entry is a (path, method) in the OpenAPI document (`GET /me/human_tasks` may
     live only in the BFF document; the assertion names the document that carried it);
  2. every key in `READS[name]` is a property of that route's 200 response schema (`$ref`
     resolved; for a union, a key in ANY member counts);
  3. (AST) no string constant starting with `/` (other than a bare "/") exists outside the `ROUTES` assignment, and no
     `.get/.post/.put/.delete/.patch/.request` call is made except inside `call` and `session`
     (`.get` on `os.environ` is allowed). This is what stops a URL bypassing ROUTES;
  4. (AST) in the functions that handle a response body (`drop, poll, extraction, review_task,
     promote, reject, ledger_entry`) every subscript with a string-constant key sits inside a call
     to `field`. Any response key those functions read therefore goes through the `READS` check.
  5. CONTROL: a deliberately wrong route and a wrong key are refused by the SAME checker
     functions arms 1 and 2 use, so the checkers are shown able to fail.

BEHAVIOURAL ARM: the client's functions run against the REAL `src.iagent.gateway.app` through
TestClient. The conftest hook checks every 200 against its v1 response model. The world fakes
only the stores and seams, one per route family:
  * drop        -- object store (`_build_s3_client`), `ingest_status.find_primary_by_sha` and
                   `record_received`, the graph node write, and the content-kind registry;
  * status      -- `ingest_status.get_status_for`, and the human-task store for the review ids;
  * extraction  -- `ingest_status.get_row` and the object store holding manifest and review.json;
  * act         -- `human_tasks` store functions and `promotion.PromotionStores` (in-memory
                   ledger and graph). `promotion.act` itself is real.
The row moves received -> extracting -> review inside the fake `sleep`, so `poll` is driven
without waiting.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "samples" / "ingest_client.py"
INGEST_DOC = ROOT / "docs" / "api" / "ingest-v1.openapi.json"
BFF_DOC = ROOT / "docs" / "api" / "cortex-bff.openapi.json"
BODY_FUNCTIONS = ("drop", "poll", "extraction", "review_task", "promote", "reject", "ledger_entry")
CALL_METHODS = {"get", "post", "put", "delete", "patch", "request"}


def load_client(monkeypatch):
    """Load the client by path. The module is registered only through monkeypatch.setitem."""
    import sys  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("_ingest_client_under_test", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


# ── the checkers (shared by the real arms and the control) ─────────────────────────────────────

def _docs():
    return [("ingest-v1.openapi.json", json.loads(INGEST_DOC.read_text(encoding="utf-8"))),
            ("cortex-bff.openapi.json", json.loads(BFF_DOC.read_text(encoding="utf-8")))]


def route_problem(method: str, path: str) -> str | None:
    """None if (method, path) is in the ingest document, or else in the BFF document; else why not."""
    for doc_name, doc in _docs():
        if method.lower() in doc["paths"].get(path, {}):
            return None
    return f"{method} {path} is in neither ingest-v1.openapi.json nor cortex-bff.openapi.json"


def route_carrier(method: str, path: str) -> str:
    for doc_name, doc in _docs():
        if method.lower() in doc["paths"].get(path, {}):
            return doc_name
    return "none"


def _resolve(doc, schema):
    while "$ref" in schema:
        schema = doc["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def _properties(doc, schema) -> set[str]:
    schema = _resolve(doc, schema)
    out = set(schema.get("properties", {}))
    for union in ("anyOf", "oneOf"):
        for member in schema.get(union, []):
            out |= _properties(doc, member)
    return out


def key_problem(name: str, method: str, path: str, key: str) -> str | None:
    """None if `key` is a property of the route's 200 response (in whichever document has the route)."""
    for doc_name, doc in _docs():
        op = doc["paths"].get(path, {}).get(method.lower())
        if op is None:
            continue
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        if key in _properties(doc, schema):
            return None
        return f"route {name!r} ({method} {path}): {key!r} is not in its 200 response ({doc_name})"
    return f"route {name!r}: {method} {path} has no document to read keys from"


# ── static arms ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    return load_client(monkeypatch)


def test_the_routes_are_the_names_the_client_documents(client):
    assert set(client.ROUTES) == {"drop", "status", "mine", "extraction", "tasks", "act"}
    assert set(client.READS) == set(client.ROUTES)


def test_arm1_every_route_is_in_the_published_contract(client):
    for name, (method, path) in client.ROUTES.items():
        problem = route_problem(method, path)
        assert problem is None, f"{name}: {problem}"
    # the one route that may live only in the BFF document says so
    assert route_carrier(*client.ROUTES["tasks"]) in ("ingest-v1.openapi.json", "cortex-bff.openapi.json")


def test_arm2_every_key_the_client_reads_is_in_that_routes_200_response(client):
    for name, keys in client.READS.items():
        method, path = client.ROUTES[name]
        for key in sorted(keys):
            problem = key_problem(name, method, path, key)
            assert problem is None, problem


def _parse():
    return ast.parse(CLIENT.read_text(encoding="utf-8"))


def _functions(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def path_leaks(tree) -> list[str]:
    """String constants starting with `/` outside the ROUTES assignment, and request-method calls
    outside `call` and `session`."""
    routes_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in targets):
                routes_nodes |= {id(n) for n in ast.walk(node)}
    exempt = set()
    for name, fn in _functions(tree).items():
        if name in ("call", "session"):
            exempt |= {id(n) for n in ast.walk(fn)}
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith("/") and len(node.value) > 1
                and id(node) not in routes_nodes):
            found.append(f"line {node.lineno}: string {node.value!r} starts with '/' outside ROUTES")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in CALL_METHODS and id(node) not in exempt):
            recv = ast.unparse(node.func.value)
            if node.func.attr == "get" and recv == "os.environ":
                continue
            found.append(f"line {node.lineno}: .{node.func.attr}() called outside call()/session()")
    return found


def subscript_leaks(tree) -> list[str]:
    """String-key subscripts in the body-handling functions that are not inside a field() call."""
    found = []
    for name, fn in _functions(tree).items():
        if name not in BODY_FUNCTIONS:
            continue
        inside_field = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "field":
                inside_field |= {id(m) for m in ast.walk(n)}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                    and isinstance(n.slice.value, str) and id(n) not in inside_field):
                found.append(f"{name}, line {n.lineno}: [{n.slice.value!r}] is not read through field()")
    return found


def test_arm3_no_url_bypasses_routes():
    assert path_leaks(_parse()) == []


def test_arm4_no_response_key_is_read_around_field():
    assert subscript_leaks(_parse()) == []


def test_arm5_control_the_checkers_can_refuse():
    """The wrong route and the wrong key go through the same functions as arms 1 and 2; the AST
    checkers are fed source that bypasses ROUTES and field()."""
    assert route_problem("GET", "/ingest/{ingest_id}/ledger") is not None
    assert key_problem("status", "GET", "/ingest/{ingest_id}/status", "bogus") is not None
    assert route_problem("GET", "/ingest/{ingest_id}/status") is None
    assert key_problem("status", "GET", "/ingest/{ingest_id}/status", "stage") is None
    bad = ast.parse('ROUTES = {"a": ("GET", "/ok")}\n'
                    'def poll(api, base):\n    return api.get(base + "/ingest/x/status")["stage"]\n')
    assert path_leaks(bad) and subscript_leaks(bad)


# ── behavioural arm: the client against the real gateway app ───────────────────────────────────

class Adapter:
    """The `.get/.post` surface the client expects (`request`, which `call` uses), with `base`
    stripped, forwarding to the TestClient. Every call goes through the conftest conformance hook."""

    BASE = "http://testserver"

    def __init__(self, tc):
        self.tc = tc

    def request(self, method, url, **kw):
        assert url.startswith(self.BASE), url
        kw.pop("timeout", None)
        return self.tc.request(method, url[len(self.BASE):], **kw)


class S3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"] if isinstance(kw["Body"], bytes) else kw["Body"].encode()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        data = self.objects[Key]
        return {"Body": SimpleNamespace(read=lambda n=-1: data, close=lambda: None)}


class Ledger:
    def __init__(self):
        self.records = {}

    def append(self, record, *, acted_by, acted_at):
        rid = record["record_id"]
        if rid in self.records:
            return {"ok": False, "reason": "immutable_conflict", "existing": self.records[rid]}
        self.records[rid] = {"decision": record["outcome"], "acted_by": acted_by,
                             "acted_at": acted_at, "record": record}
        return {"ok": True}


class Graph:
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


WHO = "alice@example.com"
PDF_BYTES = b"%PDF-1.4 a notice for the client test"
REVIEW = {
    "doc_id": "PCN26-119", "doc_id_raw": "PCN #26-119", "notice_identity": {"mfr": "Acme"},
    "pages": [], "stats": {"text_layer_parts": 1},
    "review_items": [
        {"field_path": "parts[0].affected_mpn", "value": "ABC123", "source_snippet": "ABC123",
         "region": "table", "page_number": 2, "bboxes": [[10.0, 20.0, 30.0, 40.0]],
         "page_dims": [612, 792], "match_method": "text_layer_cell", "match_confidence": 0.9,
         "needs_review": False, "review_reason": None, "approval_state": "pending"}]}


@pytest.fixture
def world(monkeypatch):
    from src.iagent import content_kinds as ck  # noqa: PLC0415
    from src.iagent import gateway  # noqa: PLC0415
    from src.iagent import human_tasks as ht  # noqa: PLC0415
    from src.iagent import ingest_status as ist  # noqa: PLC0415
    from src.iagent import promotion  # noqa: PLC0415

    w = SimpleNamespace(row=None, stages=[], s3=S3(), ledger=Ledger(), resolved=[], gateway=gateway)
    reg = SimpleNamespace(kind="notice", branch="document", domain="SUSTAINMENT",
                          seeds_workflow=None, identity_field=None)
    monkeypatch.setattr(ck, "by_kind", lambda k: reg)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: w.s3)
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(gateway, "_audit_ingest_access", lambda *a, **k: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)

    def record_received(**kw):
        w.row = {"id": kw["ingest_id"], "status": "received", "kind": kw["kind"],
                 "content_kind": kw["content_kind"], "sha256": kw["sha256"], "created_at": 1,
                 "updated_at": 1, "submitted_by": kw["submitted_by"], "on_behalf_of": None,
                 "object_prefix": kw["object_prefix"], "extraction_ref": None, "attempt": 1,
                 "review_generation": 0, "notice_id": None}
        return w.row

    monkeypatch.setattr(ist, "record_received", record_received)
    monkeypatch.setattr(ist, "get_row", lambda i: w.row if w.row and w.row["id"] == i else None)
    monkeypatch.setattr(ist, "get_status_for",
                        lambda i, *, caller_id: w.row if w.row and w.row["id"] == i
                        and caller_id == w.row["submitted_by"] else None)
    monkeypatch.setattr(ist, "update_status", lambda iid, stage, **kw: w.stages.append(stage))
    monkeypatch.setattr(ht, "get_open_task_payload", lambda t: None)
    monkeypatch.setattr(ht, "latest_task_for_subject", lambda *a, **k: None)
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: None)
    monkeypatch.setattr(ht, "task_exists", lambda t: False)
    monkeypatch.setattr(ht, "register_task", lambda **kw: {})
    monkeypatch.setattr(ht, "check_can_act", lambda a, c: True)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda a, c: True)
    monkeypatch.setattr(ht, "_resolve_audience_actors", lambda aud: [WHO])
    monkeypatch.setattr(ht, "mark_task_resolved", lambda tid, **kw: w.resolved.append(tid) or 1)
    monkeypatch.setattr(ht, "get_task_resolution", lambda *a, **k: None)

    def list_tasks(caller, status="pending"):
        if w.row is None or w.row["status"] != "review":
            return []
        tid = gateway._promotion_task_id(w.row["id"], 0)
        return [{"task_id": tid, "kind": promotion.KIND,
                 "audience": "document_promotion:SUSTAINMENT",
                 "payload": {"ingest_id": w.row["id"], "object_ref": w.row["object_prefix"] + "n.pdf",
                             "content_kind": "notice", "pipeline_version": "doc-tools@61f74dc",
                             "format_fingerprint": "fp-1", "standing": "supervised",
                             "extraction_ref": w.row["extraction_ref"], "notice_id": "PCN26-119"}}]

    stores = promotion.PromotionStores(ledger=w.ledger, graph=Graph(), corrections=SimpleNamespace(
        emit=lambda record: "corrections/x.json"))
    monkeypatch.setattr(ht, "list_tasks_for", list_tasks)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    monkeypatch.setattr(gateway, "_review_mpns_for_payload", lambda subject: ["ABC123"])
    user = SimpleNamespace(authz_id=WHO, id=WHO, sub=WHO, email=WHO, persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as tc:
        w.api = Adapter(tc)
        yield w
    gateway.app.dependency_overrides.clear()


def _extract_in_place(w):
    """What doc-tools leaves behind when the extraction finishes: the manifest and review.json."""
    prefix = w.row["object_prefix"]
    gen = prefix + "generated/PCN26-119_pdf/doc-tools@61f74dc/"
    w.s3.objects[gen + "manifest.json"] = json.dumps({
        "doc_id": "PCN26-119", "filename": "n.pdf", "source_key": prefix + "n.pdf",
        "text_location": gen + "text.json", "pipeline_version": "doc-tools@61f74dc",
        "provenance": {"standing": "supervised", "ingest_id": w.row["id"]},
        "ingest_id": w.row["id"]}).encode()
    w.s3.objects[gen + "review.json"] = json.dumps(REVIEW).encode()
    w.row["extraction_ref"] = gen + "manifest.json"


def test_arm6_the_client_drives_drop_poll_extraction_promote_against_the_real_app(
        client, world, tmp_path):
    """drop -> poll -> extraction -> review_task -> promote -> ledger_entry, then a repeat."""
    f = tmp_path / "n.pdf"
    f.write_bytes(PDF_BYTES)
    api, base = world.api, Adapter.BASE

    # the client's default: a blank on_behalf_of, which the doc says means the caller
    ingest_id = client.drop(api, base, str(f), kind="pdf", content_kind="notice")
    assert ingest_id == world.row["id"] and ingest_id.startswith("sha256:")
    assert world.row["submitted_by"] == WHO

    # the row moves on its own between polls: received -> extracting -> review
    script = iter(["extracting", "review"])
    slept = []
    clock = iter(range(0, 10_000, 1))

    def fake_sleep(seconds):
        slept.append(seconds)
        stage = next(script)
        if stage == "review":
            _extract_in_place(world)
        world.row["status"] = stage

    status = client.poll(api, base, ingest_id, sleep=fake_sleep, clock=lambda: next(clock))
    assert client.field(status, "status", "stage") == "review"
    assert len(slept) == 2

    ex = client.extraction(api, base, ingest_id)
    assert client.field(ex, "extraction", "part_count") == 1
    assert client.field(ex, "extraction", "rows_without_evidence") == 0

    task_id = client.review_task(status)
    assert task_id == world.gateway._promotion_task_id(ingest_id, 0)
    assert client.field(status, "status", "review_shape") == "promotion"

    first = client.ledger_entry(client.promote(api, base, task_id))
    assert first["decision"] == "promoted" and first["record_id"] and first["replayed"] in (False, None)
    assert len(world.ledger.records) == 1

    # the same decision again replays the same record
    again = client.ledger_entry(client.promote(api, base, task_id))
    assert again["record_id"] == first["record_id"] and again["replayed"] is True


def test_arm7_a_poll_that_runs_out_of_time_returns_the_last_body(client, world, tmp_path):
    f = tmp_path / "n.pdf"
    f.write_bytes(PDF_BYTES + b"2")
    ingest_id = client.drop(world.api, Adapter.BASE, str(f), kind="pdf", content_kind="notice",
                             on_behalf_of=WHO)
    ticks = iter([0, 1, 1000, 1001, 1002])
    body = client.poll(world.api, Adapter.BASE, ingest_id, timeout_s=5, sleep=lambda s: None,
                       clock=lambda: next(ticks))
    assert client.field(body, "status", "stage") == "received"


def test_arm8_reject_refuses_a_code_the_api_does_not_take(client):
    with pytest.raises(ValueError):
        client.reject(None, "", "t", "because")


def test_arm9_importing_the_client_has_no_side_effects(monkeypatch):
    """No network, no environment read: a poisoned requests and an empty environment still import."""
    import requests  # noqa: PLC0415

    def boom(*a, **k):
        raise AssertionError("the client touched the network at import")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests.Session, "request", boom)
    for var in ("IA_BASE_URL", "IA_TOKEN", "IA_TOKEN_URL"):
        monkeypatch.delenv(var, raising=False)
    load_client(monkeypatch)
