"""The origin WRITER (ruling 3, architect ruling 2026-10-02 "ORIGIN, not audience", item 3):
turns a confirmed `origin_resolution` (`policy/workflows/origin_record.yaml`'s own emit) into
a graph write.

FUNCTION ONLY -- `write_origin` is pure given its injected `graph_writer`/`initiator`. The
TRANSPORT (item B, 2026-10-03) is `POST /internal/origin/write` on the BFF
(`src/iagent/gateway.py:write_origin_route`), called directly by the case's own `written`
`direct_call` step -- the step's HTTP response IS this function's return value, synchronously,
so there is no separate signal to answer. `answer_signal`/`ORIGIN_WRITTEN_SIGNAL` (the prior
signal-based transport's answer-back, for the `written` step when it was still `signal_await`)
are REMOVED as dead code in this same change: no caller remained once the step converted.

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
`human_tasks.check_can_view_program`): the transport route, item B's `write_origin_route`.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from . import origin
from .promotion_stores import INGEST_FACT_FAMILY

logger = logging.getLogger(__name__)

#: `Origin.resolved_by`, keyed on `origin.obtained_via` (RULED 2026-10-03, item D): a
#: `SystemOfRecord` hit (`origin_resolver._OBTAINED_VIA_RECORD`) resolves to "record" -- ruled
#: RIGHT, carried over from the single-value constant this replaces. A bare `user-drop` (no
#: record backs it) resolves to "unresolved" -- added per the same ruling. Anything else is not
#: yet a decided mapping and is refused rather than guessed; see `write_origin`'s KeyError
#: handling below. Not `SDK Origin.RESOLVED_BY`'s third rung ("steward"): nothing produces a
#: resolution whose origin was vouched for by a human without a record, so this table has no
#: row for it -- adding one unexercised would be an invented mapping, not an encoded one.
_RESOLVED_BY_BY_OBTAINED_VIA = {
    "authoritative_source": "record",
    "user-drop": "unresolved",
}

def write_origin(
    resolution: dict[str, Any],
    *,
    graph_writer: Any,
    initiator: Any,
    dropper_is_program_member: bool,
) -> dict[str, Any]:
    """Returns `{"status": "written" | "write_refused", "reason": str | None}`. See the module
    docstring for `dropper_is_program_member` (deviation #1).

    BRANCHES ON `resolved_by` (item D). `_RESOLVED_BY_BY_OBTAINED_VIA["user-drop"]` is
    `"unresolved"`, and the SDK's own `Origin` validator (read in full) REQUIRES an
    `"unresolved"` origin to carry no `owner_domain`, no `program` and no `evidence` -- "there is
    nothing resolved to attach any of them to". A bare user-drop therefore skips
    `check_dropper_bound` entirely (there is no program in the write for the dropper to be bound
    to) and writes only the `resolved_by` marker -- making explicit the SAME "visible to its
    dropper/owner only" default `origin.py`'s module docstring already describes for an
    unresolved artifact, never a new grant.
    """
    o = resolution["origin"]
    try:
        resolved_by = _RESOLVED_BY_BY_OBTAINED_VIA[o["obtained_via"]]
    except KeyError:
        return {
            "status": "write_refused",
            "reason": f"no resolved_by mapping for obtained_via={o['obtained_via']!r} "
                      f"(known: {sorted(_RESOLVED_BY_BY_OBTAINED_VIA)})",
        }

    if resolved_by == "unresolved":
        try:
            from iagent_mesh.systems_of_record import Origin as _SorOrigin  # noqa: PLC0415

            _SorOrigin(resolved_by=resolved_by)
        except ValidationError as exc:
            return {"status": "write_refused", "reason": f"origin shape invalid: {exc}"}
        result = graph_writer.write_node(
            initiator, label=INGEST_FACT_FAMILY["node_label"], id=resolution["artifact_id"],
            payload={"origin_resolved_by": resolved_by},
        )
        if result.outcome != "written":
            return {
                "status": "write_refused",
                "reason": f"graph write outcome={result.outcome!r}: {result.detail}",
            }
        return {"status": "written", "reason": None}

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
            resolved_by=resolved_by, evidence=(citation,),
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
            "origin_resolved_by": resolved_by,
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
