"""`src/iagent/origin_writer.py` -- the origin WRITER (ingest/origin seam section 7, architect
ruling 2026-10-02 "ORIGIN, not audience", item 3).

WHAT THESE DEFEND:
  * a dropper not bound to the asserted program is refused BEFORE any graph write.
  * the happy path writes exactly one node, at the spec'd label/id/payload.
  * a graph write that lands anywhere other than "written" is still a refusal.

Run: uv run pytest tests/test_origin_writer.py -q
"""
from __future__ import annotations

from typing import Any

import pytest

iagent_mesh = pytest.importorskip("iagent_mesh")
from iagent_mesh.write_results import MeshWriteResult  # noqa: E402

from src.iagent import origin_writer as ow  # noqa: E402
from src.iagent.promotion_stores import INGEST_FACT_FAMILY  # noqa: E402


def _resolution(**kw):
    base = {
        "resolution_id": "SG-1~2",
        "suggestion_id": "SG-1",
        "artifact_id": "ART-9",
        "origin": {"owner_domain": "aviation", "program": "PRG-1",
                  "obtained_via": "authoritative_source"},
        "evidence": {"source": "sor-test", "citation": "sandbox-fake:SANDBOX-FAKE-0001"},
        "approval_chain": [{"role": "steward", "approver_sub": "steward@x"}],
        "provenance": {"case_definition": "origin_suggestion"},
    }
    base.update(kw)
    return base


class _FakeGraphWriter:
    def __init__(self, result: MeshWriteResult):
        self.calls: list[dict] = []
        self._result = result

    def write_node(self, initiator, *, label, id, payload):
        self.calls.append({"initiator": initiator, "label": label, "id": id, "payload": payload})
        return self._result


_INITIATOR = object()


def test_a_dropper_not_bound_to_the_program_is_refused_before_any_write():
    writer = _FakeGraphWriter(MeshWriteResult.written())
    out = ow.write_origin(
        _resolution(), graph_writer=writer, initiator=_INITIATOR,
        dropper_is_program_member=False,
    )
    # MUTANT target (section 7, "skip check_dropper_bound"): removing the check_dropper_bound
    # call before the graph write reds this exact fragment -- "out['status'] == 'write_refused'"
    # -- and the write would also fire, which the second assertion below catches independently.
    assert out["status"] == "write_refused", out
    assert writer.calls == [], writer.calls


def test_the_happy_path_writes_one_node_with_the_spec_shape():
    writer = _FakeGraphWriter(MeshWriteResult.written())
    out = ow.write_origin(
        _resolution(), graph_writer=writer, initiator=_INITIATOR,
        dropper_is_program_member=True,
    )
    assert out == {"status": "written", "reason": None}, out
    assert len(writer.calls) == 1, writer.calls
    call = writer.calls[0]
    assert call["initiator"] is _INITIATOR
    assert call["label"] == INGEST_FACT_FAMILY["node_label"]
    assert call["id"] == "ART-9"
    assert call["payload"] == {
        "origin_owner_domain": "aviation",
        "origin_program": "PRG-1",
        "origin_resolved_by": "record",
        "origin_evidence": "sor-test:sandbox-fake:SANDBOX-FAKE-0001",
    }


def test_a_user_drop_origin_resolves_to_unresolved_not_record():
    """Item D: `obtained_via="user-drop"` -> `resolved_by="unresolved"` -- a bare drop with no
    SystemOfRecord backing it is never written as though a record vouched for it. The SDK's own
    `Origin` validator forces an unresolved write to carry no owner_domain/program/evidence (see
    `write_origin`'s docstring), so the fake resolution's owner_domain/program are NOT expected
    to appear in the payload -- only the marker.

    MUTANT target (item D, "the table collapses back to one constant"): hard-coding
    `_RESOLVED_BY_RECORD = "record"` again (removing the table and the branch) reds this exact
    fragment -- `writer.calls[0]["payload"] == {"origin_resolved_by": "unresolved"}` -- because
    the call would either carry "record" or never happen (the unresolved branch gone).
    """
    writer = _FakeGraphWriter(MeshWriteResult.written())
    out = ow.write_origin(
        _resolution(origin={"owner_domain": "aviation", "program": "PRG-1",
                            "obtained_via": "user-drop"}),
        graph_writer=writer, initiator=_INITIATOR, dropper_is_program_member=True,
    )
    assert out == {"status": "written", "reason": None}, out
    assert writer.calls[0]["payload"] == {"origin_resolved_by": "unresolved"}


def test_a_user_drop_origin_skips_the_dropper_bound_check_not_just_record():
    """There is no program in an unresolved write to be bound to -- `check_dropper_bound` must
    not run at all for this branch, not merely pass. `dropper_is_program_member=False` would
    refuse the "record" branch (see the first test above); here it must still WRITE."""
    writer = _FakeGraphWriter(MeshWriteResult.written())
    out = ow.write_origin(
        _resolution(origin={"owner_domain": "aviation", "program": "PRG-1",
                            "obtained_via": "user-drop"}),
        graph_writer=writer, initiator=_INITIATOR, dropper_is_program_member=False,
    )
    assert out == {"status": "written", "reason": None}, out
    assert len(writer.calls) == 1


def test_an_unmapped_obtained_via_is_refused_before_any_write():
    writer = _FakeGraphWriter(MeshWriteResult.written())
    out = ow.write_origin(
        _resolution(origin={"owner_domain": "aviation", "program": "PRG-1",
                            "obtained_via": "etl"}),
        graph_writer=writer, initiator=_INITIATOR, dropper_is_program_member=True,
    )
    assert out["status"] == "write_refused", out
    assert writer.calls == [], writer.calls


@pytest.mark.parametrize("result", [
    MeshWriteResult.refused("identity gate declined"),
    MeshWriteResult.failed("store errored"),
    MeshWriteResult.unreachable("store unreachable"),
    MeshWriteResult.written_without_vector("no embedding endpoint"),
])
def test_any_outcome_other_than_written_is_a_refusal(result):
    writer = _FakeGraphWriter(result)
    out = ow.write_origin(
        _resolution(), graph_writer=writer, initiator=_INITIATOR,
        dropper_is_program_member=True,
    )
    assert out["status"] == "write_refused", out
    assert len(writer.calls) == 1, "the write WAS attempted -- only its outcome is refused"
