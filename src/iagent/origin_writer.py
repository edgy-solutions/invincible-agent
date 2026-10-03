"""The origin WRITER (ruling 3, architect ruling 2026-10-02 "ORIGIN, not audience", item 3):
turns a confirmed `origin_resolution` (`policy/workflows/origin_record.yaml`'s own emit) into
a graph write, and answers the case's `origin_written` signal with the outcome.

FUNCTION ONLY. This module does NOT consume the outbox (`origin_resolution` channel) --
that transport (reading `outbox:origin_resolution`, calling this function once per record,
calling `answer_signal` with its result) is going to the architect. This module ships the two
callables the consumer will call: `write_origin` (pure given its injected `graph_writer`/
`initiator`) and `answer_signal` (one HTTP call).

ORDER, per spec: `origin.check_dropper_bound` -> SDK `systems_of_record.Origin` shape
validation -> `graph_writer.write_node`. Any outcome other than the graph write's own
`"written"` -- a `DropperNotProgramMember`, a validation failure, or any other
`MeshWriteResult.outcome` -- is `write_refused`, never raised past this function.

DEVIATION #1 (flagged in the report): `write_origin`'s spec'd signature is
`(resolution, *, graph_writer, initiator)` -- three parameters, no room for the boolean
`origin.check_dropper_bound(is_member, origin)` needs. Read in full, `resolution` (the
`origin_resolution` emit template in `policy/workflows/origin_record.yaml`) carries
`resolution_id, suggestion_id, artifact_id, origin, evidence, approval_chain, provenance` --
NO `dropped_by` field anywhere in that template, so this function has no identity to ask any
membership source about even if one were wired in here. Rather than inventing a membership
source (there is no Topaz/graph handle in this function's parameter list either) or silently
skipping the check, this function takes the already-resolved boolean as a REQUIRED keyword
parameter, `dropper_is_program_member` -- the same shape `origin.check_dropper_bound` itself
already takes, pushed one level up to whoever DOES hold the dropper's authz_id (the original
`origin_suggestion`'s `dropped_by.authz_id`) and a membership source (e.g.
`human_tasks.check_can_view_program`): the outbox consumer, out of scope here.

DEVIATION #2 (flagged in the report): `answer_signal`'s spec'd signature is
`(instance_id, status)` -- two parameters. `agent_fleet/restate_analyst/workflow_runner.py`'s
`signal` handler (read in full) calls `main._authorize_resolution(ctx, name, request.get(
"acted_by"))`, which HARD-REQUIRES a non-blank `acted_by` (raises `restate.TerminalError`,
401, otherwise) -- confirmed independently by `tests/test_an_origin_suggestion_runs_as_a_case.
py`'s own `_approve` helper, which always supplies one. Calling the real endpoint with no
`acted_by` would always 401, so this function adds it as a required keyword parameter rather
than guessing a value to hardcode.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from . import origin
from .promotion_stores import INGEST_FACT_FAMILY

logger = logging.getLogger(__name__)

#: Same env var, same default, as gateway._RESTATE_INGRESS_URL -- duplicated rather than
#: imported from `gateway.py` (a 7700+-line module this function-only file should not pull in;
#: see the module docstring's "function only" framing).
_RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

#: `Origin.resolved_by` for a write this function performs -- always "a SystemOfRecord lookup
#: resolved it" by the time a confirmed `origin_resolution` reaches this function.
_RESOLVED_BY_RECORD = "record"

#: The case's own signal name (`policy/workflows/origin_record.yaml`'s `written` step).
ORIGIN_WRITTEN_SIGNAL = "origin_written"


def write_origin(
    resolution: dict[str, Any],
    *,
    graph_writer: Any,
    initiator: Any,
    dropper_is_program_member: bool,
) -> dict[str, Any]:
    """Returns `{"status": "written" | "write_refused", "reason": str | None}`. See the module
    docstring for `dropper_is_program_member` (deviation #1)."""
    o = resolution["origin"]
    origin_obj = origin.Origin(
        owner_domain=o["owner_domain"], program=o["program"], obtained_via=o["obtained_via"],
    )
    try:
        origin.check_dropper_bound(dropper_is_program_member, origin_obj)
    except origin.DropperNotProgramMember as exc:
        return {"status": "write_refused", "reason": str(exc)}

    evidence = resolution["evidence"]
    citation = f"{evidence['source']}:{evidence['citation']}"
    try:
        from iagent_mesh.systems_of_record import Origin as _SorOrigin  # noqa: PLC0415

        _SorOrigin(
            owner_domain=o["owner_domain"], program=o["program"],
            resolved_by=_RESOLVED_BY_RECORD, evidence=(citation,),
        )
    except ValidationError as exc:
        return {"status": "write_refused", "reason": f"origin shape invalid: {exc}"}

    result = graph_writer.write_node(
        initiator,
        label=INGEST_FACT_FAMILY["node_label"],
        id=resolution["artifact_id"],
        payload={
            "origin_owner_domain": o["owner_domain"],
            "origin_program": o["program"],
            "origin_resolved_by": _RESOLVED_BY_RECORD,
            "origin_evidence": citation,
        },
    )
    # ANY outcome other than "written" -> write_refused (spec's own wording) -- NOT `.applied`,
    # which would also accept "written_without_vector" (irrelevant here: a graph node has no
    # vector half, but the spec names "written" specifically, so this matches that literally).
    if result.outcome != "written":
        return {
            "status": "write_refused",
            "reason": f"graph write outcome={result.outcome!r}: {result.detail}",
        }
    return {"status": "written", "reason": None}


async def answer_signal(instance_id: str, status: str, *, acted_by: str) -> None:
    """POST `{RESTATE_INGRESS_URL}/WorkflowRunner/{instance_id}/signal`, body
    `{"signal": "origin_written", "status": status, "acted_by": acted_by}` -- see the module
    docstring's deviation #2 for `acted_by`. Raises on any transport/HTTP failure (unlike the
    ingest seam's best-effort `_open_case`): the case is waiting on this answer, so a swallowed
    failure here would leave it waiting forever with no record that the write even happened.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{quote(instance_id, safe='')}/signal",
            json={"signal": ORIGIN_WRITTEN_SIGNAL, "status": status, "acted_by": acted_by},
        )
    resp.raise_for_status()
