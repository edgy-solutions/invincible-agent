"""pcn state SPARQL builders are parse-valid — the rdflib discipline the TTLs get, for SPARQL.

The f-string/plain-string brace bug that cost a build/roll cycle (four literal braces -> Fuseki 400)
is caught here in milliseconds. Any new SPARQL template belongs in pcn_state_sparql with a test here.

Needs rdflib:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with rdflib pytest ../../tests/test_pcn_state_sparql.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

_REPO = Path(__file__).resolve().parent.parent
_EO = _REPO / "agent_fleet" / "ontology_service"
for p in (str(_EO), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rdflib.plugins.sparql.parser import parseUpdate  # noqa: E402
from agent_fleet.ontology_service.pcn_state_sparql import (  # noqa: E402
    build_disposition_state_update, build_parts_by_state_query,
)

_S = "http://internal/components/NSR01L30NXT5G"


def test_update_parses():
    """parseUpdate validates SYNTAX — a brace/grammar error raises here, in ms, not at Fuseki
    (execution needs a Dataset for named graphs; syntax is what the brace bug broke)."""
    upd = build_disposition_state_update(_S, "dispatchQualification", "IPCN25300X:NSR01L30NXT5G", "rules@v1")
    parseUpdate(upd)


def test_update_without_ruleset_parses():
    parseUpdate(build_disposition_state_update(_S, "archive", "IPCN25300X:X"))


def test_update_escapes_quotes_without_breaking():
    upd = build_disposition_state_update(_S, 'weird"state', 'r"ef', 'rule"set')
    parseUpdate(upd)  # escaped quotes must not break the literal / the grammar


def test_query_prepares():
    from rdflib.plugins.sparql import prepareQuery
    prepareQuery(build_parts_by_state_query("dispatchLTB"))


def test_update_writes_only_to_the_instances_graph():
    upd = build_disposition_state_update(_S, "dispatchLTB", "N:X")
    assert "GRAPH <http://internal/SUSTAINMENT_INSTANCES>" in upd
    assert upd.count("{") == upd.count("}")   # the brace bug, directly
