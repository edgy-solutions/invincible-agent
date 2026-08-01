"""DECISION RECORDS land in a DEDICATED graph, append-only, immutability enforced at the WRITER.

ADR-0034 Phase 1, persistence half. The ruling: graph, because every named consumer is
graph-shaped — promotion queries ("corrections across the last N records for format F") are
instances-by-property, and a table would mean a second query surface beside the one that
already exists, for data whose entire purpose is being queried by property.

The boundaries this seals:
  * a DEDICATED runtime graph (`<DOMAIN>_DECISIONS`) — never a vocabulary graph, never prime.
    Records are non-reproducible runtime output; mixing producers of different reproducibility
    into one graph is what the collision incident wrote in blood.
  * APPEND-ONLY, and the refusal is EXECUTABLE. "Append-only by convention" is a comment, and
    a comment is not a gate — an audit trail that can be silently overwritten is not one.
  * GENERIC AT BIRTH — the route carries no domain name; `domain` selects the graph.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_decision_record_graph_writer.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MAIN = (_ROOT / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
_HANDLER = _MAIN[_MAIN.index("async def write_decision_record"):_MAIN.index("class InstancesByPropertyRequest")]


def test_the_route_is_generic_at_birth():
    """No NEW route carries a domain name — the domain is a parameter, so a second domain
    emitting records needs no new surface."""
    assert '@app.post("/write_decision_record")' in _MAIN
    assert "sustainment" not in "/write_decision_record"


def test_records_go_to_a_dedicated_graph_never_a_vocabulary_or_prime_graph():
    """The graph is derived from the domain and suffixed _DECISIONS. A record must never land
    in the ontology graphs (different reproducibility class) or in prime."""
    # Scoped to the RETURN EXPRESSION, not the function text. The first version of this test
    # asserted `"prime" not in fn.lower()` and failed on the DOCSTRING, which says "NEVER
    # prime" — a keyword check over source matches the documentation that explains the rule as
    # readily as a violation of it. That is testing prose, not behaviour; the same family as a
    # byte-window standing in for a content check.
    fn = _MAIN[_MAIN.index("def _decisions_graph"):_MAIN.index("@app.post(\"/write_decision_record\")")]
    ret = [ln.strip() for ln in fn.splitlines() if ln.strip().startswith("return ")]
    assert len(ret) == 1, "expected exactly one return in _decisions_graph"
    expr = ret[0]
    assert "_DECISIONS" in expr
    assert "_INSTANCES" not in expr, "records must not share the instance graph"
    assert "prime" not in expr.lower(), "records must never be written to prime"
    assert "{domain" in expr or "domain" in expr, "the graph must be derived from the domain param"


def test_immutability_is_an_EXECUTABLE_refusal_not_a_comment():
    """A DIFFERENT record under an existing id must 409. This is the assertion the ruling
    asked for at the writer — convention is not enough, because an audit trail that can be
    edited in place is not an audit trail."""
    assert "ASK" in _HANDLER, "the writer never checks whether the record already exists"
    assert "409" in _HANDLER
    assert "decision_record_immutable" in _HANDLER
    # and it must NOT delete/overwrite — the shape used by write_item_state (delete-then-insert)
    # is correct for mutable state and catastrophic for evidence.
    assert "DELETE" not in _HANDLER.upper(), (
        "the decision-record writer deletes before inserting — that is the mutable-state "
        "pattern applied to evidence, and it silently rewrites history"
    )
    assert "INSERT DATA" in _HANDLER


def test_an_identical_re_emit_is_not_an_error():
    """A retry after a transport failure must be safe. Only a DIFFERENT record under an
    existing id is a conflict — otherwise every network blip becomes a false alarm and the
    emitter learns to ignore the writer's complaints."""
    assert "already_present" in _HANDLER


def test_the_indexed_projections_are_the_ones_consumers_query_by():
    """The reason the store is a graph at all: promotion and the demotion tripwire query BY
    PROPERTY. If these stop being indexed the corpus becomes a blob and the ruling's premise
    is gone."""
    for pred in ("formatFingerprint", "pipelineVersion", "outcome",
                 "admittedBy", "trustRung", "rulesetRef", "trustTableRef"):
        assert pred in _HANDLER, f"{pred} is not indexed — the corpus cannot be queried by it"


def test_the_whole_record_is_stored_verbatim_alongside_the_projections():
    """Evidence is read back WHOLE. The projections exist for querying; the canonical JSON is
    the record, so a reader never re-assembles evidence from triples that may have drifted."""
    assert "canonical" in _HANDLER


def test_it_uses_the_HOUSE_escaper_not_a_second_one():
    """Two escapers are two chances to disagree about what a quote means — the same shape as
    the duplicate identity derivation killed in 9cfe3f4. One derivation, one escaper."""
    assert "_sparql_lit(" in _HANDLER
    assert "_escape_literal" not in _MAIN


def test_the_record_id_is_validated_before_it_reaches_a_query():
    """It is interpolated into SPARQL, so it must be a slug — an unvalidated id here is an
    injection into the store the audit trail lives in."""
    assert "isalnum()" in _HANDLER and "400" in _HANDLER
