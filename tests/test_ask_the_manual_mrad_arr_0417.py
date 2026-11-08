"""Ask the manual: ten questions a maintainer asks about MRAD-ARR-0417, against what we hold of it.

WHAT IS ASKED. The only retrieval over this manual today is the declared walk
`s1000d_fault_walk` (policy/overlays/openddil-lab/verbs/), run over the committed triples
`tests/fixtures/s1000d_mrad/mrad.ttl`. This file runs the REAL declaration over the REAL fixture,
the same way `test_the_maintenance_fault_runs_as_a_case.py` does, and asks whether each answer is
in what the walk returns.

WHAT AN ANSWER MUST CITE: the data module AND the paragraph. The source is the six XML modules
in doc-tools `tests/fixtures/s1000d/mrad/`. They carry no `id=` attribute anywhere, so a
paragraph can only be cited by position (the nth step, the nth answer), and `ANCHOR` below gives
that position for each answer. No arm can check it against the XML, which is not in this repo.

EVERY MISS IS ONE OF THREE KINDS, and each kind has its own arm:
  * RETRIEVAL: the triples carry the answer, and the walk has no select that returns it. The arm
    asserts the triples carry it, which passes. It also asserts the walk returns it, a strict
    xfail.
  * EXTRACTION: the answer is in the source XML, and doc-tools' parser does not emit it. The arm
    asserts the triples carry it: a strict xfail. Its positive control proves that the same
    matcher finds a literal the triples do carry.
  * FIXTURE LAG: doc-tools' parser on its main branch emits it, and `mrad.ttl` was copied before
    it did (README: PR #63 at 4a6df088; procedure steps arrived in #131, 2a1c9fa). Ours to
    regenerate, not 7f's.
An answer is citable below the data module exactly when its text sits on its own node, so each
text arm also measures whether its paragraph can be cited.
A defect arm is `xfail(strict=True, raises=AssertionError)`. When the defect is fixed the arm
XPASSes and goes red, so its marker has to come off. A crash is not a recorded miss.

The walk's own contract (`walk-MRAD-ARR-0417.json`) changes only by ruling. So the retrieval
fixes are proposed in docs/measurements/2026-10-25-ask-the-manual-mrad-arr-0417.md, not applied
here.

Run: uv run --frozen pytest tests/test_ask_the_manual_mrad_arr_0417.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from agent_fleet.utils.declared_query import (
    build_selects, load_query_verbs, policy_root, shape_selects, verb_dirs)

FAULT = "MRAD-ARR-0417"
VERB = "s1000d_fault_walk"
_TTL = Path(__file__).resolve().parent / "fixtures" / "s1000d_mrad" / "mrad.ttl"

DM = "ODMRAD-A-34-10-01-00A-{}-A".format
FI, RM, INS, IPD, PLAN = DM("421A"), DM("520A"), DM("720A"), DM("941A"), DM("320A")

#: Where each answer sits in the source XML, by position (the XML has no ids). This is a record
#: for the report; no arm reads it.
ANCHOR = {
    "Q1": (FI, "faultIsolation/faultCode/faultCodeText"),
    "Q2": (FI, "isolationProcStep[1]/test, then isolationProcStep[1]/answer[yes]/isolationProcStep[1]/test"),
    "Q3": (FI, "isolationProcStep[1]/answer[yes]/isolationProcStep/answer[yes]/isolationProcStep"
               "/answer[yes]/isolationAction ('Replace array module.'), then its dmRef to 520A"),
    "Q4": (RM, "mainProcedure/proceduralStep[1..4], then 720A mainProcedure/proceduralStep[1..5]"),
    "Q5": (RM, "preliminaryRqmts/reqSupportEquips/reqSupportEquip[1] (and 720A, the same)"),
    "Q6": (INS, "preliminaryRqmts/reqSpares/reqSpare[1]; 941A catalog item 0001"),
    "Q7": (IPD, "catalog items 0002 (connector gasket) and 0003 (screw, qty 2); 720A proceduralStep[2], [3]"),
    "Q8": (RM, "preliminaryRqmts/reqSafety/warning[1] (and 720A, the same)"),
    "Q9": (IPD, "figure ICN-ODMRAD-00001, title 'Array Module Assembly'"),
    "Q10": (PLAN, "Periodic Array Inspection, para[1]"),
}


@pytest.fixture(scope="module")
def graph():
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return g


@pytest.fixture(scope="module")
def walk():
    """The walk's selects, shaped: the real declaration, its params injected, run over the fixture."""
    decl = load_query_verbs(verb_dirs(policy_root()))[VERB]
    ds = rdflib.Dataset(default_union=True)
    ds.parse(str(_TTL), format="turtle")
    rows = {}
    for name, sparql in build_selects(decl, {"fault_code": FAULT}).items():
        res = ds.query(sparql)
        cols = [str(v) for v in res.vars]
        rows[name] = [{v: (str(r[v]) if r[v] is not None else None) for v in cols} for r in res]
    return shape_selects(decl, rows)


