"""Engine DA's outcome vocabulary and classifier — dep-free ON PURPOSE.

Split out of ``main.py`` for the same reason ``chart_normalizer.py`` was: the decision it
encodes is the one worth pinning, and pinning it should not require dragging the FastAPI /
Restate / smolagents import chain into a unit test. A rule that is expensive to test is a rule
that gets tested loosely.

WHAT THIS ENCODES. Before 2026-08-15 Engine DA's envelope had ONE field for TWO outcomes: a run
that resolved a URN, queried it and returned rows, and a run that grounded nothing and produced
an articulate apology, BOTH shipped as ``status: "success"``. Everything downstream — the
presentation agent, ``generate_ui_payload``, ``DA_FUMBLE_METRIC`` — then reasoned about a
distinction it had never been given, and behaved correctly on the information available while
producing a confident non-answer on screen.

THE DISCRIMINATORS ARE SYMBOLIC, WHICH IS THE POINT. Neither asks the model whether it answered,
because a model that just wrote an apology will describe it however it likes. Same discipline as
``select-from-authorized-set``: the symbolic layer decides, the LLM's prose is content.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# ``status`` values Engine DA may emit. Defined here so a consumer branches on a constant
# rather than a string literal that drifts across three repos.
OUTCOME_ANSWERED = "success"
OUTCOME_UNGROUNDED = "ungrounded"
OUTCOME_ERROR = "error"
OUTCOME_ACCESS_DENIED = "access_denied"

# WHY `ungrounded` IS NOT CALLED `empty`. An empty RESULT SET is a real answer — the query ran,
# the table had no matching rows, and `rows_returned: 0` on a `success` says exactly that.
# "I never got to run a query" is a different fact with a different user action. Naming both
# "empty" would re-commit the one-field-for-two-outcomes defect one level down.
REASON_NO_URN = "no_urn_resolved"
REASON_QUERY_NEVER_SUCCEEDED = "query_never_succeeded"

UNGROUNDED_MESSAGES = {
    REASON_NO_URN: (
        "I could not ground this question to a specific dataset — the catalog did not resolve "
        "an asset for it, so no data was read."
    ),
    REASON_QUERY_NEVER_SUCCEEDED: (
        "I resolved the dataset but could not read it — no query completed, so there is no "
        "data behind this answer."
    ),
    "default": "This question could not be grounded to data.",
}


def classify_outcome(
    resolved_instance_id: str | None,
    query_successes: Iterable[Mapping[str, Any]],
) -> tuple[str, str]:
    """Return ``(outcome, reason)``. ``reason`` is ``""`` when the run answered.

    ``resolved_instance_id`` is known BEFORE the agent loop runs, so an empty value means the
    run was structurally incapable of grounding — decided without the LLM, and the prompt in
    that branch literally instructs an honest not-found.

    ``query_successes`` is appended only where a query provably returned. It is deliberately
    NOT ``sources_collected``: that list records ATTEMPTS (``_record_query_attempt`` fires
    before the fetch, so the SourcesTrail can show "we tried this" when the data plane is
    down), so using it as corroboration would call a failed read an answer.
    """
    if not resolved_instance_id:
        return OUTCOME_UNGROUNDED, REASON_NO_URN
    if not list(query_successes):
        return OUTCOME_UNGROUNDED, REASON_QUERY_NEVER_SUCCEEDED
    return OUTCOME_ANSWERED, ""


def message_for(reason: str) -> str:
    """The typed, user-facing sentence for an ungrounded reason."""
    return UNGROUNDED_MESSAGES.get(reason, UNGROUNDED_MESSAGES["default"])


def build_envelope(
    outcome: str,
    reason: str,
    agent_result: Any,
    sources: list,
    query_successes: list,
) -> dict:
    """The response envelope, built HERE rather than branched in the handler.

    Deliberately not an `if` in `analyze_data`. A branch in the handler is only testable by
    standing up Restate/FastAPI/smolagents, so in practice it gets "tested" by asserting that
    the string ``OUTCOME_UNGROUNDED`` appears in the source — which passes just as happily when
    the branch has been replaced by ``if False:``. That was measured, not supposed: a
    source-string check written for exactly this did NOT go red under that mutation.

    So the rule lives where it can actually be executed by a unit test, and the handler's job
    is reduced to supplying facts. There is no branch left to disable.
    """
    if outcome == OUTCOME_UNGROUNDED:
        return {
            "status": OUTCOME_UNGROUNDED,
            "reason": reason,
            # The agent's honest prose is usually the better sentence, so it stays as `data`.
            # What changed is that it no longer arrives wearing a success envelope.
            "data": agent_result,
            "message": message_for(reason),
            "sources": sources,
            "rows_returned": 0,
            "queries_succeeded": 0,
        }
    return {
        "status": OUTCOME_ANSWERED,
        "data": agent_result,
        "sources": sources,
        # CORROBORATION, carried rather than implied: `success` with `queries_succeeded == 0`
        # is a contradiction a consumer can detect without trusting this envelope's own claim.
        "rows_returned": sum(int((q or {}).get("row_count") or 0) for q in query_successes),
        "queries_succeeded": len(query_successes),
    }
