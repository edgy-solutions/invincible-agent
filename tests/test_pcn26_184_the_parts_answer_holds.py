"""PCN26-184, the Friday walk's notice: the parts answer, its sources and its provenance floor.

The runbook (`sessions/friday-demo-runbook.md` section 3) asks "which parts does PCN26-184
affect" and expects a parts table with rows 5530-184 and 5530-185 and the floor
`{user-drop, [], 0}`, measured x3 on rev 182. This file holds two things that walk depends on:

1. MPN ON SOURCES. `notice_parts._source` puts `mpn` and `notice_id` on every source, and the
   bff's `_project_sources` dropped both: the citation reached the browser as a label and a URI.
   Driven through `_sources_event_payload`, the function that emits the SSE `sources` event.
2. THE ROW AND ITS FLOOR. Every row the InstancesByProperty card draws joins to a source with a
   valid ProvenanceBlock, and the same answer's floor is `{user-drop, [], 0}`. The controls are
   the same drop UNPROMOTED (listed) and a seeded notice (unstamped): a table drawn from either
   must not read as a promoted drop.

THE FIXTURE. Identity, parts and cast are the runbook's (rev 182). The shape is the rev-180
PCN26-182 probe's (`tests/test_notice_parts_provenance.py`). The ingest id is a STAND-IN: the
runbook elides it, and no assertion here depends on its value, only on its presence.
"""
from __future__ import annotations

from agent_fleet.ontology_service import notice_parts as np_mod
from src.iagent import gateway as _gw
from src.iagent.provenance import validate_provenance
from tests.planning.test_planning_archetypes_are_projected import _fns
from tests.test_notice_parts_provenance import _NOTICE, _SEEDED, _Driver, _mat, _row

NOTICE = "PCN26-184"
PARTS = ["5530-184", "5530-185"]
INGEST_ID = "sha256:" + "184" * 21 + "0"   # stand-in, see the module docstring
_N184 = {**_NOTICE, "id": NOTICE, "provenance_ingest_id": INGEST_ID,
         "provenance_ingest_run": f"user-drop:{INGEST_ID}"}
ARCH = "INSTANCES_BY_PROPERTY"


def _answer(**kw):
    return np_mod.read_notice_parts(_Driver([_row(notice=_N184, mpns=PARTS, **kw)]), NOTICE)


def _card(answer):
    wrapped = [{"persona": "SAFETY_ENGINEER", "expert_response": answer}]
    return _fns()["_project_planning_archetype"](ARCH, wrapped, "SAFETY_ENGINEER", None)


# ── 1. mpn on sources, through the bff ──────────────────────────────────────────────────────

def test_EVERY_SOURCE_REACHES_THE_EVENT_WITH_ITS_PART_AND_ITS_NOTICE():
    projected, _ = _gw._sources_event_payload(_mat(_answer()["sources"]))
    assert [s["mpn"] for s in projected] == PARTS
    assert {s["notice_id"] for s in projected} == {NOTICE}


def test_CONTROL_A_SOURCE_THAT_NEVER_CARRIED_AN_MPN_DOES_NOT_GROW_ONE():
    """The projection passes the field through; it does not invent it."""
    bare = [{"type": "document", "label": "x", "uri": "http://e/x"}]
    projected, _ = _gw._sources_event_payload(_mat(bare))
    assert "mpn" not in projected[0] and "notice_id" not in projected[0]


# ── 2. the row and its floor ────────────────────────────────────────────────────────────────

def _rows_and_floor(answer):
    card = _card(answer)
    projected, floor = _gw._sources_event_payload(_mat(answer["sources"]))
    return card, {s["uri"]: s for s in projected}, floor


def test_EVERY_ROW_JOINS_A_STAMPED_SOURCE_AND_THE_FLOOR_IS_A_PROMOTED_DROP():
    card, by_uri, floor = _rows_and_floor(_answer())
    assert card["title"] == f"Parts affected by {NOTICE}"
    assert [r["mpn"] for r in card["rows"]] == PARTS
    for r in card["rows"]:
        src = by_uri.get(r["instance"])
        assert src is not None, f"row {r['instance']} cites no source"
        assert src["mpn"] == r["mpn"], "the row and its citation name different parts"
        validate_provenance(src["provenance"])
        assert src["promoted_by"] == "human:bob@example.com"
    assert floor == {"obtained_via": "user-drop", "ingest_ids": [], "unidentified": 0}


def test_CONTROL_THE_SAME_TABLE_UNPROMOTED_LISTS_ITS_DROP():
    """Same rows, no PROMOTION fact: the card is identical and the floor is not."""
    card, _, floor = _rows_and_floor(_answer(promoted_by=None))
    assert [r["mpn"] for r in card["rows"]] == PARTS
    assert floor == {"obtained_via": "user-drop", "ingest_ids": [INGEST_ID], "unidentified": 0}


def test_CONTROL_A_TABLE_FROM_A_SEEDED_NOTICE_READS_UNSTAMPED():
    """The card draws for a seeded notice too. Its floor must say `unstamped`, so a seeded table
    never reads as a promoted drop. This is the documented gap: nothing stamps seeded notices."""
    seeded = np_mod.read_notice_parts(
        _Driver([_row(notice=_SEEDED, mpns=PARTS, dropped_by=None, promoted_by=None)]),
        _SEEDED["id"])
    card, by_uri, floor = _rows_and_floor(seeded)
    assert [r["mpn"] for r in card["rows"]] == PARTS
    assert all("provenance" not in by_uri[r["instance"]] for r in card["rows"])
    assert floor["obtained_via"] == "unstamped"