@pytest.fixture(autouse=True, scope="module")
def _real_policy():
    mp = pytest.MonkeyPatch()
    mp.delenv("WORKFLOW_DEFINITIONS_DIR", raising=False)
    yield
    mp.undo()


def _values(obj) -> set[str]:
    """Every scalar the walk returns, as strings."""
    if isinstance(obj, dict):
        return set().union(*(_values(v) for v in obj.values())) if obj else set()
    if isinstance(obj, (list, tuple)):
        return set().union(*(_values(v) for v in obj)) if obj else set()
    return set() if obj is None else {str(obj)}


def _literals(g) -> list[str]:
    return [str(o).lower() for o in g.objects() if isinstance(o, rdflib.Literal)]


def _in_triples(g, text: str) -> bool:
    """Does any literal in the triples contain `text`? Case-insensitive substring."""
    return any(text.lower() in lit for lit in _literals(g))


def _walk_says(walk, *values) -> bool:
    got = _values(walk)
    return all(str(v) in got for v in values)


RETRIEVAL = pytest.mark.xfail(strict=True, raises=AssertionError,
                              reason="DEFECT retrieval: in the triples, no walk select returns it")
EXTRACTION = pytest.mark.xfail(strict=True, raises=AssertionError,
                               reason="DEFECT extraction: in the source XML, not in the triples")
FIXTURE_LAG = pytest.mark.xfail(strict=True, raises=AssertionError,
                                reason="DEFECT fixture lag: doc-tools main emits it, mrad.ttl predates")


# --- the matchers can see what is there ---------------------------------------------------------

def test_control_the_walk_matcher_finds_what_the_walk_returns(walk):
    assert _walk_says(walk, FI) and not _walk_says(walk, "not-a-dmc")


def test_control_the_triple_matcher_finds_a_literal_the_triples_carry(graph):
    assert _in_triples(graph, "array module fault, section 3") and not _in_triples(graph, "zzqx")


# --- answered at data-module level --------------------------------------------------------------

def test_Q1_what_does_the_code_mean(walk):
    """Q1. What does MRAD-ARR-0417 mean?"""
    assert _walk_says(walk, FI, "Array module fault, section 3.")


def test_Q3_which_modules_replace_the_array_module(walk):
    """Q3. If it is confirmed, which procedures replace the module?"""
    assert _walk_says(walk, RM, INS)


def test_Q6_which_spare_and_how_many(walk):
    """Q6. Which spare do I draw, and how many?"""
    assert _walk_says(walk, IPD, "ODM-AM-0001", "1")


def test_Q9_which_illustration(walk):
    """Q9. Which illustration shows the array module?"""
    assert _walk_says(walk, IPD, "ICN-ODMRAD-00001")


