"""The ActionRecord's `work_order.parts[]` are objects and its citations sit under `task_refs`, ON THE
WIRE, for every option the maintenance case can release.

The contract (openddil-contracts ADR-0046, amendment 2026-11-24): each part is an object with
`item`, `part_ref` and an integer `quantity` above 0, plus the optional `source_site`, `icn`,
`hotspot_id` and the `lead_time_days`/`lead_time_source` pair; a part written as a bare string is
refused; citations sit under `work_order.task_refs[]` and under no other key.

WHY A SECOND SEAL. tests/test_the_written_action_record_meets_the_pinned_schema.py drives ONE
option (`replace_after_resupply`) and validates the Python dict in pydantic's LAX mode, which turns
`"2"` into `2`. An intake validates JSON against a JSON schema, where `"2"` is not an integer. So
this seal:
- drives the REAL `maint_fault_propose.yaml` / `maint_release.yaml` to `released` for EACH of the
  four options (two carry parts, two carry `parts: []`);
- serialises the record the runner POSTs, and validates that JSON with the pinned SDK
  `ActionRecord` in STRICT mode (no coercion);
- asserts the shape directly too (a list of objects, an `int` quantity, no other citation key), so
  it does not rest on the SDK alone.

Run: uv run pytest tests/test_the_action_record_parts_are_objects_on_the_wire.py -v
"""
from __future__ import annotations

import copy
import json

import pytest
import pytest_asyncio

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
pytest.importorskip("iagent_mesh")
from iagent_mesh.maintenance_bridge import ActionRecord  # noqa: E402

from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: E402,F401
    REVIEW, _declared_walk_double, _real_policy, registered)
from tests.test_the_runner_writes_the_action_record_at_released import (  # noqa: E402,F401
    DECIDE, DELEGATE, _drive, posts)
from tests.test_the_written_action_record_meets_the_pinned_schema import (  # noqa: E402
    _ENVELOPE, _undeclared_allowance)

#: The four options `maint_fault_propose.yaml` renders, and whether each one names a part. An NMC
#: option (`evacuate_for_depot`) takes the supervisor's second approval before it is released.
OPTIONS = (("replace_now", True, False), ("replace_after_resupply", True, False),
           ("defer_with_restriction", False, False), ("evacuate_for_depot", False, True))

_PART_KEYS = {"item", "part_ref", "quantity", "source_site", "icn", "hotspot_id",
              "lead_time_days", "lead_time_source"}
_WORK_ORDER_KEYS = {"option", "readiness", "task", "task_refs", "parts", "outcome"}


def strict_violations(record) -> list:
    """Every error the pinned `ActionRecord` raises on the record's JSON, in STRICT mode. The
    ruled fields the pin does not declare yet are allowed `extra_forbidden`, as in the lax seal."""
    body = json.dumps({k: v for k, v in record.items() if k not in _ENVELOPE})
    allowed = _undeclared_allowance()
    try:
        ActionRecord.model_validate_json(body, strict=True)
    except Exception as e:  # pydantic ValidationError
        return [f"{tuple(err['loc'])} {err['type']}" for err in e.errors()
                if not (err["type"] == "extra_forbidden" and tuple(err["loc"]) in allowed)]
    return []


