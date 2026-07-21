"""Tests for the ADR-0030 rule-2 degrade decision (Engine F).

The load-bearing property: a deterministic LineageTopology is EDGELESS BY
DESIGN and must render as a document — it must NEVER reach RenderAsTopology
(which would invent edges and time out). The decision is keyed on the
``outcome`` DISCRIMINANT, not on "edges happens to be empty", so a genuine
sparse graph still renders as a graph.

Authored data only — invented names, generic platform slugs.
"""
from __future__ import annotations

from agent_fleet.presentation_agent.topology_degrade import edgeless_lineage_document

PERSONA = "OPS_OPERATOR"


def _sd(outcome, **extra):
    base = {"outcome": outcome, "asset_label": "Sales Dashboard",
            "edges": [], "match_count": 0, "upstream_tables": []}
    base.update(extra)
    return base


# --- the deterministic (edgeless) answer degrades to a document -------------

def test_list_outcome_degrades_to_document_with_summary():
    sd = _sd("list", match_count=2, upstream_tables=["orders", "customers"])
    doc = edgeless_lineage_document(sd, "depends on 2 warehouse_a tables: orders; customers.", PERSONA)
    assert doc is not None
    comp = doc["components"][0]
    assert comp["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert comp["source_persona"] == PERSONA
    assert comp["subject_concept"] == "Sales Dashboard"
    assert "orders" in comp["markdown_content"] and "customers" in comp["markdown_content"]


def test_every_say_so_outcome_degrades_not_just_the_list():
    # none / couldnt_locate / ambiguous / unrecognized_platform / lineage_error
    for outcome in ("none", "couldnt_locate", "ambiguous",
                    "unrecognized_platform", "lineage_error"):
        doc = edgeless_lineage_document(_sd(outcome), "the honest say-so text", PERSONA)
        assert doc is not None, f"{outcome} should degrade to a document"
        assert doc["components"][0]["markdown_content"] == "the honest say-so text"


def test_structured_data_may_arrive_as_a_dict_already():
    # main.py JSON-decodes a string payload before calling this; here we pin
    # the dict contract the pure function actually receives.
    doc = edgeless_lineage_document(_sd("none"), "no matching upstreams.", PERSONA)
    assert doc is not None


def test_empty_summary_still_yields_a_coherent_document():
    doc = edgeless_lineage_document(_sd("lineage_error"), "", PERSONA)
    assert doc is not None
    assert doc["components"][0]["markdown_content"] == "No lineage content available."


# --- a real graph is NOT degraded — it must reach the topology renderer -----

def test_no_discriminant_means_real_topology_render():
    # A payload with edges but no `outcome` is a genuine graph from some other
    # producer; the degrade must decline (return None) so RenderAsTopology runs.
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
    assert edgeless_lineage_document(graph, "a real graph", PERSONA) is None


def test_discriminant_but_nonempty_edges_is_a_real_graph():
    # If a future deterministic path DID produce edges, it is a real topology;
    # the discriminant alone must not force a document — the edges decide.
    sd = _sd("list", edges=[{"from": "x", "to": "y"}], match_count=2)
    assert edgeless_lineage_document(sd, "has edges", PERSONA) is None


def test_non_dict_payload_declines():
    assert edgeless_lineage_document(None, "x", PERSONA) is None
    assert edgeless_lineage_document("not-a-dict", "x", PERSONA) is None
    assert edgeless_lineage_document({"outcome": 123}, "x", PERSONA) is None  # outcome not a str
