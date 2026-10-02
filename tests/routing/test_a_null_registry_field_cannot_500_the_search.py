"""A Predicate row whose string field is NULL must not 500 /search_predicates.

MEASURED 2026-10-01 on the running engine-o (helm rev 161, image 0f48fe2f), each fire x3: every
POST /search_predicates answered 500, `ValidationError ... PredicateCandidate endpoint Input
should be a valid string [input_value=None]`. A read-only census of the Predicate collection
found 77 of 138 rows with no `endpoint_url`, and all 77 were `mesh:rendersAs` -- frontend
renderers that carry a `frontend_id` and have no URL by design. rendersAs floods unconstrained
search windows, so in practice any query hit one.

The defect was the mapping, not the rows: Weaviate returns every schema property on every row,
NULL where the row never set it, so `p.get("endpoint_url", "")` never used its default. The
two sibling builders (`/find_tool`, the classify path) already coerced with `or ""`.

DEFENDED FOR THE CLASS, not the field that bit: every source field the mapping renames into a
`str`-typed candidate field is parametrised below, and the endpoint arm drives the HANDLER, so
a consumer-side regression (the model re-typed, a builder bypassing the mapping) is red too.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_predicate_hybrid_search import _FakeObject, ontology_main  # noqa: E402,F401


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def hybrid(self, query, limit, filters, return_metadata, vector=None):
        return type("R", (), {"objects": self._rows[:limit]})()

    def bm25(self, query, limit, filters, return_metadata):
        return type("R", (), {"objects": self._rows[:limit]})()


class _Client:
    def __init__(self, rows):
        col = type("C", (), {"query": _Query(rows)})()
        self.collections = type("Cs", (), {"exists": lambda self, n: True,
                                           "get": lambda self, n: col})()


def _renders_as_row() -> dict:
    """The live shape: every schema key PRESENT, endpoint_url NULL (a renderer has no URL)."""
    return {
        "verb_iri": "mesh:rendersAs", "verb_local": "rendersAs",
        "input_uri": "http://invincible-agent/mesh#ImpactSet",
        "output_uri": "http://invincible-agent/mesh#Presentation",
        "endpoint_url": None, "frontend_id": "cortex-ui-desktop",
        "owner_persona": "DATA_STEWARD", "domains": [], "cost_class": None,
        "requires_human_approval": False,
    }


def _engine_row() -> dict:
    return {
        "verb_iri": "mesh:explain", "verb_local": "explain",
        "input_uri": "http://invincible-agent/mesh#DocPage",
        "output_uri": "http://invincible-agent/mesh#DocPage",
        "endpoint_url": "http://engine-docs:8100/explain", "frontend_id": None,
        "owner_persona": None, "domains": ["DOCS"], "cost_class": None,
        "requires_human_approval": False,
    }


#: source property -> the hit key the mapping renames it to. Every one feeds a `str` field of
#: PredicateCandidate (subject_uri, verb_type, verb_iri, endpoint, output_uri).
_STR_FIELDS = {
    "verb_iri": "verb_iri",
    "verb_local": "verb_type",
    "input_uri": "input_uri",
    "output_uri": "output_uri",
    "endpoint_url": "endpoint",
}


def _search(ontology_main, monkeypatch, rows):
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT", _Client([_FakeObject(r, 0.5) for r in rows]))
    return ontology_main._predicate_hybrid_search_sync("q", entitled_domains=[], limit=10)


def test_the_candidate_model_still_types_these_fields_str(ontology_main):
    """The premise of every arm below. If the model loosens to `str | None`, the coercion is
    moot and these arms should be revisited, not silently keep passing."""
    fields = ontology_main.PredicateCandidate.model_fields
    for f in ("subject_uri", "verb_type", "verb_iri", "endpoint", "output_uri"):
        assert fields[f].annotation is str, f


@pytest.mark.parametrize("source", sorted(_STR_FIELDS))
def test_a_present_null_string_field_maps_to_empty_string(ontology_main, monkeypatch, source):
    row = _engine_row()
    row[source] = None
    (hit,) = _search(ontology_main, monkeypatch, [row])
    assert hit[_STR_FIELDS[source]] == "", (source, hit[_STR_FIELDS[source]])


def test_CONTROL_a_set_endpoint_survives_the_coercion(ontology_main, monkeypatch):
    (hit,) = _search(ontology_main, monkeypatch, [_engine_row()])
    assert hit["endpoint"] == "http://engine-docs:8100/explain"
    assert hit["verb_type"] == "explain"


def test_CONTROL_an_absent_key_still_maps_to_empty_string(ontology_main, monkeypatch):
    row = _engine_row()
    del row["endpoint_url"]
    (hit,) = _search(ontology_main, monkeypatch, [row])
    assert hit["endpoint"] == ""


def test_search_predicates_answers_with_a_renderer_row_in_the_window(ontology_main, monkeypatch):
    """The measured failure, end to end through the handler: one null-endpoint renderer row
    beside a real engine row. Unfixed, this raises ValidationError (the live 500)."""
    monkeypatch.setattr(ontology_main, "_WEAVIATE_CLIENT",
                        _Client([_FakeObject(_renders_as_row(), 0.7), _FakeObject(_engine_row(), 0.3)]))
    monkeypatch.setattr(ontology_main, "_emit_routing_decision", lambda **_kw: None)
    # HARNESS, not production: the fixture loads main.py by path under a synthetic module name,
    # so pydantic cannot resolve the response model's forward reference on its own.
    ontology_main.SearchPredicatesResponse.model_rebuild(
        _types_namespace={"PredicateCandidate": ontology_main.PredicateCandidate})
    resp = asyncio.run(ontology_main.search_predicates(
        ontology_main.SearchPredicatesRequest(query="how do I add a canvas template",
                                              entitled_domains=["DOCS"], limit=10,
                                              # the mesh flag is on by default (c94a43a1): a mesh
                                              # read is attributed to a person or it is not made.
                                              user_email="alice@example.com")))
    assert resp.found is True
    by_verb = {c.verb_iri: c for c in resp.candidates}
    assert set(by_verb) == {"mesh:rendersAs", "mesh:explain"}
    assert by_verb["mesh:rendersAs"].endpoint == ""
    assert by_verb["mesh:explain"].endpoint == "http://engine-docs:8100/explain"
