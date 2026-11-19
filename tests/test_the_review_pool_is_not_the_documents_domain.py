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
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {"review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})  # zero-row gate, ruling 2026-10-17
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


# A read of "domain" in a promotion handler is DECLARED here, by (path, function) -- never by line --
# with the NUMBER of reads it excuses and the reason none reads the pool as the document's domain.
# The list is checked both ways: a function with more reads than declared fails (the extra read is
# named by line), and one with fewer -- including none -- fails too (so it cannot go stale).
# This changes the census's rules at gov's request: gov reviews the mechanism too.
DECLARED_DOMAIN_READS = {
    ("src/iagent/gateway.py", "_file_or_find_document_promotion_task"): {
        "reads": 1,
        "why": "reads the receipt's STORED domain (ingest_status row) only to clear it when it differs "
               "from the task's routing domain (#443); it scopes, routes and files nothing from that value",
    },
}


def _scan_tree():
    found = {}
    for top in ("src", "agent_fleet"):
        for path in sorted((ROOT / top).rglob("*.py")):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "document_promotion" not in text and "promotion.KIND" not in text                     and path.name != "promotion.py":
                continue
            hits = _domain_reads(text, str(path))
            if hits:
                found[path.relative_to(ROOT).as_posix()] = hits
    return found


def _verdict(found, declared):
    """(undeclared reads, declared entries whose count is wrong).

    Per (path, function) the first `reads` hits are excused; each further hit is undeclared and
    keeps its line. A declared entry with fewer hits than `reads` is stale."""
    undeclared, stale = {}, []
    for f, hits in found.items():
        used = {}
        # ast.walk is breadth-first: a deeper read that comes LATER in the file can be listed before an
        # earlier one, and the census would then excuse the added line and name the declared one.
        for fn, line in sorted(hits, key=lambda h: h[1]):
            used[fn] = used.get(fn, 0) + 1
            if used[fn] > declared.get((f, fn), {}).get("reads", 0):
                undeclared.setdefault(f, []).append((fn, line))
    seen = {(f, fn): sum(1 for h, _ in hits if h == fn) for f, hits in found.items() for fn, _ in hits}
    for key, d in declared.items():
        if seen.get(key, 0) < d["reads"]:
            stale.append((key, d["reads"], seen.get(key, 0)))
    return undeclared, sorted(stale)


def _census_failure(undeclared, stale):
    """The census's own failure message (None when clean)."""
    out = []
    if undeclared:
        out.append(f"undeclared domain reads (path: [(function, line)]): {undeclared}")
    if stale:
        out.append(f"declared reads that no longer exist (entry, declared, found): {stale}")
    return "; ".join(out) or None


def test_no_promotion_handler_reads_a_domain_key():
    failure = _census_failure(*_verdict(_scan_tree(), DECLARED_DOMAIN_READS))
    assert failure is None, failure


def test_an_undeclared_read_still_fails():
    found = {"src/iagent/x.py": [("act", 3)], "src/iagent/gateway.py":
             [("_file_or_find_document_promotion_task", 9), ("other_handler", 20)]}
    undeclared, _ = _verdict(found, DECLARED_DOMAIN_READS)
    assert undeclared == {"src/iagent/x.py": [("act", 3)],
                          "src/iagent/gateway.py": [("other_handler", 20)]}


def test_a_declared_entry_that_matches_no_read_fails():
    declared = {**DECLARED_DOMAIN_READS, ("src/iagent/gone.py", "was_a_handler"): {"reads": 1, "why": "x"}}
    undeclared, stale = _verdict(_scan_tree(), declared)
    assert stale == [(("src/iagent/gone.py", "was_a_handler"), 1, 0)]
    assert undeclared == {}


def test_control_the_real_tree_passes_with_exactly_the_one_declared_entry():
    assert len(DECLARED_DOMAIN_READS) == 1
    found = _scan_tree()
    assert {(f, fn) for f, hits in found.items() for fn, _ in hits} == set(DECLARED_DOMAIN_READS)
    assert all(d["reads"] == 1 and d["why"] for d in DECLARED_DOMAIN_READS.values())


def test_a_second_read_in_the_declared_function_fails_and_names_its_line():
    (path, fn), = DECLARED_DOMAIN_READS
    found = {path: [(fn, 10), (fn, 42)]}
    undeclared, stale = _verdict(found, DECLARED_DOMAIN_READS)
    assert undeclared == {path: [(fn, 42)]} and stale == []
    assert "42" in _census_failure(undeclared, stale)      # the census's OWN message names the added line


def test_the_added_read_is_named_even_when_the_walk_lists_it_first():
    """ast.walk is breadth-first, so a deeper, later read can come BEFORE the declared (earlier) one."""
    (path, fn), = DECLARED_DOMAIN_READS
    undeclared, stale = _verdict({path: [(fn, 42), (fn, 10)]}, DECLARED_DOMAIN_READS)
    assert undeclared == {path: [(fn, 42)]} and stale == []
    assert "42" in _census_failure(undeclared, stale) and "10" not in _census_failure(undeclared, stale)


def test_the_same_function_name_in_another_file_is_not_excused():
    (path, fn), = DECLARED_DOMAIN_READS
    other = "src/iagent/not_the_gateway.py"
    undeclared, stale = _verdict({path: [(fn, 10)], other: [(fn, 5)]}, DECLARED_DOMAIN_READS)
    assert undeclared == {other: [(fn, 5)]} and stale == []


def test_a_declared_function_with_fewer_reads_than_declared_is_stale():
    (path, fn), = DECLARED_DOMAIN_READS
    declared = {(path, fn): {"reads": 2, "why": "x"}}
    undeclared, stale = _verdict({path: [(fn, 10)]}, declared)
    assert undeclared == {} and stale == [((path, fn), 2, 1)]
