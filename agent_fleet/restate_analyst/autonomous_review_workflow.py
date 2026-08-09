"""AutonomousReview — workflow 2's durable host (ADR-0034 phase 1.3).

THE SIBLING OF ``grouped_review_workflow``, AND DELIBERATELY ITS MIRROR. Same runner
(``_run_definition``), same step-kind executor, same registry load. The ONE difference is which
git-asserted definition it names — and that difference is the entire trust lifecycle:

    grouped_review     human_await -> dispatch      (workflow 1, supervised)
    autonomous_review  dispatch                     (workflow 2, monitored/trusted)

THE DEFINITION IS LOADED FROM THE RUNTIME REGISTRY, NEVER FROM THE REQUEST. This sentence is
load-bearing prose, not decoration: the next workflow author copies what the reference says, and
the reference must therefore say the rule. A client-supplied process is exactly the laundering the
stage-2 verifier exists to prevent — and on THIS path it would be worse than on workflow 1's,
because here there is no human step between the request and the effect. (``BPMNWorkflowRunner``
accepts ``request["definition"]`` for the legacy inline path; that is a different, older seam and
must not be reached for by anything wiring the autonomous path.)

WHO CHOOSES BETWEEN THE TWO. Not this module, and not the definitions — ``ReviewStarter`` computes
``rung_for(format_fingerprint, pipeline_version)`` SERVER-SIDE and sends to one host or the other.
The rung never crosses a client boundary: a caller supplies FACTS about its input; it may never
supply the authority decision computed from those facts. The definitions stay mode-free — no YAML
consults the trust table — so the process plane and the admission plane never encode each other.

EXPECTED TO DENY TODAY, AND THAT IS THE HONEST STATE. ``mesh:dispatchDispositions`` is granted to
nobody, so a run that reaches here terminally fails at the ``direct_call`` gate. That is the
designed pre-ceremony posture: **routes autonomously, denied at the gate.** Phase 1.3 makes
workflow 2 REACHABLE, not LIVE; the ceremony (grant + trust-table promotion, one governed act)
flips the deny to an allow, and because 1.3 landed first, that flip will change WITNESSED
BEHAVIOUR rather than editing a YAML nothing reads.
"""
from __future__ import annotations

import restate
from restate import Workflow, WorkflowContext

autonomous_review = Workflow("AutonomousReview")


@autonomous_review.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    """Execute the autonomous disposition path for one notice.

    Mirrors ``grouped_review_workflow.run``'s delegation exactly: load the git-asserted definition
    from the registry, hand it to the SHARED executor, map the envelope back to a stable shape.
    There is no ``submit_decision``/``get_batch`` here because there is no human to wake — the
    absence of those handlers is what workflow 2 IS.
    """
    try:  # lazy — main imports THIS module at load time, so the edge must be call-time
        import main as _main  # type: ignore[no-redef]
        from workflow_definition import get_workflow_definition  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst import main as _main
        from agent_fleet.restate_analyst.workflow_definition import get_workflow_definition

    definition = get_workflow_definition("autonomous_review")
    trigger = {**request, "compartment": _compartment_from_request(request)}
    # BIND AT ADMISSION, OR FAIL LOUD HERE. `autonomous_review.yaml` declares
    # `endpoint: "{dispatch_endpoint}"` and nothing used to bind it — the literal string reached an
    # HTTP client and surfaced, sixteen retries deep, as "Invalid URL '{dispatch_endpoint}': No
    # scheme supplied", three layers from the thing that was actually missing. An unbound
    # placeholder is a DEPLOYMENT defect (true of every run of this definition, not of this
    # notice), so it belongs here — once, terminally — not as a retryable-looking transport error.
    try:
        from workflow_definition import UnboundPlaceholder, bind_placeholders  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover — import path differs by runtime
        from agent_fleet.restate_analyst.workflow_definition import (
            UnboundPlaceholder, bind_placeholders,
        )
    try:
        bound = bind_placeholders(definition.model_dump(), trigger)
    except UnboundPlaceholder as exc:
        # TERMINAL: retrying cannot bind a placeholder the deployment does not define.
        raise restate.TerminalError(str(exc), status_code=500)
    envelope = await _main._run_definition(ctx, ctx.key(), bound, trigger)

    dispatched = next(
        (r for r in envelope.get("step_results", []) if r.get("kind") == "direct_call"),
        None,
    )
    if dispatched is None:
        # The definition ran but produced no dispatch step — the process no longer contains the
        # step this handler exists to run. Loud, because a silent {} would read to every caller as
        # an autonomous run that completed with nothing to do, which on THIS path means "acted
        # without supervision and told nobody what it did".
        raise restate.TerminalError(
            "autonomous_review definition produced no direct_call result — "
            f"steps ran: {[r.get('step_id') for r in envelope.get('step_results', [])]}",
            status_code=500,
        )
    return {
        "status": "RESOLVED",
        "admitted_by": "policy",          # no human decided this; the trust table admitted it
        "dispatch": dispatched.get("result"),
        "step_results": envelope.get("step_results", []),
    }


def _compartment_from_request(request: dict) -> str:
    """The compartment this notice belongs to — the only part of the audience the TRIGGER supplies.

    Same rule and same reason as ``grouped_review_workflow._compartment_from_request``: taking only
    the TAIL means a caller can influence WHICH compartment handles its notice, never WHICH
    NAMESPACE decides. Duplicated deliberately rather than imported, because this module must not
    import workflow 1's (they are siblings, not a hierarchy) — and the shared alternative would be
    a third home for a four-line derivation. If it grows, it moves to `utils/`, once.
    """
    explicit = request.get("compartment")
    if explicit:
        return str(explicit)
    audience = request.get("audience") or ""
    return audience.split(":", 1)[1] if ":" in audience else ""
