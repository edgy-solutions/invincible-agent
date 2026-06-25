"""Pure helpers for the supervisor's predicate-routing path.

Extracted here so pure-unit tests can pin the contracts without
dragging Dagster / psycopg2 through ``iagent/__init__.py``.
``dynamic_supervisor.py`` re-exports these under the legacy
underscored names so the rest of the supervisor file doesn't change.
"""

from __future__ import annotations

from typing import Any, Dict


def inject_predicate_output_uri(
    engine_response: Any, predicate: Dict[str, Any]
) -> None:
    """Inject the matched predicate's output_uri into the engine's
    response when the engine itself didn't echo one.

    Why this exists: Engine F's /render_ui reads
    ``expert_response.output_uri`` to pick the archetype-hardened
    presentation path. Engine A's smolagent is prompted to echo
    output_uri in final_answer() (ADR-0017 cheap-drift-detection),
    so its expert_response already carries it — engine echo wins
    here, which is what makes the drift detection useful (a
    disagreement between echoed and declared is visible in audit).
    Engine DA / W / E don't all echo. Without injection, /render_ui
    falls through to legacy DesignUI which never runs the
    deterministic chart_data normalizer, and the widget renders
    empty — the c4b3ff7a-d734-4a10-8b32-812537c82ea5 chart-empty
    regression. The supervisor already knows the predicate's
    output_uri from the routing decision; inject it.

    Contract:
      * dict response without output_uri + predicate has one → injected.
      * dict response WITH output_uri → engine echo wins (drift
        detection preserved; never overwritten).
      * dict response + predicate has no output_uri → no-op (nothing
        to inject).
      * Non-dict response (e.g., None on routing infrastructure
        failure) → no-op (safe, leaves any error sentinel intact).

    Pinned by ``tests/routing/test_supervisor_output_uri_injection.py``.
    """
    if not isinstance(engine_response, dict):
        return
    if engine_response.get("output_uri"):
        return
    pred_uri = predicate.get("output_uri") if isinstance(predicate, dict) else None
    if pred_uri:
        engine_response["output_uri"] = pred_uri
