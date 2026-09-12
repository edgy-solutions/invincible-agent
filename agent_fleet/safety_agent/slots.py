"""Engine S's slot declarations — the THIRD consumer of the shared derivation.

BORN CONSUMING, NOT COPYING. Engine P wrote the derivation, Engine F copied it and filed the
duplication with the trigger named — "a third engine is the point at which it stops being a
cost and becomes the defect" — and this engine is that third. So there is no `_type_of` here,
no `_is_union`, and no signature-reading loop: all of it lives in
`agent_fleet/utils/slot_declarations.py` and this file declares only what is Engine S's.

That is also the seal on the extraction being real. If the shared module had been extracted
badly, this file is where it shows: a third consumer that has to reach around the abstraction
is a failed extraction, and this one declares four maps and calls one function.

── WHAT IS ENGINE S'S ──────────────────────────────────────────────────────────────────────
NO HANDLE SLOTS AND NO CEREMONY VERBS, and that is a FACT rather than an omission. Engine P
has both because it owns state a room creates; Engine F has neither because ADR-0045 makes it
governed reading. Engine S is governed reading too (ADR-0051 §3), and every mutation it might
otherwise perform is a HumanTask disposition rather than a verb — so there is no scenario
handle to inject and no ceremony to supply. Both are declared empty rather than omitted,
because a reader who finds two of four kinds used cannot otherwise tell whether the other two
were considered.

── THE REFERENT MAP, AND THE ONE ENTRY THAT POINTS OUT OF THIS ENGINE ──────────────────────
`work_order_id` resolves against the MAINTENANCE plane, not a safety class. Engine S reads
work orders and does not own them; declaring a safety-namespaced referent for one would mint a
parallel work-order concept, which is the mistake the ADR-0007 survey spent its effort
avoiding one level up (a hazard's cause is `s3kl:FailureMode`, not `safety:Cause`).
"""
from __future__ import annotations

from typing import Dict, List

try:  # flat in the image (/app), packaged in the repo — runbook §5, flat FIRST.
    # `utils` is a sibling top-level module in the image
    # (`COPY agent_fleet/utils/ /app/utils/`, build-containers.yml:356).
    import measures
    from utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots
except ImportError:
    from agent_fleet.safety_agent import measures  # type: ignore[no-redef]
    from agent_fleet.utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots

_SAFETY = "http://internal/sustainment/safety#"
_MAINT = "http://internal/maintenance#"

#: Injected by the route, never spoken. EMPTY FOR THIS ENGINE — see the docstring.
HANDLE_SLOTS: Dict[str, set] = {}

#: Verbs whose parameters arrive through a governed UI flow. EMPTY FOR THIS ENGINE:
#: no safety verb mutates anything, and the one act that governs — accepting a risk —
#: is a task disposition rather than a verb with a ceremony (ADR-0051 §5, §7).
CEREMONY_VERBS: set = set()

#: The measure's own state handle.
_NOT_A_SLOT = NOT_A_SLOT

#: A spoken slot whose value is an OPAQUE ID, mapped to the CLASS URI it names.
#: The value is the class URI, not a kind name, so a consumer filtering resolver
#: candidates compares `class_uri == referent` and needs no second map.
_REFERENT_KIND = {
    "hazard_id":     _SAFETY + "Hazard",
    "write_up_id":   _SAFETY + "WriteUp",
    # POINTS OUT OF THIS ENGINE, on purpose — see the module docstring.
    "work_order_id": _MAINT + "WorkOrder",
}

#: `scope` is referent-bound in a second sense: its VALUE names a kind of thing
#: (a tail, a platform), and `scope_value` is the thing. Declared so the filler
#: asks "which tail?" rather than putting the word "tail" in the value slot —
#: the `site_id="Aurora"` failure one level over.
_SCOPE_REFERENT = {
    "tail": _SAFETY + "Hazard",
    "platform": _SAFETY + "Hazard",
}


def _attach_scope_pairing(rec: dict, *, name: str, prm, kind: str, values):
    """Engine S's one enrichment: `scope_value` is conditional on `scope`.

    WHY THIS NEEDS DECLARING. `scope="fleet"` takes no value and `scope="tail"` requires one,
    and a type system cannot say so — both are `Optional[str]`. Without it the filler either
    always asks for a value (wrong for a fleet-wide question) or never does (silently widening
    a tail question to the fleet, which returns a DIFFERENT answer and reports it as the same).
    """
    if kind.startswith("spoken") and name == "scope_value":
        rec["required_when"] = {"slot": "scope", "value_in": ["tail", "platform"]}
        rec["referent_by"] = _SCOPE_REFERENT
    return values


def slots_for(fn_name: str) -> List[dict]:
    """One verb's slot declarations, derived from its signature."""
    fn = getattr(measures, fn_name, None)
    if fn is None:
        return []
    return derive_slots(
        fn,
        handles=HANDLE_SLOTS.get(fn_name, set()),
        ceremony=fn_name in CEREMONY_VERBS,
        referents=_REFERENT_KIND,
        not_a_slot=_NOT_A_SLOT,
        decorate=_attach_scope_pairing,
    )


def missing_mandatory(fn_name: str, params: dict) -> List[dict]:
    """The spoken-mandatory slots this call did not supply.

    A value of `None` counts as NOT SUPPLIED: a router that fills a slot it could not resolve
    with an explicit null is reporting a gap, not answering one.
    """
    return [
        s for s in slots_for(fn_name)
        if s["kind"] == "spoken-mandatory" and params.get(s["name"]) is None
    ]
