"""The maintenance ActionRecord the runner WRITES at `released` meets the pinned SDK's schema.

The record is produced by the REAL `maint_fault_propose.yaml` / `maint_release.yaml` over the REAL
MRAD fixture walk (the runner driven to `released`, as in
tests/test_the_runner_writes_the_action_record_at_released.py), then validated with
`iagent_mesh.maintenance_bridge.ActionRecord` -- never a hand-written record.

ALLOWANCE (derived, not typed): five fields the architect ruled (2026-11-10) are ones the SDK
adds in a later tag. Each may fail with `extra_forbidden` ONLY while the pinned model does not
declare it; read from `model_fields` per field, so the day the pin declares one, an error on it
fails this seal. Every other error fails, always.

Run: uv run pytest tests/test_the_written_action_record_meets_the_pinned_schema.py -v
"""
from __future__ import annotations

import copy

import pytest
import pytest_asyncio

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
pytest.importorskip("iagent_mesh")
from iagent_mesh.maintenance_bridge import ActionRecord  # noqa: E402

from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: E402,F401
    _declared_walk_double, _real_policy, registered)
from tests.test_the_runner_writes_the_action_record_at_released import (  # noqa: E402,F401
    DELEGATE, RELEASED, _delegates, _drive, posts)

_ENVELOPE = ("case_id", "artifact_id", "acts", "dmcs_cited", "action_ids")
#: The ruled schema-side fields, as (section, field).
_RULED = (("work_order", "option"), ("work_order", "readiness"), ("provenance", "case_definition"),
          ("provenance", "case_id"), ("provenance", "emitted_by"))


def _model_of(section):
    return ActionRecord.model_fields[section].annotation


def _undeclared_allowance():
    return {(s, f) for s, f in _RULED if f not in _model_of(s).model_fields}


def _nonblank(x):
    return isinstance(x, str) and bool(x.strip())


def violations(record) -> list:
    """Every reason `record` fails the seal; empty means it meets it."""
    out = []
    allowed = _undeclared_allowance()
    try:
        ActionRecord.model_validate({k: v for k, v in record.items() if k not in _ENVELOPE})
    except Exception as e:  # pydantic ValidationError
        for err in e.errors():
            loc = tuple(err["loc"])
            if err["type"] == "extra_forbidden" and len(loc) == 2 and loc in allowed:
                continue
            out.append(f"schema: {loc} {err['type']}")
    for i, ref in enumerate((record.get("work_order") or {}).get("task_refs") or []):
        if not _nonblank(ref.get("graph_uri")):
            out.append(f"task_refs[{i}].graph_uri is {ref.get('graph_uri')!r}")
    nodes = (record.get("provenance") or {}).get("manual_nodes_consulted")
    if not isinstance(nodes, list) or not nodes or not all(_nonblank(n) for n in nodes):
        out.append(f"manual_nodes_consulted is not a flat list of non-empty strings: {nodes!r}")
    return out


@pytest_asyncio.fixture
async def record(registered, posts):
    out, _ = await _drive(RELEASED, seeded_by=DELEGATE)
    assert out["status"] == "CLOSED"
    recs = [j["record"] for u, j, _h in posts if u.endswith("/action-record")]
    assert len(recs) == 1, recs
    return recs[0]


def test_the_allowance_is_read_from_the_pinned_model_not_typed():
    assert _undeclared_allowance() <= set(_RULED)
    for s, f in _RULED:
        assert ((s, f) in _undeclared_allowance()) == (f not in _model_of(s).model_fields)


@pytest.mark.asyncio
async def test_the_written_record_meets_the_pinned_schema(record):
    assert violations(record) == []
    refs = record["work_order"]["task_refs"]
    assert refs and all(_nonblank(r["graph_uri"]) for r in refs), refs
    nodes = record["provenance"]["manual_nodes_consulted"]
    assert nodes and all(isinstance(n, str) and n for n in nodes), nodes


@pytest.mark.asyncio
async def test_POSITIVE_CONTROL_a_null_graph_uri_is_refused(record):
    bad = copy.deepcopy(record)
    bad["work_order"]["task_refs"][0]["graph_uri"] = None
    assert violations(bad)


@pytest.mark.asyncio
async def test_POSITIVE_CONTROL_a_nested_list_in_manual_nodes_is_refused(record):
    bad = copy.deepcopy(record)
    bad["provenance"]["manual_nodes_consulted"][1] = ["a", "b"]
    assert violations(bad)
