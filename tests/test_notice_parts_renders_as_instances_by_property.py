"""`mesh:NoticePartSet` draws as an INSTANCES_BY_PROPERTY table, not as its own JSON.

WHY THIS EXISTS. On rev 181 "which parts does PCN26-184 affect" routed correctly to engine-o and
answered both parts with their provenance, and the card was a KNOWLEDGE_DOCUMENT showing the
verb's JSON in a code block: nothing bound the output type, and the archetype had no server path.
Roll #23 adds the three server-side pieces; this file is their conformance case (runbook site 5):

  * the producer: `notice_parts.instances_by_property`, additive on the ok answer;
  * the projector: `_PROJECTED_ARCHETYPES["INSTANCES_BY_PROPERTY"]`;
  * the capability row: `mesh:NoticePartSet -> mesh:InstancesByProperty` in capabilities.py.

The cortex half (the DERIVED_BINDINGS row) is held to this one by the fleet mirror seal in
tests/finance/test_the_wire_carries_what_the_engine_declares.py, not here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.ontology_service import notice_parts as np_mod
from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
from tests.planning.test_planning_archetypes_are_projected import _fns
from tests.test_notice_parts_provenance import NOTICE, PARTS, _row

_IBP = Path(__file__).resolve().parents[2] / "cortex-ui" / "src" / "components" / "InstancesByProperty"
ARCH = "INSTANCES_BY_PROPERTY"


def _project(answer):
    """Through the projector exactly as render_ui calls it: the supervisor's wrapper list."""
    wrapped = [{"persona": "SAFETY_ENGINEER", "expert_response": answer}]
    return _fns()["_project_planning_archetype"](ARCH, wrapped, "SAFETY_ENGINEER", None)


def _passthrough() -> tuple:
    return _fns()["_PROJECTED_ARCHETYPES"][ARCH]


def test_THE_ANSWER_PROJECTS_TO_A_TABLE_OF_ITS_PARTS():
    answer = np_mod.notice_parts([_row()], NOTICE)
    got = _project(answer)
    assert got is not None, "the ok answer projected nothing; the card degrades to its JSON"
    assert got["archetype"] == ARCH
    assert got["title"] == f"Parts affected by {NOTICE}"
    assert got["target"] == {"domain": "SUSTAINMENT", "class": "pcn:Component"}
    assert got["row_identity"] == {"key": "instance", "iri": True, "display_from_local_name": True}
    assert [r["mpn"] for r in got["rows"]] == sorted(PARTS)
    # The table and the provenance name the same parts: one row per source, same IRI.
    assert [r["instance"] for r in got["rows"]] == [s["uri"] for s in answer["sources"]]
    assert "state_vocabulary" not in got, "an unfiltered answer must not invent filter tabs"


def test_EVERY_ROW_KEY_IS_A_DECLARED_COLUMN_AND_THE_IDENTITY_NAMES_ONE():
    got = _project(np_mod.notice_parts([_row()], NOTICE))
    cols = [c["key"] for c in got["columns"]]
    assert got["row_identity"]["key"] in cols
    for r in got["rows"]:
        assert set(r) == set(cols), f"row keys {sorted(r)} != columns {cols}: a blank or lost cell"


def test_THE_ADDITION_IS_ADDITIVE_THE_VERB_STILL_ANSWERS_WHAT_IT_DID():
    answer = np_mod.notice_parts([_row()], NOTICE)
    for k in ("status", "verb", "output_uri", "notice_id", "notice_type", "parts", "count",
              "message", "data", "sources"):
        assert k in answer, k
    assert answer["count"] == len(answer["rows"]) == len(answer["parts"])


@pytest.mark.parametrize("answer", [
    np_mod.notice_parts([_row(mpns=[])], NOTICE),   # a known notice naming no part
    np_mod.notice_parts([], NOTICE),                 # unknown_notice
    np_mod.notice_parts([], ""),                     # notice_required
], ids=["no_parts", "unknown_notice", "notice_required"])
def test_NO_PARTS_PROJECTS_NOTHING_SO_THE_PROSE_CARD_SAYS_WHY(answer):
    """An empty table would read as "checked, none" for a refusal. The projector refuses an empty
    list, render_ui degrades, and the document card carries the verb's own message."""
    assert _project(answer) is None
    assert answer["message"]


def test_THE_CAPABILITY_ROW_BINDS_THE_VERBS_OUTPUT_TYPE_AND_ITS_FIELDS_ARRIVE():
    rows = [c for c in PRESENTATION_CAPABILITIES if c["subject_uri"] == "mesh:NoticePartSet"]
    assert len(rows) == 1, rows
    cap = rows[0]
    assert (cap["object_uri"], cap["archetype"]) == ("mesh:InstancesByProperty", ARCH)
    assert np_mod.OUTPUT_URI.rsplit("#", 1)[-1] == "NoticePartSet"
    answer = np_mod.notice_parts([_row()], NOTICE)
    assert set(cap["expected_fields"]) <= set(answer), set(cap["expected_fields"]) - set(answer)


def test_THE_PASSTHROUGH_IS_WHAT_THE_VIEW_READS():
    """Derived from cortex's own view, so the tuple cannot drift from the reader in either
    direction: a field the view reads and the tuple drops is a blank, and a field the tuple
    carries that the view never reads is advertised to nobody."""
    view = _IBP / "InstancesByPropertyView.tsx"
    if not view.is_file():
        pytest.skip("cortex-ui is not a sibling on disk")
    m = re.search(r"const\s*\{([^}]*)\}\s*=\s*payload\s*;", view.read_text(encoding="utf-8"))
    assert m, "the view's payload destructure moved; this derivation reads nothing"
    read = {f.strip() for f in m.group(1).split(",") if f.strip()}
    key, passthrough = _passthrough()
    assert read == {key, *passthrough}


def test_THE_PROJECTED_CARD_CARRIES_EVERY_REQUIRED_FIELD_OF_CORTEX_S_TYPE():
    types = _IBP / "types.ts"
    if not types.is_file():
        pytest.skip("cortex-ui is not a sibling on disk")
    body = re.search(r"interface InstancesByPropertyPayload\s*\{(.*?)\n\}",
                     types.read_text(encoding="utf-8"), re.S)
    assert body, "InstancesByPropertyPayload moved; this derivation reads nothing"
    src = re.sub(r"/\*.*?\*/|//[^\n]*", "", body.group(1), flags=re.S)
    required = set(re.findall(r"^\s*(\w+)\s*:", src, re.M))
    assert {"archetype", "title", "columns", "rows"} <= required, required
    got = _project(np_mod.notice_parts([_row()], NOTICE))
    assert required <= set(got), required - set(got)


def test_CONTROL_A_PASSTHROUGH_WITHOUT_COLUMNS_FAILS_THE_REQUIRED_FIELD_CHECK():
    """The check above must be able to fail: drop `columns` from the tuple and the card the view
    would map over is missing its headers."""
    ns = _fns()
    key, passthrough = ns["_PROJECTED_ARCHETYPES"][ARCH]
    ns["_PROJECTED_ARCHETYPES"][ARCH] = (key, tuple(f for f in passthrough if f != "columns"))
    wrapped = [{"persona": "X", "expert_response": np_mod.notice_parts([_row()], NOTICE)}]
    got = ns["_project_planning_archetype"](ARCH, wrapped, "X", None)
    assert "columns" not in got
