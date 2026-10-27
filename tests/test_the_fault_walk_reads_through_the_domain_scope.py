"""The S1000D fault walk, run WITH engine-o's graph restriction: it answers from the MAINTENANCE
instance graph and from nowhere else.

WHY THIS EXISTS. `tests/test_the_maintenance_fault_runs_as_a_case.py` runs the walk's selects
UNSCOPED on an `rdflib.Dataset(default_union=True)`. Live, every select goes through
`execute_sparql(domain="MAINTENANCE")`, which wraps it in
`VALUES ?__mesh_g { <http://internal/MAINTENANCE> <http://internal/MAINTENANCE_INSTANCES> }
GRAPH ?__mesh_g { ... }`. On 2026-10-16 the live `fault_isolation` select returned zero rows for
MRAD-ARR-0417 while all five of its legs were present in the drop's own `urn:doc:` graph (lane 74's
packets of 10-16 and 10-17). The offline test could not see that, because it never ran the wrap.
RULED (architect, via Chris, 2026-10-17): "the offline fixture test runs again WITH the engine's
graph restriction, fixture loaded into MAINTENANCE_INSTANCES; it must return the five fields and
must return zero when the fixture is loaded only into a urn:doc: graph. That is the seal for 7f's
fix."

WHAT IS REAL. engine-o's `/declared_query` route: the verb registry read from the real policy
tree, `build_selects`, `execute_sparql`'s scope wrap, and `shape_selects`. WHAT IS STUBBED: only
the Jena transport. The double answers whatever text `execute_sparql` posts by querying an rdflib
`Dataset` holding the committed fixture `tests/fixtures/s1000d_mrad/mrad.ttl`. The dataset unions
its default graph, as Fuseki appears to (the 10-17 packet), so the zero arm cannot pass merely
because a default graph is empty.

THE FIVE FIELDS are the `fault_isolation` select's five legs: the module's type, its label (the
DMC), its fault-code link, the code's value, and the code's text. The select projects `?dmc` and
`?text`; the leg arm removes each leg in turn and shows the row needs all five.

Run: uv run --frozen pytest tests/test_the_fault_walk_reads_through_the_domain_scope.py -v
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import rdflib
from rdflib import RDF, RDFS, URIRef

from agent_fleet.utils.declared_query import build_selects

_MRAD_TTL = Path(__file__).resolve().parent / "fixtures" / "s1000d_mrad" / "mrad.ttl"
MIL = rdflib.Namespace("http://edgy-solutions.com/ontology/mil#")

VERB = "s1000d_fault_walk"
PARAMS = {"fault_code": "MRAD-ARR-0417"}
INSTANCES = "http://internal/MAINTENANCE_INSTANCES"
#: The shape of the graph the live ingest wrote the module into (the 10-17 packet); the hash is a
#: placeholder.
URN_DOC = ("urn:doc:ingress-user/xml/" + "0" * 64
           + "/DMC-ODMRAD-A-34-10-01-00A-421A-A_001-00_EN-US.xml")
SCOPE = ("VALUES ?__mesh_g { <http://internal/MAINTENANCE> <http://internal/MAINTENANCE_INSTANCES> }"
         " GRAPH ?__mesh_g")
FAULT_ISOLATION = {"dmc": "ODMRAD-A-34-10-01-00A-421A-A", "text": "Array module fault, section 3."}


@pytest.fixture
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    # The registry reads the real policy tree, never an override.
    monkeypatch.delenv("WORKFLOW_DEFINITIONS_DIR", raising=False)
    return mod


class _Jena:
    """The Jena transport: answers the posted SPARQL from an rdflib Dataset and records the text."""

    def __init__(self, ds: rdflib.Dataset):
        self.ds, self.posted = ds, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, headers=None, **kw):
        q = data["query"]
        self.posted.append(q)
        body = json.loads(self.ds.query(q).serialize(format="json"))
        return SimpleNamespace(status_code=200, json=lambda: body)


def _dataset(graph: str) -> rdflib.Dataset:
    ds = rdflib.Dataset(default_union=True)
    ds.graph(URIRef(graph)).parse(str(_MRAD_TTL), format="turtle")
    return ds


def _walk(eo, monkeypatch, ds):
    jena = _Jena(ds)
    monkeypatch.setattr(eo, "_JENA_ENDPOINT", "http://jena/ds/query")
    monkeypatch.setattr(eo, "_jena_client", lambda: jena)
    out = asyncio.run(eo.declared_query_route(eo.DeclaredQueryRequest(verb=VERB, params=PARAMS)))
    selects = eo.load_query_verbs(eo.verb_dirs(eo.policy_root()))[VERB].selects
    # Every select reached the double; nothing was answered by the rdflib fallback.
    assert len(jena.posted) == len(selects), jena.posted
    return out["selects"], jena


def test_the_walk_answers_from_the_maintenance_instance_graph(eo, monkeypatch):
    selects, jena = _walk(eo, monkeypatch, _dataset(INSTANCES))
    assert selects["fault_isolation"] == FAULT_ISOLATION, selects
    # The rest of the walk reads through the same scope.
    assert all(v not in (None, [], {}) for v in selects.values()), selects
    # What answered was the scoped text, the one live posts.
    assert all(SCOPE in q for q in jena.posted), jena.posted


def test_the_walk_answers_nothing_when_the_fixture_is_only_in_a_urn_doc_graph(eo, monkeypatch):
    """Differs from the arm above ONLY in the graph's name."""
    ds = _dataset(URN_DOC)
    selects, _ = _walk(eo, monkeypatch, ds)
    assert selects["fault_isolation"] is None, selects
    assert all(v in (None, []) for v in selects.values()), selects
    # CONTROL on the same dataset: the unscoped text finds the row, so the zero above is the scope,
    # not an unreadable fixture.
    decl = eo.load_query_verbs(eo.verb_dirs(eo.policy_root()))[VERB]
    rows = [{str(k): str(v) for k, v in r.asdict().items()}
            for r in ds.query(build_selects(decl, PARAMS)["fault_isolation"])]
    assert rows == [FAULT_ISOLATION], rows


_FI = MIL["dmc-ODMRAD-A-34-10-01-00A-421A-A"]
_FC = MIL["faultcode-DMC-ODMRAD-A-34-10-01-00A-421A-A_001-00_EN-US.xml-MRAD-ARR-0417"]
_LEGS = [
    pytest.param((_FI, RDF.type, MIL.FaultIsolationDataModule), id="type"),
    pytest.param((_FI, RDFS.label, None), id="label"),
    pytest.param((_FI, MIL.hasFaultCode, _FC), id="hasFaultCode"),
    pytest.param((_FC, MIL.hasFaultCodeValue, None), id="hasFaultCodeValue"),
    pytest.param((_FC, MIL.hasFaultCodeText, None), id="hasFaultCodeText"),
]


@pytest.mark.parametrize("leg", _LEGS)
def test_each_of_the_five_legs_is_needed_for_the_row(eo, monkeypatch, leg):
    ds = _dataset(INSTANCES)
    g = ds.graph(URIRef(INSTANCES))
    assert len(list(g.triples(leg))) == 1, f"the fixture no longer holds this leg once: {leg}"
    g.remove(leg)
    selects, _ = _walk(eo, monkeypatch, ds)
    assert selects["fault_isolation"] is None, selects
