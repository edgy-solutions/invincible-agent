"""The docs page gate and the capability grants it reads are one decision, asserted at the join.

Two seals each cover one end, and neither covers the join.
- `test_explain_withholds_a_page_the_asker_cannot_invoke.py` drives the gate against a
  FIXTURE of grants.
- `test_every_explained_verb_has_a_derived_invoker.py` checks `capability_grants.yaml` against
  keys it spells itself (`f"mesh:{verb}"`, lowerCamel locals only).
Both stay green if the gate asks for a capability under one spelling and the sync writes it
under another. After the flip, that failure withholds every verb-bearing page from every
caller.

So every name here is DERIVED from the code that ships:
- the capabilities asked come from the gate's own `gated_capabilities`, over the corpus;
- the relations come from the sync's own `load_capabilities` and `derive_desired`, over the
  real yaml;
- the permission comes from the Topaz manifest's `capability` type;
- the request comes from the gate's own `can_invoke`, as it would be POSTed.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import sys

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[2]
for p in (_REPO, _REPO / "policy" / "sync"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import agent_fleet.docs_agent.entitlement as ent  # noqa: E402
import capability_grant_sync as cgs  # noqa: E402

CORPUS = _REPO / "setup" / "ontologies" / "docs_corpus.ttl"
GRANTS = _REPO / "policy" / "capability_grants.yaml"
MANIFEST = _REPO / "helm" / "invincible-agent" / "templates" / "topaz-configmap.yaml"
MESH = "http://invincible-agent/mesh#"


@dataclasses.dataclass(frozen=True)
class _Row:
    iri: str
    title: str
    explains: tuple


def _rows() -> list:
    import rdflib
    from rdflib.namespace import RDF, RDFS

    g = rdflib.Graph().parse(CORPUS, format="turtle")
    M = rdflib.Namespace(MESH)
    return [_Row(str(p), str(g.value(p, RDFS.label) or ""),
                 tuple(sorted(str(o) for o in g.objects(p, M.explains))))
            for p in g.subjects(RDF.type, M.DocPage)]


def _permission_relations() -> dict:
    """The manifest's `capability` type: {permission: relation it is computed from}."""
    text = MANIFEST.read_text(encoding="utf-8")
    m = re.search(r"^(\s*)capability:\n((?:\1\s+.*\n)+)", text, re.M)
    assert m, "no `capability:` type in the Topaz manifest: the matcher reaches nothing"
    perms = re.search(r"permissions:\n((?:\s+\w+:\s*\w+\n)+)", m.group(2))
    assert perms, "the manifest's capability type declares no permissions"
    return dict(re.findall(r"(\w+):\s*(\w+)", perms.group(1)))


def _relations(raw: dict) -> set:
    caps, errors = cgs.load_capabilities(raw)
    assert not errors, errors
    return cgs.derive_desired(caps).relations


def _decider(relations: set):
    """Answers a POSTed check as the manifest computes it, from the relations the sync wrote."""
    computed = _permission_relations()

    def post(url, json=None, timeout=None, **_kw):
        via = computed.get(json["relation"])
        ok = any((r.object_type, r.object_id, r.relation, r.subject_type, r.subject_id)
                 == (json["object_type"], json["object_id"], via,
                     json["subject_type"], json["subject_id"])
                 for r in relations)

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"check": ok}

        return _R()
    return post


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(ent, "TOPAZ_DIRECTORY_URL", "http://topaz.test")

    def _served_to(relations: set, row) -> set:
        monkeypatch.setattr(ent.httpx, "post", _decider(relations))
        users = {r.subject_id for r in relations}
        return {u for u in users if ent.partition([row], u)[0]}
    return _served_to


ROWS = _rows()
VERB_PAGES = [r for r in ROWS if ent.gated_capabilities(r.explains)]


def test_the_corpus_has_pages_the_gate_asks_about_and_pages_it_does_not():
    assert VERB_PAGES, "no corpus page explains a verb: the gate is asked nothing"
    assert len(VERB_PAGES) < len(ROWS), "every page explains a verb: the control below has no subject"


def test_the_manifest_computes_can_invoke_from_the_relation_the_sync_writes(monkeypatch):
    asked = []

    def post(url, json=None, timeout=None, **_kw):
        asked.append(json)
        raise RuntimeError("recorded")

    monkeypatch.setattr(ent, "TOPAZ_DIRECTORY_URL", "http://topaz.test")
    monkeypatch.setattr(ent.httpx, "post", post)
    ent.can_invoke("someone@example.test", "mesh:seedCanvas")
    (req,) = asked
    written = {(t, rel) for t, rel in cgs.MANAGED_CAPABILITY_RELATIONS}
    assert (req["object_type"], _permission_relations().get(req["relation"])) in written, (
        f"the gate asks {req['object_type']}#{req['relation']}, which the manifest computes from "
        f"{_permission_relations().get(req['relation'])!r}; the sync writes {sorted(written)}")


def test_every_capability_the_gate_asks_of_the_corpus_is_a_key_the_sync_writes():
    asked = {c for r in ROWS for c in ent.gated_capabilities(r.explains)}
    written = {r.object_id for r in _relations(yaml.safe_load(GRANTS.read_text(encoding="utf-8")))}
    missing = sorted(asked - written)
    assert not missing, (
        f"the gate asks {missing}, which the sync writes no invoker for; after the flip every page "
        f"explaining them is withheld from every caller")


@pytest.mark.parametrize("row", VERB_PAGES, ids=lambda r: r.iri.rsplit("#", 1)[-1])
def test_no_verb_bearing_page_is_withheld_from_every_grantee(gate, row):
    rels = _relations(yaml.safe_load(GRANTS.read_text(encoding="utf-8")))
    assert gate(rels, row), (
        f"{row.iri} explains {ent.gated_capabilities(row.explains)}, and the gate on the sync's "
        f"relations serves it to no grantee")


def test_CONTROL_the_same_decider_on_no_grants_serves_no_verb_bearing_page(gate):
    """Same gate, same decider, same rows; it differs only in the grants. One placeholder
    grant keeps the population of askers non-empty, so 'served to nobody' is a decision."""
    raw = {"capabilities": {"mesh:censusControlOnly": {
        "granted_by": "test", "reason": "control", "grant_to": ["control@example.test"]}}}
    rels = _relations(raw)
    assert all(not gate(rels, r) for r in VERB_PAGES)
    other = [r for r in ROWS if not ent.gated_capabilities(r.explains)]
    assert all(gate(rels, r) == {"control@example.test"} for r in other), (
        "a page explaining no verb was withheld: the decider denies blanket, not by grant")
