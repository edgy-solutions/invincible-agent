"""Slot declarations, DERIVED from the measure signatures — not hand-transcribed.

WHY THIS EXISTS. A registration declares what a verb is ABOUT (`input_uri`) and what it PRODUCES
(`output_uri`) and has never declared what it TAKES. So the router cannot know a slot is missing —
it only knows nothing cleared threshold, which is why a slot-shaped question surfaces as
`NO_VERB_CLASSIFIED` (an INFORMATION gap, not a threshold problem), and why a spoken parameter is
dropped in silence on every verb that has a default for it.

Measured 2026-08-28: twelve of fourteen planning verbs accept parameters and **zero** declare them.
See `[[slots-are-extracted-then-dropped-at-dispatch]]`.

── DERIVED, BECAUSE A HAND-KEPT LIST WOULD BE THE FIFTH INSTANCE ───────────────────────────────
Names, types, enum values, defaults and mandatory-ness are read from `inspect.signature` — the
same instrument the census used to find the problem, promoted from reader to generator. The enum
values CANNOT drift from the `Literal` because they are read out of it. This repo has paid four
times for lists someone remembered instead of enumerating (the re-register list, the phantom
service URL, the readiness probes, the producer seal's own first draft); this is not the fifth.

There is no per-verb Pydantic model to derive from, and that is not a gap being worked around:
`MeasureRequest` types the ENVELOPE (`state_ref`, `params: dict`), `MeshTool` carries only
semantics, and engine-p never populates `openapi_schema`. In this architecture the subject's shape
is ontological (`input_uri` -> a graph class) and the output's shape is the component contract;
the signature is where the parameters' shape actually lives. Deriving from it is the native form,
not a substitute for one. **If a per-verb input model ever arrives** — Engine F's finance verbs are
a plausible first — this generates from it the same way. The declaration layer is source-agnostic
by construction.

── THE ONE FACT NO TYPE SYSTEM CARRIES ─────────────────────────────────────────────────────────
`baseline_state: str` and `site_id: str` are the same shape with opposite provenance: one is
supplied by the route from context, the other must be spoken. A type system cannot tell them
apart, so the KIND is the only thing declared by hand — and only where mandatory-ness does not
already imply it.
"""
from __future__ import annotations

import inspect
import typing
from typing import Any, Dict, List

try:  # flat in the image (/app), packaged in the repo — see
    # tests/test_agent_modules_survive_flat_layout.py, which seals this dual form. A bare
    # `from . import measures` imports fine here and dies at container start.
    import measures
except ImportError:
    from agent_fleet.planning_agent import measures

#: Injected by the route, never spoken. MIRRORS the `params[...] = ...` sites in main.py's
#: run_measure, and `test_slot_handles_match_the_routes_injection_sites` fails if the two
#: disagree — because deriving this by pattern-matching the route's body would be an instrument
#: reading prose, which is the comment-poisoning species this repo has already been bitten by.
HANDLE_SLOTS: Dict[str, set] = {
    "plan_diff":            {"baseline_state"},
    "plan_cost_curve":      {"baseline_state"},
    "plan_schedule":        {"touched_project_ids"},
    "plan_session_changes": {"ops", "scenario_name"},
}

#: Every parameter arrives by a governed UI flow, never from a phrase. The commit ceremony's
#: rationale/actor/ops are supplied by the ceremony; asking a user to speak them would be asking
#: them to compose a governance record in a sentence.
CEREMONY_VERBS = {"plan_commit_scenario"}

#: The measure's own state handle. Never a parameter in any sense a caller would recognise.
_NOT_A_SLOT = {"state"}

SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")


def _type_of(annotation: Any) -> tuple[str, List[str] | None]:
    """(type-name, enum-values) read from the annotation — never from a remembered list."""
    if annotation is inspect.Parameter.empty:
        return "unknown", None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return "enum", [str(v) for v in typing.get_args(annotation)]
    # Optional[X] / X | None — unwrap to the first non-None arm.
    if origin is not None:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _type_of(args[0])
    name = getattr(annotation, "__name__", None)
    return (name or str(annotation)), None


def slots_for(fn_name: str) -> List[dict]:
    """The slot declarations for one measure, derived from its signature."""
    fn = getattr(measures, fn_name, None)
    if fn is None:
        return []
    handles = HANDLE_SLOTS.get(fn_name, set())
    ceremony = fn_name in CEREMONY_VERBS
    out: List[dict] = []
    # `eval_str=True` because measures.py uses `from __future__ import annotations`, which makes
    # every annotation a STRING. Without it `Literal["org","initiative"]` arrives as the literal
    # text `"Literal['org', 'initiative']"` — the enum values reduced to prose, which is exactly
    # the hand-maintained shape this module exists to avoid, arriving through the back door.
    # Falls back to the unevaluated signature if a forward reference will not resolve; a slot
    # typed "unknown" is honest, a slot whose values were parsed out of a string is not.
    try:
        sig = inspect.signature(fn, eval_str=True)
    except Exception:  # noqa: BLE001 - an unresolvable annotation must not break registration
        sig = inspect.signature(fn)
    for name, prm in sig.parameters.items():
        if name in _NOT_A_SLOT:
            continue
        required = prm.default is inspect.Parameter.empty
        type_name, values = _type_of(prm.annotation)
        if name in handles:
            kind = "handle"
        elif ceremony:
            kind = "ceremony"
        elif required:
            kind = "spoken-mandatory"
        else:
            kind = "spoken-optional"
        rec: dict = {"name": name, "kind": kind, "type": type_name, "required": required}
        if values is not None:
            rec["values"] = values
        if not required and prm.default is not None:
            rec["default"] = prm.default if isinstance(
                prm.default, (str, int, float, bool)
            ) else str(prm.default)
        out.append(rec)
    return out
