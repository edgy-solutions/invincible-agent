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
import types
import typing
from typing import Any, Dict, List

try:  # flat in the image (/app), packaged in the repo — see
    # tests/test_agent_modules_survive_flat_layout.py, which seals this dual form. A bare
    # `from . import measures` imports fine here and dies at container start.
    import measures
    from entities import FISCAL_PERIODS
except ImportError:
    from agent_fleet.planning_agent import measures
    from agent_fleet.planning_agent.entities import FISCAL_PERIODS

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


def _is_union(origin: Any) -> bool:
    """`Optional[X]` and `X | None` have DIFFERENT origins (`typing.Union` and
    `types.UnionType`), and this module must treat both as unwrappable — otherwise the same
    annotation declares differently depending on which syntax the author used."""
    if origin is typing.Union:
        return True
    UnionType = getattr(types, "UnionType", None)  # 3.10+; absent on older runtimes
    return UnionType is not None and origin is UnionType


def _type_of(annotation: Any) -> tuple[str, List[str] | None]:
    """(type-name, enum-values) read from the annotation — never from a remembered list."""
    if annotation is inspect.Parameter.empty:
        return "unknown", None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return "enum", [str(v) for v in typing.get_args(annotation)]
    if origin is not None:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        # Optional[X] / X | None — unwrap to the single remaining arm.
        if _is_union(origin):
            if len(args) == 1:
                return _type_of(args[0])
            return "union", None
        # A REAL CONTAINER, AND THE CONTAINER IS PART OF THE CONTRACT.
        #
        # The unwrap rule above was written for Optional and silently ate this case:
        # `Optional[list[str]]` unwrapped to `list[str]`, then unwrapped AGAIN to `str`, so
        # `plan_site_load.window` was declared a scalar. Measured consequence, on real
        # bytes: a router filling that slot from "in FY26-Q4" sends the STRING, the measure
        # iterates it, and the engine refuses with
        #   422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4
        # — a message that names characters and blames the engine for the declaration's
        # lie. `window=["FY26-Q4"]` returns the one period that was asked for.
        #
        # So the container is reported. Enum values, if any, come from INSIDE it
        # (`list[Literal[...]]` is a multi-select over a closed vocabulary), because the
        # values are a fact about what may be said, not about how many may be said.
        inner_name, inner_values = _type_of(args[0]) if args else ("unknown", None)
        cname = getattr(origin, "__name__", None) or str(origin)
        return f"{cname}[{inner_name}]", inner_values
    name = getattr(annotation, "__name__", None)
    return (name or str(annotation)), None


#: A spoken slot whose value is an OPAQUE ID, mapped to the kind of thing it identifies.
#:
#: WHY THIS IS DECLARED RATHER THAN SNIFFED. `site_id` and `window` are both `str` to a type
#: system, and the difference — one names a thing in the model, the other is a literal the
#: speaker supplies — is the same fact `kind` carries for route-supplied slots. A consumer
#: that guessed from the `_id` suffix would be re-deriving a convention downstream, which is
#: the hand-maintained shape this module exists to remove. Measured cost of not declaring it:
#: the filler emitted `site_id="Aurora"` at 0.92 confidence and the engine answered
#: `422 unknown site 'Aurora'` — see docs/plans/the-filler-has-no-entity-resolution.md.
#:
#: The map is from the PARAMETER name, so `scope_initiative_id` resolves against initiatives
#: rather than against a class called "scope initiative" that does not exist.
#: The value is the CLASS URI, not a bare kind name, so a consumer filtering resolver
#: candidates compares `class_uri == referent` and needs no second map of its own. A kind
#: name would have to be translated to a class somewhere, and that somewhere becomes the
#: second registry this arc keeps paying for.
_IDP = "http://invincible-agent/idp#"
_REFERENT_KIND = {
    "site_id":             _IDP + "Site",
    "capability_id":       _IDP + "Capability",
    "project_id":          _IDP + "Project",
    "process_id":          _IDP + "BusinessProcess",
    "tech_id":             _IDP + "Technology",
    "scope_initiative_id": _IDP + "Initiative",
}


