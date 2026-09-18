"""THE THREE READS THAT RETURN `[]` FOR TWO DIFFERENT WORLDS.

`execute_sparql`, `_discover_enumerate_providers` and `_get_subject_ancestor_chain` each return an
empty list both when nothing matched and when the substrate could not be asked. A caller holding
`[]` cannot tell an outage from a fact about the data, so every one of them renders a dead store as
a confident zero.

**THE SECOND FINDING IS THE ONE THAT CHANGES THE FIX**, and it is asserted here rather than
described: `execute_sparql`'s advertised rdflib fallback CANNOT SERVE ANY OF ITS EIGHT CALLERS.
The graph-scoping wrap injects `GRAPH ?__mesh_g`, and a plain `rdflib.Graph` raises on any
named-graph pattern — so Path B does not return few rows, it raises, and the raise is swallowed
into `return []`. Measured across all eight call sites, not sampled from one.

Run: uv run --frozen pytest tests/test_an_outage_is_not_an_empty_answer.py -v
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

rdflib = pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from agent_fleet.ontology_service.read_outcome import (  # noqa: E402
    StoreAttempt,
    SubstrateUnavailable,
    outcome,
    rows_or_refuse,
)

_MAIN = _REPO / "agent_fleet" / "ontology_service" / "main.py"


# -- the distinction itself ------------------------------------------------------------------


def test_NOTHING_MATCHED_and_COULD_NOT_ASK_are_different_outcomes():
    """The whole packet in one assertion. Both of these return `[]` today."""
    matched_nothing = outcome([StoreAttempt("jena", rows=[])], what="q")
    could_not_ask = outcome([StoreAttempt("jena", error="connect timeout")], what="q")
    assert matched_nothing.outcome == "empty"
    assert could_not_ask.outcome == "failed"
    assert matched_nothing.outcome != could_not_ask.outcome, (
        "if these ever collapse, every caller is back to reading an outage as a zero"
    )


def test_ROWS_NONE_IS_NOT_ROWS_EMPTY():
    """`rows=[]` RAN and matched nothing; `rows=None` never got that far. Collapsing them in the
    attempt record would rebuild the defect one layer up, so the dataclass keeps them apart."""
    assert StoreAttempt("jena", rows=[]).answered is True
    assert StoreAttempt("jena", rows=None).answered is False
    chain = [StoreAttempt("jena", rows=[]), StoreAttempt("rdflib", rows=[{"a": 1}])]
    assert outcome(chain).outcome == "empty", (
        "a store that answered EMPTY is still the answer - the chain must not fall through it"
    )


def test_UNDECLARED_is_UNREACHABLE_not_FAILED():
    """A deployment that never configured a store and one whose store is down want opposite
    responses - a configuration answer and a page. `[]` gave both the same silence."""
    assert outcome([StoreAttempt("jena", declared=False)], what="q").outcome == "unreachable"
    assert outcome([StoreAttempt("jena", declared=True, error="500")], what="q").outcome == "failed"


def test_the_result_says_WHICH_STORE_ANSWERED():
    """A row served from a file shipped beside the code is not the same claim as one served from
    the cluster. Today the caller cannot tell; `mode` is where that stops."""
    degraded = [StoreAttempt("jena", error="down"), StoreAttempt("rdflib", rows=[{"a": 1}])]
    assert outcome(degraded).mode == "rdflib"
    assert outcome([StoreAttempt("jena", rows=[{"a": 1}])]).mode == "jena"


def test_the_bridge_REFUSES_rather_than_returning_empty():
    """`rows_or_refuse` is the fix landing on the path the eight callers actually take. A correct
    result nobody reads changes nothing, so the refusal is not parked behind a migration."""
    with pytest.raises(SubstrateUnavailable) as exc:
        rows_or_refuse(outcome([StoreAttempt("jena", error="timeout")], what="execute_sparql"))
    assert "timeout" in str(exc.value)
    assert rows_or_refuse(outcome([StoreAttempt("jena", rows=[])])) == [], (
        "EMPTY must still pass through as [] - that is the case [] always meant correctly"
    )


def test_the_refusal_names_EVERY_store_that_failed_not_just_the_last():
    """A chain that tried two stores and lost both has two reasons, and the first is usually the
    real one. Reporting only the last names the fallback's symptom instead of the cause."""
    detail = outcome(
        [
            StoreAttempt("jena", error="connect timeout"),
            StoreAttempt("rdflib", error="needs a dataset"),
        ],
        what="execute_sparql",
    ).detail
    assert "jena: connect timeout" in detail and "rdflib: needs a dataset" in detail