def shape_violations(record) -> list:
    """The amendment's rule, read off the JSON without the SDK."""
    wo = json.loads(json.dumps(record))["work_order"]
    out = []
    if not isinstance(wo.get("parts"), list):
        out.append(f"parts is {type(wo.get('parts')).__name__}, not a list")
    for i, p in enumerate(wo.get("parts") or []):
        if not isinstance(p, dict):
            out.append(f"parts[{i}] is {type(p).__name__}, not an object: {p!r}")
            continue
        if set(p) - _PART_KEYS:
            out.append(f"parts[{i}] has keys outside the table: {sorted(set(p) - _PART_KEYS)}")
        for k in ("item", "part_ref"):
            if not (isinstance(p.get(k), str) and p[k].strip()):
                out.append(f"parts[{i}].{k} is {p.get(k)!r}")
        q = p.get("quantity")
        if not (type(q) is int and q > 0):
            out.append(f"parts[{i}].quantity is {q!r} ({type(q).__name__}), not an integer above 0")
        if (p.get("lead_time_days") is None) != (p.get("lead_time_source") is None):
            out.append(f"parts[{i}] sets one of the lead_time pair without the other")
    if not isinstance(wo.get("task_refs"), list) or not wo["task_refs"]:
        out.append(f"task_refs is {wo.get('task_refs')!r}")
    for i, r in enumerate(wo.get("task_refs") or []):
        if not (isinstance(r, dict) and set(r) == {"graph_uri", "data_module_code"}):
            out.append(f"task_refs[{i}] is not a {{graph_uri, data_module_code}} object: {r!r}")
    if set(wo) - _WORK_ORDER_KEYS:
        out.append(f"work_order carries keys outside the contract: {sorted(set(wo) - _WORK_ORDER_KEYS)}")
    return out


async def _released_record(posts, verb, reviewed=False):
    answers = [(DECIDE, verb)] + ([(REVIEW, "approved", "s@x")] if reviewed else [])
    out, _ = await _drive(answers, seeded_by=DELEGATE)
    assert out["status"] == "CLOSED", out
    recs = [j["record"] for u, j, _h in posts if u.endswith("/action-record")]
    assert len(recs) == 1, recs
    return recs[0]


@pytest_asyncio.fixture
async def resupply_record(registered, posts):
    return await _released_record(posts, "replace_after_resupply")


@pytest.mark.asyncio
@pytest.mark.parametrize("verb,has_parts,reviewed", OPTIONS)
async def test_every_option_releases_parts_as_objects_on_the_wire(registered, posts, verb, has_parts,
                                                                  reviewed):
    record = await _released_record(posts, verb, reviewed)
    assert record["work_order"]["option"] == verb
    assert strict_violations(record) == []
    assert shape_violations(record) == []
    # An option that needs no part sends an EMPTY list, never a missing key or a null.
    assert bool(record["work_order"]["parts"]) == has_parts, record["work_order"]["parts"]


@pytest.mark.asyncio
async def test_POSITIVE_CONTROL_a_part_as_a_string_is_refused(resupply_record):
    bad = copy.deepcopy(resupply_record)
    p = bad["work_order"]["parts"][0]
    bad["work_order"]["parts"][0] = f"{p['quantity']} x {p['part_ref']}"
    assert strict_violations(bad)
    assert any("not an object" in v for v in shape_violations(bad))


@pytest.mark.asyncio
async def test_POSITIVE_CONTROL_a_quantity_as_a_string_is_refused_strictly(resupply_record):
    """The reason this seal is STRICT: the lax model admits `"2"`, a JSON-schema intake does not."""
    bad = copy.deepcopy(resupply_record)
    bad["work_order"]["parts"][0]["quantity"] = str(bad["work_order"]["parts"][0]["quantity"])
    assert strict_violations(bad)
    assert any("quantity" in v for v in shape_violations(bad))
    lax = {k: v for k, v in bad.items() if k not in _ENVELOPE}
    try:
        ActionRecord.model_validate(lax)
        lax_errors = []
    except Exception as e:
        lax_errors = [x for x in e.errors() if "quantity" in str(x["loc"])]
    assert lax_errors == [], "the lax model now refuses a string quantity; this control's premise moved"


@pytest.mark.asyncio
async def test_POSITIVE_CONTROL_a_second_citation_key_is_refused(resupply_record):
    bad = copy.deepcopy(resupply_record)
    bad["work_order"]["citations"] = copy.deepcopy(bad["work_order"]["task_refs"])
    assert strict_violations(bad)
    assert any("outside the contract" in v for v in shape_violations(bad))
