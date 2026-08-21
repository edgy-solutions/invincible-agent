"""ADR-0017 amendment: a malformed capability registration is REFUSED AT THE DOOR.

Before this check, /register_frontend_capabilities accepted everything -- it logged the
payload and returned accepted=len(capabilities). A frontend could advertise an unknown
archetype or a contract declaring no fields, and the first sign of trouble was a render
that produced nothing: the failure discovered at the far end of the pipeline.

These tests pin the two properties that matter and are easy to lose:
  * a refused row is REPORTED with its index, archetype and reason -- never dropped;
  * a LEGACY row carrying no typed contract stays ADMISSIBLE, because migration is
    row-by-row and refusing untyped rows would break every frontend on ship day.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_capability_admission.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent.capability_admission import (  # noqa: E402
    KNOWN_ARCHETYPES,
    validate_capability,
    validate_registration,
)

_DERIVED = {
    "archetype": "CHART_WIDGET",
    "subject_uri": "mesh:DatasetAnalysisReport",
    "object_uri": "mesh:ChartWidget",
    "contract": {
        "fields": {"chart_data": {"encoding": "json-string"}},
        "refusalReasons": ["no rows", "no numeric column"],
    },
}

_LEGACY = {
    "archetype": "KNOWLEDGE_DOCUMENT",
    "subject_uri": "mesh:OwnershipFact",
    "object_uri": "mesh:KnowledgeDocument",
}


def test_a_well_formed_derived_capability_is_admitted():
    assert validate_capability(_DERIVED) is None


def test_a_legacy_row_without_a_typed_contract_is_STILL_admitted():
    """Migration is row-by-row. Slice 1 derives CHART_WIDGET and leaves nine hand-authored
    rows; refusing untyped rows would refuse nine real capabilities on ship day."""
    assert validate_capability(_LEGACY) is None


def test_an_unknown_archetype_is_refused():
    r = validate_capability({**_DERIVED, "archetype": "HOLOGRAM"})
    assert r is not None
    assert "unknown archetype" in r["reason"]


@pytest.mark.parametrize("key", ["subject_uri", "object_uri"])
def test_an_empty_graph_key_is_refused(key):
    """These are the lookup keys. A registration with an empty one can never be found,
    so accepting it stores a row that is guaranteed dead."""
    r = validate_capability({**_DERIVED, key: ""})
    assert r is not None and key in r["reason"]


def test_a_contract_declaring_no_fields_is_refused():
    """A typed contract with no fields validates nothing -- worse than declaring none,
    because it LOOKS like a contract to anything that checks for presence."""
    r = validate_capability({**_DERIVED, "contract": {"fields": {}}})
    assert r is not None and "non-empty" in r["reason"]


def test_a_field_without_an_encoding_is_refused():
    r = validate_capability({**_DERIVED, "contract": {"fields": {"x": {}}}})
    assert r is not None and "encoding" in r["reason"]


def test_an_unknown_encoding_is_refused():
    r = validate_capability({**_DERIVED, "contract": {"fields": {"x": {"encoding": "hologram"}}}})
    assert r is not None and "unknown encoding" in r["reason"]


def test_json_string_is_a_known_encoding():
    """The encoding that motivated the whole typed contract: ChartWidget's chart_data is a
    STRING containing JSON, not an array. If this ever stops validating, the one fact a
    field-name list could never carry stops being carryable again."""
    assert validate_capability(
        {**_DERIVED, "contract": {"fields": {"chart_data": {"encoding": "json-string"}}}}
    ) is None


def test_refusal_reasons_must_be_strings():
    r = validate_capability({**_DERIVED, "contract": {"fields": {"x": {"encoding": "string"}},
                                                      "refusalReasons": [1, 2]}})
    assert r is not None and "refusalReasons" in r["reason"]


def test_one_bad_row_does_not_refuse_the_batch_and_the_refusal_IS_REPORTED():
    """Per-capability, not per-batch: the other rows are real. But the refused row comes
    back with its index so a caller fixes the row instead of bisecting a payload."""
    admitted, rejected = validate_registration(
        [_DERIVED, {**_DERIVED, "archetype": "HOLOGRAM"}, _LEGACY]
    )
    assert len(admitted) == 2
    assert len(rejected) == 1
    assert rejected[0]["index"] == 1
    assert rejected[0]["archetype"] == "HOLOGRAM"
    assert rejected[0]["reason"]


def test_the_dispatched_but_unenumerated_archetypes_are_admissible():
    """Finding D4: the interpreter dispatches GROUPED_REVIEW / APPROVAL_TASK /
    TRIAGE_TASK / WORKFLOW_OBSERVATION / INSTANCES_BY_PROPERTY, none of which are BAML
    SemanticArchetype members. A validator honouring that split would refuse archetypes
    the UI genuinely renders, so the vocabulary is deliberately the union."""
    for a in ("GROUPED_REVIEW", "APPROVAL_TASK", "TRIAGE_TASK",
              "WORKFLOW_OBSERVATION", "INSTANCES_BY_PROPERTY"):
        assert a in KNOWN_ARCHETYPES
        assert validate_capability({**_LEGACY, "archetype": a}) is None
