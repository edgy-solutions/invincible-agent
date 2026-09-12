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

from typing import Dict, List

try:  # flat in the image (/app), packaged in the repo — see
    # tests/test_agent_modules_survive_flat_layout.py, which seals this dual form. A bare
    # `from . import measures` imports fine here and dies at container start.
    #
    # `utils` is a SIBLING TOP-LEVEL module in the image — `COPY agent_fleet/utils/ /app/utils/`
    # in build-containers.yml — which is what makes the shared derivation importable here at
    # all (runbook §5). FLAT FIRST: getting this order backwards cost Engine P a full roll,
    # where the import failed, the registration helper became None, and twelve registrations
    # were skipped while the engine reported perfectly healthy.
    import measures
    from entities import FISCAL_PERIODS
    from utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots
except ImportError:
    from agent_fleet.planning_agent import measures
    from agent_fleet.planning_agent.entities import FISCAL_PERIODS
    from agent_fleet.utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots

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
#: The shared default says the same thing; bound here so the engine still names its own fact.
_NOT_A_SLOT = NOT_A_SLOT

# `SLOT_KINDS`, `_is_union` and `_type_of` MOVED 2026-09-11 to
# `agent_fleet/utils/slot_declarations.py`, at the third consumer (Engine S, ADR-0051 §4) and
# on the trigger Engine F's own FILED-NOT-FIXED note named. `SLOT_KINDS` is re-exported above
# so every existing `from slots import SLOT_KINDS` keeps working and there is still exactly one
# definition of the vocabulary.
#
# The two asymmetries this module paid for in measured failures — `eval_str=True`, and
# unwrapping `Optional[X]` but STOPPING at a real container — moved WITH their evidence and
# are sealed in `tests/utils/test_slot_declarations_extraction.py`. If you are here because a
# declaration looks wrong, read that file: the derivation is no longer in this one.


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


def _attach_period_vocabulary(rec: dict, *, name: str, prm, kind: str, values):
    """Engine P's own enrichment, passed to the shared derivation as its `decorate` hook.

    THIS IS THE PART THAT IS NOT SHARED, and it is not shared because it is a fact about a
    CALENDAR rather than about a signature — `Optional[list[str]]` says the shape and nothing
    about which strings are periods.

    WHAT KIND OF PERIOD THIS SLOT TAKES — declared, because `str` does not say, and the two
    vocabularies are different. The filler needs it to offer a date where a date is wanted
    rather than free text; the router needs it to know which values it may check.
    """
    if kind.startswith("spoken") and name in _PERIOD_KIND:
        rec["period"] = _PERIOD_KIND[name]
        # A date-taking period slot carries the label->date boundaries it can resolve, so the
        # router can turn "FY26-Q4" into the date the measure actually compares against.
        # Without it the label is forwarded and the measure's LEXICAL compare silently admits
        # everything: ('9999-12-31' <= 'FY26-Q4') is True.
        # BOTH period kinds carry the calendar, for different reasons. A `date` slot needs it
        # to RESOLVE a label to a date. A `fiscal-period` slot needs it so the router can work
        # out which period contains today — the ANCHOR that makes "this quarter" answerable —
        # without holding a second copy of the calendar.
        rec["period_end"] = _resolve_period_to_date()
    if kind.startswith("spoken") and name in _PERIOD_SLOTS and values is None:
        values = list(FISCAL_PERIODS)
    return values


def slots_for(fn_name: str) -> List[dict]:
    """The slot declarations for one measure, derived from its signature.

    The derivation itself lives in `utils/slot_declarations.py` (extracted at the third
    consumer). What stays here is what is Engine P's: which parameters the route injects,
    which verb is a ceremony, which names are referents and to what classes, and the fiscal
    calendar the signature cannot carry.
    """
    fn = getattr(measures, fn_name, None)
    if fn is None:
        return []
    return derive_slots(
        fn,
        handles=HANDLE_SLOTS.get(fn_name, set()),
        ceremony=fn_name in CEREMONY_VERBS,
        referents=_REFERENT_KIND,
        not_a_slot=_NOT_A_SLOT,
        decorate=_attach_period_vocabulary,
    )


def arity_for(fn_name: str) -> str | None:
    """QUERY-SHAPE eligibility, derived from the signature — never hand-transcribed.

    "single" when the measure CANNOT RUN without one named instance: it has a slot that is
    both REQUIRED and a REFERENT. Otherwise None, which the supervisor's gate reads as
    "any" and never excludes.

    WHY THOSE TWO CONDITIONS AND NOT THE PROSE. `plan_dependency_neighborhood` and
    `plan_dependency_violations` have descriptions a paragraph apart and opposite arities;
    the discriminator that is actually load-bearing is in the signature —
    `project_id: str` with NO default versus no such parameter at all. A required referent
    means the question has to name something; an optional one is a FILTER on a
    portfolio-wide answer (`plan_schedule`'s `scope_initiative_id`) and leaves the verb
    set-shaped.

    WHAT THIS BUYS — AND WHAT CHANGED 2026-09-04. `_filter_verbs_by_arity` marks a "single"
    verb `needs_instance` when `query_is_set = not subject_instance_id`. It originally
    DROPPED it, to avoid the 400 named in
    docs/plans/a-missing-mandatory-slot-is-a-400-not-an-ask.md — but that 400 is now an ASK,
    and excluding the verb cost H06 its answer: "what is the capability path" grounded to
    Capability and then reported no-verb-classified, because the only verb that fit was
    removed for the very reason it would have asked.

    THE DERIVATION IS WHAT MAKES KEEPING IT SAFE. "single" means the measure has a slot that
    is both required and a referent — which is exactly the condition the disposition asks
    about. So a kept single verb whose instance was never named reaches an ask or an abstain
    and cannot dispatch silently. The gate's guarantee did not weaken; it moved to the layer
    that can offer a menu instead of a refusal.

    ROUTE-SUPPLIED HANDLES CANNOT TRIGGER THIS, and that falls out rather than being
    special-cased: `slots_for` sets `referent` only on SPOKEN slots, because a handle is
    resolved by the dispatcher from the store and was never something a speaker names.
    `plan_commit_scenario` has nine slots and stays set-shaped for exactly that reason.

    Derived for four of the fourteen measures and for none of the other ten — a lumpy split,
    which is the shape a real discriminator produces. Pinned in
    tests/planning/test_arity_is_derived_from_the_signature.py so a signature change moves
    the declaration with it instead of leaving a stale literal behind.
    """
    for d in slots_for(fn_name):
        if d.get("required") and d.get("referent"):
            return "single"
    return None
