"""A `kind: document` grant is stored in the form the document gate ASKS Topaz about.

The gate (Engine W `_gate_hits`, Engine E `_can_read_document`) sends the chunk's
`source_url or uri or doc_id` to Topaz VERBATIM as the `document` object id: no prefix
expansion, no namespace rewrite. So a grant row matches a chunk only if it is spelled exactly
as the chunk producer stamped it: a full IRI for an S1000D data module (doc-tools stamps
`MIL[...]`, the `mil` namespace of setup/ontologies/mil_extension.ttl), a bare doc_id for a
seeded manual (scripts/seed_weaviate_manuals.py). A short `mil#x` is stamped by nothing.

Three arms:
  1. the REAL gate against a Topaz double that admits ONE spelling: only that spelling reads;
  2. `grant_sync` diffs and REVOKES: a file in the wrong spelling against live data in the
     right one revokes the live reader;
  3. the shipped file: every document row is a spelling the gate can build.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import httpx
import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_SYNC = _REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from grant_sync import GrantRecord, load_grants, sync_grants  # noqa: E402
from topaz_sync import DirObject, DirRelation  # noqa: E402

_saved = sys.modules.get("baml_client")
_stub = types.ModuleType("baml_client")
_stub.b = types.SimpleNamespace(with_options=lambda **_k: None)
try:
    sys.modules["baml_client"] = _stub
    import agent_fleet.weaviate_expert.service as w  # noqa: E402
finally:
    if _saved is None:
        sys.modules.pop("baml_client", None)
    else:
        sys.modules["baml_client"] = _saved

ALICE = "alice@example.com"
NS = "http://edgy-solutions.com/ontology/mil#"
FULL = NS + "dmc-example-001"
SHORT = "mil#dmc-example-001"


def _topaz(monkeypatch, module, admitted: set):
    """A Topaz double admitting exactly `admitted` (user, document id) pairs; records the asks."""
    asked: list = []

    def post(url, json=None, timeout=None, **_k):
        asked.append(json["object_id"])
        ok = (json["subject_id"], json["object_id"]) in admitted
        return httpx.Response(200, json={"check": ok}, request=httpx.Request("POST", url))

    monkeypatch.setattr(module.httpx, "post", post)
    monkeypatch.setattr(module, "ENABLE_AGENTIC_AUTH", True, raising=False)
    return asked


def _chunk(**props):
    return types.SimpleNamespace(properties=props)


@pytest.mark.parametrize("props, asked_id", [
    ({"doc_id": FULL}, FULL),
    ({"source_url": "https://s/x", "doc_id": FULL}, "https://s/x"),
    ({"uri": FULL, "doc_id": "d"}, FULL),
    ({"doc_id": "TM-1H-130H-2-12-01"}, "TM-1H-130H-2-12-01"),
])
def test_engine_w_gate_asks_topaz_about_the_chunks_own_id_verbatim(monkeypatch, props, asked_id):
    asked = _topaz(monkeypatch, w, {(ALICE, asked_id)})
    kept, dropped = w._gate_hits([_chunk(**props)], ALICE)
    assert asked == [asked_id] and len(kept) == 1 and dropped == 0


def test_a_short_form_grant_does_not_read_a_full_iri_chunk_and_the_full_form_does(monkeypatch):
    chunk = _chunk(doc_id=FULL)
    _topaz(monkeypatch, w, {(ALICE, SHORT)})
    assert w._gate_hits([chunk], ALICE) == ([], 1)
    _topaz(monkeypatch, w, {(ALICE, FULL)})
    kept, dropped = w._gate_hits([chunk], ALICE)
    assert len(kept) == 1 and dropped == 0


def test_engine_e_sends_the_same_id_verbatim(monkeypatch):
    pytest.importorskip("baml_py")
    saved = sys.modules.get("baml_client")
    sys.modules["baml_client"] = _stub
    try:
        import agent_fleet.neo4j_expert.service as e
    finally:
        if saved is None:
            sys.modules.pop("baml_client", None)
        else:
            sys.modules["baml_client"] = saved
    asked = _topaz(monkeypatch, e, {(ALICE, FULL)})
    assert e._can_read_document(ALICE, FULL) is True
    assert e._can_read_document(ALICE, SHORT) is False
    assert asked == [FULL, SHORT]


# --------------------------------------------------------------------------- grant_sync revokes
class _Dir:
    def __init__(self):
        self.objects, self.relations = set(), set()

    def set_object(self, obj, display_name=""):
        self.objects.add(obj)

    def set_relation(self, rel):
        self.relations.add(rel)

    def delete_relation(self, rel):
        self.relations.discard(rel)

    def delete_object(self, obj, with_relations=True):
        self.objects.discard(obj)

    def list_objects(self, t):
        return [o for o in self.objects if o.type == t]

    def object_exists(self, t, i):
        return DirObject(t, i) in self.objects

    def list_relations(self, object_type, relation):
        return [r for r in self.relations if r.object_type == object_type and r.relation == relation]


def _live(doc_id):
    d = _Dir()
    d.set_object(DirObject("user", ALICE))
    d.set_object(DirObject("document", doc_id))
    d.set_relation(DirRelation("document", doc_id, "reader", "user", ALICE))
    return d


def _g(asset):
    return GrantRecord(ALICE, asset, "cnogradi", "r", kind="document")


def test_grant_sync_revokes_the_live_full_iri_when_the_file_says_the_short_form():
    live = _live(FULL)
    sync_grants(live, [_g(SHORT)])
    assert DirRelation("document", FULL, "reader", "user", ALICE) not in live.relations
    assert DirRelation("document", SHORT, "reader", "user", ALICE) in live.relations


def test_grant_sync_keeps_the_live_full_iri_when_the_file_says_the_same_form():
    live = _live(FULL)
    sync_grants(live, [_g(FULL)])
    assert DirRelation("document", FULL, "reader", "user", ALICE) in live.relations


# --------------------------------------------------------------------------- the shipped file
def _shipped_documents():
    raw = yaml.safe_load((_REPO / "policy" / "asset_grants.yaml").read_text(encoding="utf-8"))
    grants, errors = load_grants(raw)
    assert errors == []
    return [g.asset for g in grants if g.kind == "document"]


def _declared_namespaces():
    out = set()
    for ttl in (_REPO / "setup" / "ontologies").glob("*.ttl"):
        out |= set(re.findall(r"@prefix\s+\w*:\s*<([^>]+)>", ttl.read_text(encoding="utf-8")))
    return out


def _seed_doc_ids():
    text = (_REPO / "scripts" / "seed_weaviate_manuals.py").read_text(encoding="utf-8")
    return set(re.findall(r'"doc_id":\s*"([^"]+)"', text))


def _form_the_gate_can_build(asset: str) -> bool:
    """A full IRI inside a declared ontology namespace (the S1000D stamp), or a seeded bare id."""
    if asset in _seed_doc_ids():
        return True
    return any(asset.startswith(ns) and len(asset) > len(ns) for ns in _declared_namespaces())


def test_every_shipped_document_row_is_a_form_the_gate_can_build():
    bad = [a for a in _shipped_documents() if not _form_the_gate_can_build(a)]
    assert bad == [], f"document grants in a form no chunk is stamped with: {bad}"


def test_the_seal_goes_red_on_a_short_form_row():
    assert not _form_the_gate_can_build(SHORT)
    assert _form_the_gate_can_build(FULL)
