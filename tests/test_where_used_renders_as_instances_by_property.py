"""`mesh:WhereUsedSet` draws as an INSTANCES_BY_PROPERTY table.

The producer is `where_used.where_used`; the capability row is in presentation_agent/capabilities.py;
the class is declared in setup/ontologies/mesh_system.ttl.

Run: uv run pytest tests/test_where_used_renders_as_instances_by_property.py -q
"""
from __future__ import annotations

from pathlib import Path

from agent_fleet.ontology_service import where_used as w
from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from tests.test_where_used_rolls_up_through_every_level import ALICE, ask, ident

REPO = Path(__file__).resolve().parents[1]


def _ok():
    got = ask(ident("P"), ALICE)
    assert got["status"] == "ok"
    return got


def test_THE_ENVELOPE_CARRIES_THE_TABLE_PARTS_AND_ONE_ROW_PER_ANSWER_ROW():
    got = _ok()
    for key in ("title", "columns", "rows", "row_identity", "target"):
        assert key in got, key
    assert len(got["rows"]) == len(got["where_used"]) == got["count"]
    assert got["target"] == {"domain": w.DOMAIN, "class": "ps:Part"}
    assert "synthetic fixture" in got["title"] and "as_designed" in got["title"]
    keys = {c["key"] for c in got["columns"]}
    assert all(keys <= set(r) for r in got["rows"])
    assert got["row_identity"]["key"] in got["rows"][0]
    assert got["data"] == got["message"] and got["output_uri"] == w.OUTPUT_URI


def test_GROUP_BY_NAMES_A_COLUMN_KEY_PRESENT_IN_EVERY_ROW():
    got = _ok()
    assert got["group_by"] in {c["key"] for c in got["columns"]}
    assert all(got["group_by"] in r for r in got["rows"])


def test_EVERY_ENVELOPE_TABLE_PART_SURVIVES_THE_PROJECTOR_PASSTHROUGH():
    """The projector carries `rows` plus a declared tuple and drops the rest silently; `group_by`
    is envelope-level, so it reaches cortex only if INSTANCES_BY_PROPERTY declares it."""
    from tests.finance.test_the_wire_carries_what_the_engine_declares import _projector_passthrough

    key, carried = _projector_passthrough()["INSTANCES_BY_PROPERTY"]
    assert key == "rows"
    got = _ok()
    for part in ("title", "target", "columns", "row_identity", "group_by"):
        assert part in got and part in carried, part


def test_THE_CAPABILITY_ROW_EXISTS_FOR_THE_OUTPUT_CLASS():
    rows = [c for c in PRESENTATION_CAPABILITIES if c["subject_uri"] == "mesh:WhereUsedSet"]
    assert len(rows) == 1 and rows[0]["archetype"] == "INSTANCES_BY_PROPERTY"
    assert w.OUTPUT_URI.rsplit("#", 1)[1] == "WhereUsedSet"


def test_THE_ONTOLOGY_DECLARES_THE_CLASS():
    ttl = (REPO / "setup/ontologies/mesh_system.ttl").read_text(encoding="utf-8")
    assert "\nmesh:WhereUsedSet a owl:Class" in ttl