def test_Q10_how_often_is_the_array_inspected(walk):
    """Q10. How often is the array inspected?"""
    assert _walk_says(walk, PLAN, "180 days")


# --- retrieval: the triples carry it, the walk does not return it --------------------------------

_TOOLS = """PREFIX mil: <http://edgy-solutions.com/ontology/mil#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?dmc ?pn WHERE { ?dm rdfs:label ?dmc ; mil:requiresTool ?t . ?t mil:hasPartNumber ?pn . }"""

_ITEMS = """PREFIX mil: <http://edgy-solutions.com/ontology/mil#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?pn ?q ?name WHERE { ?dm a mil:IllustratedPartsDataModule ; mil:hasCatalogItem ?i .
  ?i mil:hasPartNumber ?pn ; mil:hasQuantity ?q ; rdfs:label ?name . }"""


def test_Q5_the_triples_name_the_tool_for_both_procedures(graph):
    got = {(str(r.dmc), str(r.pn)) for r in graph.query(_TOOLS)}
    assert got == {(RM, "ODM-SE-0001"), (INS, "ODM-SE-0001")}


@RETRIEVAL
def test_Q5_what_tools_do_i_need(walk):
    """Q5. What tools do I need for the remove and the install?"""
    assert _walk_says(walk, "ODM-SE-0001")


def test_Q7_the_triples_list_the_gasket_and_the_screws(graph):
    got = {(str(r.pn), int(r.q)) for r in graph.query(_ITEMS)}
    assert {("ODM-GS-0002", 1), ("ODM-SC-0003", 2)} <= got


@RETRIEVAL
def test_Q7_do_i_need_a_new_gasket_or_screws(walk):
    """Q7. What else is in the assembly: the connector gasket, the two screws?"""
    assert _walk_says(walk, "ODM-GS-0002", "ODM-SC-0003")


def test_Q9_the_triples_carry_the_figure_title(graph):
    assert _in_triples(graph, "Array Module Assembly")


@RETRIEVAL
def test_Q9_the_walk_names_the_figure(walk):
    assert _walk_says(walk, "Array Module Assembly")


# --- extraction: in the source XML, not in the triples -------------------------------------------

@EXTRACTION
def test_Q2_what_do_i_check_first(graph):
    """Q2. What do I check first, and then what? 421A's isolation tests."""
    assert _in_triples(graph, "Re-run BIT. Does fault code MRAD-ARR-0417 report again?")
    assert _in_triples(graph, "Check the array module power LED")


@EXTRACTION
def test_Q3_on_what_condition_do_i_replace(graph):
    """Q3, the condition: the replace action is the 'yes' answer of the reseat test."""
    assert _in_triples(graph, "Replace array module.")


@FIXTURE_LAG
def test_Q4_in_what_order(graph):
    """Q4. In what order? The steps of 520A, then 720A. `refersToDataModule` is a set, so the
    walk's ORDER BY ?dmc puts 520A first only because of the codes' spelling. doc-tools #131
    emits each procedure's steps as an rdf:List of `mil:ProceduralStep` with `mil:hasStepText`."""
    assert _in_triples(graph, "Disconnect the array module connector")
    preds = {str(p).rsplit("#", 1)[-1] for p in graph.predicates()}
    assert preds & {"stepIndex", "first", "rest"}


@EXTRACTION
def test_Q5_what_the_tool_is_called(graph):
    """Q5, the name: the triples label the tool with its part number only."""
    assert _in_triples(graph, "array module extraction tool")


@EXTRACTION
def test_Q8_any_warning_before_i_start(graph):
    """Q8. Any warning before I start? SAFETY: both 520A and 720A warn 'Disconnect power before
    removal.', and the walk sends a mechanic to 520A without it."""
    assert _in_triples(graph, "Disconnect power before removal.")


@EXTRACTION
def test_Q10_what_the_inspection_involves(graph):
    assert _in_triples(graph, "inspect the array face for physical damage")