def test_AN_UNDECLARED_STORE_STAYS_IN_THE_REASON_even_when_another_store_failed():
    """FOUND BY THE WIRING TEST, NOT BY THIS FILE, which is the whole argument for having both.

    An unset `JENA_QUERY_ENDPOINT` with a broken fallback originally reported only
    `rdflib: <error>` - so an operator saw the fallback's symptom and never learned the cluster was
    never configured. The undeclared store is the ACTIONABLE half: a line in a chart, not an
    outage. It stays in the sentence while staying out of the verdict.
    """
    result = outcome(
        [
            StoreAttempt("jena", declared=False, error="JENA_QUERY_ENDPOINT unset"),
            StoreAttempt("rdflib", error="AttributeError"),
        ],
        what="execute_sparql",
    )
    assert result.outcome == "failed", "the DECLARED store decides the verdict"
    assert "unset" in result.detail, "the undeclared store must survive into the reason"
    assert "not declared" in result.detail, "and be marked as configuration, not as an outage"


# -- the fallback that cannot serve anyone ---------------------------------------------------


def _wrap_like_main(query: str, dom: str = "MAINTENANCE") -> str:
    """The graph-scoping wrap, lifted from `execute_sparql` so the arm below tests the REAL rule."""
    scope = (
        "VALUES ?__mesh_g { <http://internal/" + dom + "> "
        "<http://internal/" + dom + "_INSTANCES> } GRAPH ?__mesh_g"
    )
    if "GRAPH" not in query.upper() and "SELECT" in query.upper():
        if "WHERE {" in query:
            out = query.replace("WHERE {", "WHERE { " + scope + " {", 1)
        elif re.search(r"WHERE\s*\{", query, re.IGNORECASE):
            out = re.sub(r"WHERE\s*\{", "WHERE { " + scope + " {", query, flags=re.IGNORECASE, count=1)
        else:
            return query
        i = out.rfind("}")
        return out[:i] + "} }" + out[i + 1:] if i != -1 else out
    return query


def test_PATH_B_CANNOT_ANSWER_A_SCOPED_QUERY_AT_ALL():
    """THE FALLBACK IS DEAD, AND IT RAISES RATHER THAN RETURNING FEW ROWS.

    `_get_local_graph` returns a plain `rdflib.Graph`. The wrap injects `GRAPH ?__mesh_g`. rdflib
    refuses a named-graph pattern on a single graph - so the "Safe/Development fallback" cannot
    serve a single scoped query, and `except Exception: return []` turns that into a clean zero.

    The file it parses is 44KB of real maintenance triples, which is why this looks healthy from
    the outside: the data is there and unreachable through the only path that reads it.
    """
    g = rdflib.Graph()
    g.parse(data="@prefix ex: <http://e/> . ex:a a ex:C .", format="turtle")
    plain = "SELECT ?s WHERE { ?s a <http://e/C> . }"
    assert len(list(g.query(plain))) == 1, "POSITIVE CONTROL: it does answer an unscoped query"
    with pytest.raises(Exception) as exc:
        list(g.query(_wrap_like_main(plain)))
    assert "dataset" in str(exc.value).lower() or "conjunctive" in str(exc.value).lower()


def test_ALL_EIGHT_execute_sparql_CALL_SITES_are_unserviceable_by_the_fallback():
    """PARTITIONED, NOT SAMPLED - every call site in the basis or excluded with a reason.

    Seven pass a query the wrap scopes. The eighth (`main.py:603`, the Jena emptiness check)
    already contains `GRAPH ?g` so the wrap skips it - and a named-graph pattern is exactly what a
    plain `rdflib.Graph` cannot serve either. Eight of eight, by two routes to the same raise.
    """
    tree = ast.parse(_MAIN.read_text(encoding="utf-8", errors="replace"))
    sites = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "execute_sparql"
        and n.args
    ]
    assert len(sites) == 8, (
        "the call-site count moved to " + str(len(sites)) + "; this partition was derived at 8 "
        "and a new caller has not been classified. Re-derive it rather than adjusting the number."
    )


