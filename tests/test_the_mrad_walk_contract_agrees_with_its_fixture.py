"""`walk-MRAD-ARR-0417.json` is the contract 7f builds to; `mrad.ttl` is the per-module drift check.

RULED (architect, 2026-10-16): an option's DMC becomes `procedures[]` (ordered), and an option
may carry cited values `{value, evidence_ref}`. The file is the EXPECTED RENDERED WALK for the fault
code, options and all. OVERRULED (architect, 2026-10-17): 421A is the module an option comes FROM,
not a procedure the mechanic performs, so `procedures[]` holds only procedural modules and 421A
stays in `citations`; option 4 cites the 320A interval. These arms keep the file honest against
the graph it is a contract over:

- its `citations` are what the REAL walk renders over `mrad.ttl` today, not a transcription;
- every procedure is a procedural module the fault-isolation module refers to, never 421A itself,
  and a replace option's procedures are the remove/install citation's modules;
- `procedures` is REQUIRED and may be empty (architect, 2026-10-17: min 0): an option with none
  is an inspect/observe option, and its cited `action` text carries it;
- a cited part value is the IPD citation's, cited to the IPD module; a cited interval is the
  planning citation's (which the first arm proves the walk renders from 320A's interval).

Not asserted: procedure ORDER. `mrad.ttl` carries none, so 7f's output must (an rdf:List or an
explicit mil:stepIndex); the order arm goes in once 7f says which.

The options are rendered by the `render` step of the `maint_fault_propose` template, not by the
walk, so no arm here can see them: this file reads the fixture graph, which can never flip. Whether
a case renders them is checked live by the e2e step `tests/sandbox_e2e/test_mrad_case_walks_to_
closed.py`, and lane/74's walk of 2026-10-17 (`MRAD-ARR-0417 walked live to closed`, case
712382d7) is the record of the flip.
"""
from __future__ import annotations

import json
from pathlib import Path

import rdflib

from tests.test_the_maintenance_fault_runs_as_a_case import _MRAD_TTL, _shaped_walk, main

_CONTRACT = Path(__file__).resolve().parent / "fixtures" / "s1000d_mrad" / "walk-MRAD-ARR-0417.json"
_MIL = rdflib.Namespace("http://edgy-solutions.com/ontology/mil#")


def _contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _rendered() -> dict:
    params = {"fault_code": _contract()["bit_code"]}
    decl, shaped = _shaped_walk("s1000d_fault_walk", params)
    return main._render(decl.returns, {"params": params, **shaped}, where="contract")


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(str(_MRAD_TTL), format="turtle")
    return g


def _module(g: rdflib.Graph, dmc: str):
    hits = [s for s in g.subjects(rdflib.RDFS.label, rdflib.Literal(dmc))
            if (s, rdflib.RDF.type, _MIL.DataModule) in g]
    assert len(hits) == 1, f"{dmc}: {len(hits)} data modules carry this label"
    return hits[0]


def test_the_contracts_citations_are_what_the_real_walk_renders():
    r, c = _rendered(), _contract()
    assert (r["bit_code"], r["bit_text"], r["citations"]) == (c["bit_code"], c["bit_text"], c["citations"])


def test_procedures_are_the_procedural_modules_the_fault_isolation_module_refers_to():
    c, g = _contract(), _graph()
    fi_dmc = c["citations"]["fault_isolation"]["dmc"]
    fi = _module(g, fi_dmc)
    referred = {str(g.value(dm, rdflib.RDFS.label)) for dm in g.objects(fi, _MIL.refersToDataModule)
                if (dm, rdflib.RDF.type, _MIL.ProcedureDataModule) in g}
    remove_install = set(c["citations"]["remove_install"]["dmc"])
    assert remove_install and remove_install <= referred
    assert [o["n"] for o in c["options"]] == [1, 2, 3, 4]
    for o in c["options"]:
        assert isinstance(o.get("procedures"), list), o["n"]
        procs = o["procedures"]
        if not procs:
            assert "action" in o.get("cited", {}), o["n"]
        assert fi_dmc not in procs, o["n"]
        assert set(procs) <= referred and len(set(procs)) == len(procs), o["n"]
        for dmc in procs:
            _module(g, dmc)
        replaces = "part_number" in o.get("cited", {})
        assert set(procs) == (remove_install if replaces else set()), o["n"]


def test_a_cited_value_names_a_module_and_a_part_value_is_the_ipd_citations():
    c, g = _contract(), _graph()
    ipd = c["citations"]["ipd"]
    for o in c["options"]:
        for key, cv in o.get("cited", {}).items():
            assert set(cv) == {"value", "evidence_ref"}, (o["n"], key)
            _module(g, cv["evidence_ref"])
            if key in ("part_number", "quantity", "icn"):
                assert cv == {"value": ipd[key], "evidence_ref": ipd["dmc"]}, (o["n"], key)
            if key == "action":
                assert cv["evidence_ref"] == c["citations"]["fault_isolation"]["dmc"], o["n"]
            if key == "interval":
                pi = c["citations"]["planning_interval"]
                assert cv == {"value": pi["interval"], "evidence_ref": pi["dmc"]}, o["n"]
    assert "interval" in c["options"][3]["cited"]