#: Slots whose value is a fiscal period, and the vocabulary they take.
#:
#: SOURCED FROM `FISCAL_PERIODS`, THE CODE'S OWN TABLE — not from a loaded plan's
#: `period_caps`. The first version took it from the data and was WRONG IN THE RESTRICTIVE
#: DIRECTION: the seed funds five periods while the calendar declares eight, so the router
#: refused `FY27-Q2` as not-a-permitted-value while the measure accepted it and returned a
#: row. A legitimate question, refused before it reached the thing that could answer it.
#:
#: It is the same defect this arc keeps meeting — a declaration disagreeing with the code it
#: describes — inverted. The earlier instances (`direction: str`, `Optional[list[str]]`) were
#: too PERMISSIVE and invited a wrong answer; this one was too RESTRICTIVE and refused a right
#: one. Both come from deriving a contract from something other than the contract: there, from
#: a type that had lost information; here, from data that was never the vocabulary.
#:
#: `_periods()` in measures.py validates against `FISCAL_PERIODS`, so that is the authority and
#: this reads the same constant. No registration-time enrichment is needed, because the
#: vocabulary is not data-dependent at all — which is why `with_live_vocabularies` is gone
#: rather than corrected.
#: PERIOD SLOTS AND WHAT EACH ACTUALLY TAKES. Both are annotated `str` in the signature and
#: they are NOT the same vocabulary — which is the third instance of a declaration less
#: precise than the code it describes, and the one that survived past the carry.
#:
#:   "fiscal-period"  a label from FISCAL_PERIODS ("FY26-Q4"). `window` — validated, because
#:                    `_periods()` rejects anything outside that table.
#:   "date"           an ISO date ("2026-09-30"). `as_of` — compared LEXICALLY against
#:                    `assessed_at`, so a fiscal label is not a weak filter but a COMPLETE
#:                    NO-OP: ('9999-12-31' <= 'FY26-Q4') is True, and as_of="FY26-Q4" returns
#:                    the unfiltered set byte-identical to passing nothing.
#:
#: `as_of` DELIBERATELY CARRIES NO `values` YET. Giving it the fiscal vocabulary would make
#: the router accept exactly the values the measure silently ignores — a guard certifying a
#: no-op, which is worse than no guard because it looks like coverage. The vocabulary and the
#: acceptance move together, when fiscal->date resolution lands.
_PERIOD_KIND = {
    "window": "fiscal-period",
    "as_of": "date",
}

#: The subset whose vocabulary is validated as a permitted-value set.
_PERIOD_SLOTS = {name for name, kind in _PERIOD_KIND.items() if kind == "fiscal-period"}


def _resolve_period_to_date() -> dict:
    """Fiscal label -> the date a `period: "date"` slot should be given for it.

    THE END of the period, because `as_of` means "as things stood at the end of X". A start
    date would answer a different question and would do it silently.

    Carried ON THE DECLARATION rather than resolved inside the router, for the same reason
    the enum vocabulary is: the router must not hold a second copy of the fiscal calendar.
    `FISCAL_PERIODS` stays the one place the convention lives, and the declaration is how it
    travels to whoever needs it.

    THIS FUNCTION'S EXISTENCE IS THE TRIPWIRE MARKER. The paired test asserts that a
    `period: "date"` slot carries these boundaries exactly when this resolution exists —
    boundaries without resolution certify a no-op, resolution without boundaries leaves the
    silent path open, and both are failures.
    """
    return {label: iv.end for label, iv in FISCAL_PERIODS.items()}


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
        # WHAT KIND OF THING THIS SLOT NAMES, when it names one. Present only on spoken
        # slots: a route-supplied handle is resolved by the dispatcher and needs no
        # referent hint. Absent means "a literal the speaker supplies", which is the
        # common case and needs no resolution.
        if kind.startswith("spoken") and name in _REFERENT_KIND:
            rec["referent"] = _REFERENT_KIND[name]
        # A period slot's vocabulary is a fact about the calendar, not about the signature —
        # `Optional[list[str]]` says the shape and nothing about which strings are periods.
        # WHAT KIND OF PERIOD THIS SLOT TAKES — declared, because `str` does not say, and the
        # two vocabularies are different. The filler needs it to offer a date where a date is
        # wanted rather than free text; the router needs it to know which values it may check.
        if kind.startswith("spoken") and name in _PERIOD_KIND:
            rec["period"] = _PERIOD_KIND[name]
            # A date-taking period slot carries the label->date boundaries it can resolve, so
            # the router can turn "FY26-Q4" into the date the measure actually compares
            # against. Without it, the label is forwarded and the measure's LEXICAL compare
            # silently admits everything: ('9999-12-31' <= 'FY26-Q4') is True.
            # BOTH period kinds carry the calendar, for different reasons. A `date` slot
            # needs it to RESOLVE a label to a date. A `fiscal-period` slot needs it so the
            # router can work out which period contains today — the ANCHOR that makes "this
            # quarter" answerable — without holding a second copy of the calendar.
            rec["period_end"] = _resolve_period_to_date()
        if kind.startswith("spoken") and name in _PERIOD_SLOTS and values is None:
            values = list(FISCAL_PERIODS)
        if values is not None:
            rec["values"] = values
        if not required and prm.default is not None:
            rec["default"] = prm.default if isinstance(
                prm.default, (str, int, float, bool)
            ) else str(prm.default)
        out.append(rec)
    return out
