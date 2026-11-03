"""Reading a safety `review_request` off a draft, and building the trigger that opens it.

THE ARTIFACT SIDE of the R-076 consumer. The DECISION side — which definition opens an
acceptance at a given level — is `agent_fleet/restate_analyst/acceptance_selection.py`, and the
split is not cosmetic: **the gateway must never be able to choose the definition.** It reads the
request and hands over FACTS; the table behind the workflow boundary chooses the route. A caller
that could name the definition could name `safety_acceptance_direct` for a High hazard and skip
the concurrence MIL-STD-882E §4.3.7 requires first.

It also keeps the decision tables out of cortex-bff, which has no reason to compose them.

WHY THIS IS IN `iagent_pure` AND NOT COPIED INTO THE GATEWAY: the gateway and the seals that
check it must read the SAME derivation. Two implementations that agree are a copy, and a copy
drifts until a hazard's acceptance opens under a key one of them no longer builds.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class AcceptanceRequestError(Exception):
    """A review request could not be turned into a trigger. Always terminal — never defaulted."""


def review_request_of(engine_response: Any) -> Dict[str, Any]:
    """The `review_request` block off a draft's ENGINE RESPONSE, at its declared key.

    ADDRESSED, NOT SEARCHED, AND THE DIFFERENCE IS DELIBERATE. `walk_census._review_request`
    walks a turn recursively because it reads a RENDERED artifact and cannot know where the block
    rides. This reads `direct_dispatch`'s `engine_response` — the engine's own body, where
    `measures.py:411` puts the block at the top level. A recursive walk here would be hunting for
    something whose location is known, and would cheerfully find a block nested inside some
    unrelated payload the day one appears.

    MEASURED 2026-09-19 against the live fleet (engine-safety `91d8d34`, which diffs EMPTY
    against this tree for `safety_agent/`): the draft for HAZ-1003 carries `review_request` with
    kind `risk_acceptance_medium` and audience `risk_acceptance_medium:SUSTAINMENT`.

    **AND IT IS ABSENT FROM THE RENDERED TURN.** Engine F renders a card and the block does not
    survive into it — which is why this consumer belongs at `gateway.py`'s
    `_expert = outcome.engine_response` and NOT anywhere downstream of the render. It is also
    why the walk census scores this row `drawn` rather than `task_requested` while the engine has
    been emitting the request correctly the whole time: **the census and the engine are looking
    at two different surfaces, and only one of them ever carried the block.**
    """
    if not isinstance(engine_response, dict):
        return {}
    rr = engine_response.get("review_request")
    return rr if isinstance(rr, dict) and rr else {}


#: The WorkflowRunner trigger a safety `review_request` opens (policy/overlays/*/triggers/). The
#: route after it -- concurrence or direct, and what follows each outcome -- is decision-table rows.
SAFETY_TRIGGER = "safety_review_request"


def _key_inputs(review_request: Dict[str, Any]) -> tuple:
    """``(hazard_id, level, level_slug)`` as the acceptance trigger reads them off the block.

    ONE DERIVATION for `acceptance_trigger` (which mints `acceptance_id`) and `with_minted_ids`
    (which stamps `case_id`), so the card's key and the minted key cannot drift apart.
    """
    payload = review_request.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    hazard_id = payload.get("hazard_id") or review_request.get("subject_ref") or ""
    level = payload.get("risk_level") or ""
    level_slug = payload.get("risk_level_slug") or (level.lower() if level else "")
    return hazard_id, level, level_slug


def with_minted_ids(review_request: Dict[str, Any]) -> Dict[str, Any]:
    """A COPY of the block with `case_id` set to the key `acceptance_trigger` mints.

    Stamped where the engine response is READ, before the render, because the engine image
    cannot import this module and the UI opens the case from the card's `case_id` before any
    task exists. The minted value wins over whatever the engine sent (a WARNING names both).
    Inputs absent -> the block is returned unchanged (never an invented key).

    `task_id` is NOT stamped: the real task id is `{workflow_id}:{step.id}` minted by the
    workflow runner (restate_analyst/main.py, human_await), and `step.id` depends on the route
    the decision table picks at run time (`acceptance` vs `concurrence`), so it is not
    computable from the request.
    """
    if not isinstance(review_request, dict) or not review_request:
        return review_request
    hazard_id, _level, level_slug = _key_inputs(review_request)
    if not (hazard_id and level_slug):
        return review_request
    minted = acceptance_workflow_id(str(hazard_id), str(level_slug))
    out = dict(review_request)
    sent = out.get("case_id")
    if sent and sent != minted:
        logger.warning("review_request case_id %r overridden by the minted case key %r",
                       sent, minted)
    out["case_id"] = minted
    return out


def acceptance_trigger(review_request: Dict[str, Any], *, authz_id: str) -> Dict[str, Any]:
    """The FLAT trigger `_run_definition` binds a definition's `{placeholders}` from.

    `_run_definition` builds its bindings as ``{k: v for k, v in request.items() if
    isinstance(v, (str, int, float))}`` — **top-level scalars only.** The fields the acceptance
    definitions need (`hazard_id`, `level`, `level_slug`) live inside `review_request["payload"]`,
    so they are lifted here rather than left one level down where the binder cannot see them. A
    nested value is not a missing value, and it fails exactly like one.

    THE AUDIENCE PLACEHOLDER IS STRICT, WHICH IS WHY THIS REFUSES RATHER THAN GUESSES.
    `safety_acceptance_direct.yaml` declares ``audience: "risk_acceptance_{level_slug}:SUSTAINMENT"``
    and the executor raises on an unbound strict placeholder, because "a `human_await` registered
    against the literal `risk_acceptance_{level_slug}` matches no Topaz relation, so NOBODY can
    act on it and the workflow suspends forever with no error". Inventing a `level_slug` here
    would move that failure from bind time to a queue nobody holds.

    VERIFIED ON THE LIVE ARTIFACT: the trigger built from HAZ-1003's request binds that strict
    audience to `risk_acceptance_medium:SUSTAINMENT`, which is byte-identical to the
    `acceptance_audience` the engine resolved INDEPENDENTLY from the ratified matrix TTL. Two
    derivations of one audience, agreeing — an invariant BETWEEN two declarations, which no
    per-declaration check can see (R-035), and `tests/safety/` now asserts it.

    `authz_id` IS THE CASE'S REQUESTER (ruled 2026-10-05): the person whose turn's answer carried
    this review_request, read from the answer's envelope by the consumer. It travels as the fact
    `authz_id` because that is the key `_run_definition` builds its identity from, and the
    `human_await` row's `requested_by` is that identity when the step declares none (no safety
    definition does). Refused when blank: the register would refuse the row anyway, but only
    after the case had opened, and an open case with no row is a review nobody was asked for.
    The review_request's own `requested_by` stays a separate fact -- it names the engine that
    drafted, not the person who asked.
    """
    if not str(authz_id or "").strip():
        raise AcceptanceRequestError(
            f"review_request (kind={review_request.get('kind')!r}, subject_ref="
            f"{review_request.get('subject_ref')!r}) reached the acceptance consumer with no "
            "requester: the turn's envelope carries no authz_id. A case opened without one would "
            "register a row the store refuses.")
    payload = review_request.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    hazard_id, level, level_slug = _key_inputs(review_request)

    missing = [n for n, v in (("hazard_id", hazard_id), ("risk_level", level),
                              ("risk_level_slug", level_slug)) if not v]
    if missing:
        raise AcceptanceRequestError(
            f"review_request cannot build an acceptance trigger: missing {missing} "
            f"(kind={review_request.get('kind')!r}, subject_ref="
            f"{review_request.get('subject_ref')!r}). The definition's audience placeholder is "
            "STRICT, so an incomplete trigger would suspend a workflow nobody can act on."
        )

    return {
        "hazard_id": str(hazard_id),
        "level": str(level),
        "level_slug": str(level_slug),
        # THE CASE KEY, as a fact: the trigger declares `key: acceptance_id`, and the runner refuses
        # a case whose URL key is not the event's own -- so the dedupe is this one derivation.
        "acceptance_id": acceptance_workflow_id(str(hazard_id), str(level_slug)),
        "kind": str(review_request.get("kind") or ""),
        "audience": str(review_request.get("audience") or ""),
        "subject_ref": str(review_request.get("subject_ref") or hazard_id),
        "title": str(review_request.get("title") or ""),
        "summary": str(review_request.get("summary") or ""),
        "requested_by": str(review_request.get("requested_by") or ""),
        "authz_id": str(authz_id).strip(),
        # NOT a scalar, so no placeholder binds from it. Carried because an acceptance recorded
        # without the evidence that justified it is the signature ADR-0051 exists to prevent.
        "review_payload": payload,
    }


def acceptance_workflow_id(hazard_id: str, level_slug: str) -> str:
    """The durable key for one hazard's acceptance at one level.

    HAZARD AND LEVEL BOTH. A redraft that moves a hazard to a different level is a DIFFERENT
    acceptance by a DIFFERENT authority; keying on the hazard alone would collapse the second
    onto the first and it would be swallowed by idempotency, unseen. That collapse is recorded in
    `review_starter.escalation_request_key` as a defect that had to be fixed once already — the
    BFF's ingress key "collapses onto the original admission's key and the escalation is
    swallowed", in its own words. Same mechanism, so the same guard, rather than a second
    discovery of it.
    """
    return f"risk-acceptance-{hazard_id}-{level_slug}"
