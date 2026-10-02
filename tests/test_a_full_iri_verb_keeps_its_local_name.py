"""A full-IRI verb names the same relationship type as its compact form, and the writer refuses
a type that still carries an IRI.

THE RESIDUE, READ 2026-10-01. The sandbox graph held an edge of relationship type
`//invincible-agent/mesh#explain`, from engine-docs' pre-09-17 registration of the verb as
`http://invincible-agent/mesh#explain`, beside the `explain` edge the compact `mesh:explain` wrote.
The registrar's predicate family derives the type with `v2_substrate._get_verb_local_name`, which
split at the first `:` whatever the form, so the scheme colon was taken for a CURIE prefix.

TWO DEFENCES, SEALED SEPARATELY:
  * the family's function reduces both forms of a verb to one local name;
  * `Neo4jGraphWriter.write_edge` refuses a type that still carries `:`, `/` or `#`, whichever
    family function produced it. A type is a parameter to apoc, so Neo4j itself accepts the
    mangled one, and nothing downstream would ever say so.

Driven through the real writer configured with the registrar's real `PREDICATE_EDGE_FAMILY`, on a
recording driver: the `rel_type` the writer hands the query is the observable.
"""
from __future__ import annotations

from typing import Any

import pytest

from iagent_mesh.interfaces import EdgeIdentity, Initiator
from iagent_mesh.write_results import MeshWriteResult

from agent_fleet.mesh_registrar.v2_substrate import (
    PARAMETERISED_BY_FAMILY,
    PREDICATE_EDGE_FAMILY,
    _get_verb_local_name,
)
from agent_fleet.utils.mesh_writers.neo4j_graph import Neo4jGraphWriter

_PERSON = Initiator(subject="test-person", kind="person")
_REFUSED = MeshWriteResult.refused("x").outcome


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, driver):
        self._d = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self._d.queries.append(params)
        return _Result([{"n": 1}])


class _Driver:
    def __init__(self):
        self.queries: list[dict] = []

    def session(self):
        return _Session(self)


def _write(family: dict, verb: str) -> tuple[Any, list[dict]]:
    driver = _Driver()
    result = Neo4jGraphWriter(driver=driver, **family).write_edge(
        _PERSON,
        identity=EdgeIdentity(subject="mesh:DocPage", verb=verb,
                              object="docs:DocExplanation", key="urn:tool:engine-docs"),
    )
    return result, driver.queries


# ── 1. THE FAMILY'S FUNCTION: BOTH FORMS, ONE LOCAL NAME ─────────────────────────────────────

@pytest.mark.parametrize("verb, local", [
    ("http://invincible-agent/mesh#explain", "explain"),      # the residue's own verb
    ("https://invincible-agent/mesh#lookupOwnership", "lookupOwnership"),
    ("http://invincible-agent/mesh/explain", "explain"),      # a slash namespace
    ("mesh:explain", "explain"),                              # control: the compact form
    ("explain", "explain"),                                   # control: a bare name
])
def test_every_form_of_a_verb_reduces_to_its_local_name(verb, local):
    got = _get_verb_local_name(verb)
    assert got == local, f"{verb!r} reduced to {got!r}, not {local!r}"


# ── 2. THROUGH THE REAL WRITER, WITH THE REGISTRAR'S REAL FAMILY ─────────────────────────────

def test_the_full_iri_writes_the_same_type_as_the_compact_form():
    full, full_q = _write(PREDICATE_EDGE_FAMILY, "http://invincible-agent/mesh#explain")
    compact, compact_q = _write(PREDICATE_EDGE_FAMILY, "mesh:explain")

    assert compact.applied and [q["rel_type"] for q in compact_q] == ["explain"], (compact, compact_q)
    assert full.applied, f"the full-IRI verb's write was not applied: {full}"
    assert [q["rel_type"] for q in full_q] == ["explain"], (
        f"the full-IRI verb wrote type {[q['rel_type'] for q in full_q]}; the compact form "
        "writes 'explain'")
    # The verb property keeps the form the caller sent: only the TYPE is reduced.
    assert full_q[0]["identity"]["iri"] == "http://invincible-agent/mesh#explain", full_q[0]


# ── 3. THE WRITER REFUSES A TYPE THAT STILL CARRIES AN IRI ───────────────────────────────────

_SPLIT_AT_FIRST_COLON = dict(PREDICATE_EDGE_FAMILY, relationship_type=lambda v: v.split(":", 1)[1])


@pytest.mark.parametrize("verb", [
    "http://invincible-agent/mesh#explain",   # -> //invincible-agent/mesh#explain
    "urn:x:explain",                          # -> x:explain
])
def test_the_writer_refuses_a_type_that_still_carries_an_iri(verb):
    """The pre-fix family function, kept here as a FIXTURE: the writer must refuse what it made,
    and must refuse it before the store is asked."""
    result, queries = _write(_SPLIT_AT_FIRST_COLON, verb)
    assert result.outcome == _REFUSED, f"the writer did not refuse a write of type {verb.split(':', 1)[1]!r}"
    assert queries == [], f"the refused write still reached the store: {queries}"
    assert "relationship type" in (result.detail or ""), result


def test_a_fixed_type_and_a_compact_verb_still_write():
    """CONTROL: the refusal must not touch the types the fleet writes today."""
    fixed, fixed_q = _write(PARAMETERISED_BY_FAMILY, "mesh:explain")
    assert fixed.applied and [q["rel_type"] for q in fixed_q] == ["PARAMETERISED_BY"], (fixed, fixed_q)
    derived, derived_q = _write(_SPLIT_AT_FIRST_COLON, "mesh:explain")
    assert derived.applied and [q["rel_type"] for q in derived_q] == ["explain"], (derived, derived_q)