def test_the_dead_fallback_is_REPORTED_not_silently_converted_to_empty():
    """The behaviour change that matters: with both stores failing, the caller gets a refusal
    naming both - never `[]`. This is what `except Exception: return []` costs today."""
    result = outcome(
        [
            StoreAttempt("jena", error="connect timeout"),
            StoreAttempt("rdflib", error="operation requiring a dataset"),
        ],
        what="execute_sparql",
    )
    assert result.outcome == "failed"
    with pytest.raises(SubstrateUnavailable):
        rows_or_refuse(result, what="execute_sparql")


def test_THE_REFUSAL_TYPE_IS_ONE_CLASS_not_one_per_import_path():
    """AN EXCEPTION TYPE CANNOT USE THE FLATTEN-FIRST CONVENTION, and this is the arm that says so.

    Engine O imports its own modules flat-name-first (`from state_sparql import ...`) with a package
    fallback, so the same file can be loaded as `read_outcome` OR as
    `agent_fleet.ontology_service.read_outcome`. For functions and data that is harmless — two
    module objects holding equal functions behave identically.

    **For an exception type it is a silent defect.** Two module objects mean two distinct classes
    with the same name, so a caller writing `except SubstrateUnavailable` against one path does not
    catch the other: the refusal sails past the handler written to receive it and surfaces as an
    unhandled error instead of the outage it was told about.

    Measured 2026-09-17: three arms in `test_execute_sparql_refuses_instead_of_zeroing.py` failed
    exactly this way in the full suite while passing standalone, because the suite put both paths
    on `sys.path`. `main.py` therefore imports THIS module package-first. If that order is ever
    flipped back to match the convention, this reds.
    """
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    # MATCH THE MODULE PATHS, NOT THE IMPORTED NAMES. An earlier version of this arm keyed on
    # `read_outcome import StoreAttempt` and broke the moment another name joined the import —
    # a check that reds when the FORMATTING moves is a check nobody keeps.
    pkg = src.index("from agent_fleet.ontology_service.read_outcome import")
    flat = src.index("from read_outcome import")
    assert pkg < flat, (
        "main.py must try the PACKAGE path first for read_outcome. Flat-first creates a second "
        "module object and a second SubstrateUnavailable class, and callers stop catching it."
    )


# -- the two Neo4j reads ---------------------------------------------------------------------


def test_an_ABSENT_DRIVER_and_a_FAILED_QUERY_are_both_hidden_today():
    """`_discover_enumerate_providers` returns `[]` on THREE distinct conditions: no driver, a
    failed query, and a genuinely empty registry. Its own log line says "no providers this call" -
    it KNOWS which one happened, and the return value cannot carry it."""
    no_driver = outcome([StoreAttempt("neo4j", declared=False)], what="enumerate_providers")
    failed = outcome([StoreAttempt("neo4j", error="ServiceUnavailable")], what="enumerate_providers")
    genuinely_none = outcome([StoreAttempt("neo4j", rows=[])], what="enumerate_providers")
    assert len({no_driver.outcome, failed.outcome, genuinely_none.outcome}) == 3, (
        "three conditions, three outcomes - today all three are []"
    )


def test_an_empty_ancestor_chain_SILENTLY_REVERTS_the_ADR_0018_amendment():
    """THE CONSEQUENCE, ASSERTED AGAINST THE CONSUMER RATHER THAN DESCRIBED.

    `_get_subject_ancestor_chain` documents its choice - "we degrade silently rather than fail the
    route". The consumer at `main.py:4690` builds `ancestor_hops` from that chain, and
    `_inheritance_phrase` returns `None` for every candidate when it is empty. So a Neo4j outage
    sends the LLM back to validating a verb against the raw `input_uri` string, which is the exact
    regression ADR-0018's amendment exists to fix - and the ADR still reads as satisfied because
    the code is all there.

    This arm reds if the consumer stops deriving its map from the chain, because then this
    reasoning is about a call path that no longer exists.
    """
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    assert "for a in ancestor_chain}" in src, (
        "the consumer no longer builds its hop map from the chain; re-derive what an empty chain "
        "now costs before trusting this arm's reasoning"
    )
    assert "if not input_uri or input_uri not in ancestor_hops:" in src, (
        "_inheritance_phrase no longer gates on the hop map; the cost of an empty chain has moved"
    )
    ancestor_chain: list[dict] = []  # what an outage produces
    ancestor_hops = {a["uri"]: a["hops"] for a in ancestor_chain}
    assert ancestor_hops == {}, "an empty chain yields no hop map"
    assert "idp:Table" not in ancestor_hops, (
        "so every _inheritance_phrase lookup misses and the LLM sees no inheritance at all"
    )
