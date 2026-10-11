"""The promotion review task's routing hint is `review_pool`, never a plain `domain`.

`_file_or_find_document_promotion_task` used to file `{**derived, "domain": DOMAIN, ...}`. That
`domain` was the content-kind registration's domain, uppercased: the ROUTING KEY for the audience
`document_promotion:<DOMAIN>`, not a fact about the document. Under a plain `domain` key a reader
could take it for the document's own. It is `review_pool` now.

`derived` (promotion.payload_from_extraction) is a closed literal with no `domain` key, so the old
spread never overwrote a document value; arm 2 of the brief (a stubbed `derived` carrying
`domain`) therefore does not apply and is replaced by `test_derived_cannot_carry_a_domain`.

Arm 3 is a derived source seal: every function that handles a document_promotion payload
(it names `promotion.KIND` or "document_promotion", or lives in promotion.py) is scanned, by AST,
for reads of the key "domain". There are no migration fallbacks: no in-repo reader needs the pool.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

HEX = "7c" * 32
ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
REF = PREFIX + "generated/doc_pdf/doc-tools@61f74dc/manifest.json"
MANIFEST = {"doc_id": "N-1", "filename": "doc.pdf", "source_key": PREFIX + "doc.pdf",
            "pipeline_version": "doc-tools@61f74dc", "ingest_id": ID,
            "provenance": {"standing": "supervised", "ingest_id": ID}}


@pytest.fixture
def registered(monkeypatch):
    row = {"id": ID, "status": "extracting", "kind": "pdf", "content_kind": "pcn",
           "object_prefix": PREFIX, "submitted_by": "alice@example.com"}
    rec = []
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)
    reg = type("Reg", (), {"domain": "sustainment"})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg if kind == "pcn" else None)
    monkeypatch.setattr(ht, "task_exists", lambda t: False)
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: rec.append(kw) or {"task_id": kw["task_id"], "recipients": []})
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: dict(MANIFEST))
    return rec


@pytest.fixture
def client():
    user = type("U", (), {"authz_id": "svc:doc-tools", "id": "svc:doc-tools",
                          "sub": "svc:doc-tools", "email": None, "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


def test_the_payload_carries_the_pool_under_its_own_name(client, registered):
    r = client.post(f"/ingest/{ID}/stage", json={"stage": "review", "extraction_ref": REF})
    assert r.status_code == 200, r.text
    (reg,) = registered
    assert reg["audience"] == f"{promotion.KIND}:SUSTAINMENT"
    assert reg["payload"]["review_pool"] == "SUSTAINMENT"
    assert "domain" not in reg["payload"], reg["payload"]


def test_derived_cannot_carry_a_domain():
    """Why arm 2 is skipped: the derived payload is a closed literal, so there was never a
    document `domain` for the routing hint to overwrite."""
    row = {"id": ID, "content_kind": "pcn", "object_prefix": PREFIX}
    derived = promotion.payload_from_extraction(ID, row, dict(MANIFEST), REF)
    assert "domain" not in derived and "review_pool" not in derived, sorted(derived)


# --- arm 3: nothing reads the pool as the document's domain --------------------------------

def _domain_reads(text: str, name: str = "<mod>"):
    """(function, lineno) for every read of the key "domain" -- `x["domain"]` or
    `x.get("domain"...)` -- inside a function that handles a document_promotion payload."""
    tree = ast.parse(text)
    whole_module = name.endswith("promotion.py")
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seg = ast.get_source_segment(text, fn) or ""
        if not (whole_module or "promotion.KIND" in seg or '"document_promotion"' in seg):
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                    and n.slice.value == "domain" and isinstance(n.ctx, ast.Load)):
                hits.append((fn.name, n.lineno))
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "get" and n.args
                  and isinstance(n.args[0], ast.Constant) and n.args[0].value == "domain"):
                hits.append((fn.name, n.lineno))
    return hits


def test_the_scanner_detects_a_planted_read():
    planted = ("def act(task):\n    kind = promotion.KIND\n    return task['payload']['domain']\n")
    assert _domain_reads(planted) == [("act", 3)]
    planted_get = ("def act(p):\n    k = 'x' and \"document_promotion\"\n    return p.get('domain')\n")
    assert _domain_reads(planted_get) == [("act", 3)]
    control = "def other(p):\n    return p['domain']\n"
    assert _domain_reads(control) == [], "a function that is not a promotion handler is out of scope"


def test_no_promotion_handler_reads_a_domain_key():
    found = {}
    for top in ("src", "agent_fleet"):
        for path in sorted((ROOT / top).rglob("*.py")):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "document_promotion" not in text and "promotion.KIND" not in text \
                    and path.name != "promotion.py":
                continue
            hits = _domain_reads(text, str(path))
            if hits:
                found[str(path.relative_to(ROOT))] = hits
    assert found == {}, found
