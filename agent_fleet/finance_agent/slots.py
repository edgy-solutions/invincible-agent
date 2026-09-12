"""Slot declarations for Engine F's six verbs, DERIVED from the measure signatures.

BORN DECLARING. Every engine before this one registered what a verb is ABOUT (`input_uri`)
and what it PRODUCES (`output_uri`) and never what it TAKES — so the router could not know a
slot was missing, only that nothing cleared threshold, which is why a slot-shaped question
surfaced as `NO_VERB_CLASSIFIED` (an INFORMATION gap wearing a threshold gap's clothes) and
why a spoken parameter was dropped in silence on every verb that had a default for it.

Engine F is the first engine to declare from its first registration. Nothing here is
retrofitted, and `fin_eac_calculation` is the reason it had to be: its mandatory `method`
slot IS the engine's designed refusal (ADR-0045), and a refusal the router cannot see is a
refusal that never fires.

── DERIVED, NOT HAND-KEPT ──────────────────────────────────────────────────────────────────
Names, types, enum values, defaults and mandatory-ness are read from `inspect.signature`.
The three EAC method names CANNOT drift from `EACMethod` because they are read out of the
`Literal`, in the same edit that would add a fourth formula. This repo has paid five times
for lists someone remembered instead of enumerated; this is not the sixth.

── ON THE DUPLICATION WITH `planning_agent/slots.py`, WHICH IS REAL ─────────────────────────
Lane 1 landed the same derivation for Engine P. This module is a SECOND implementation of it,
and that is a deliberate cost paid for two reasons: the extraction target would be
`agent_fleet/utils/`, which is shared code another lane is currently in; and the flat image
layout (`/app` IS the engine directory) means a cross-engine import does not survive
containerisation — `tests/test_agent_modules_survive_flat_layout.py` seals exactly that.

**FILED, NOT FIXED:** the derivation belongs in `agent_fleet/utils/slot_declarations.py`,
imported by both engines under the same flat/packaged idiom the mesh helpers already use.
Two copies of a derivation is precisely the shape both copies exist to remove, and a third
engine is the point at which it stops being a cost and becomes the defect.

── THE ONE FACT NO TYPE SYSTEM CARRIES ─────────────────────────────────────────────────────
Lane 1's finding, and it holds here: two `str` parameters can have opposite provenance —
one supplied by the route from context, the other necessarily spoken — and a type system
cannot tell them apart. So the KIND is declared by hand wherever mandatory-ness does not
already imply it.

**ENGINE F HAS NO HANDLE SLOTS AND NO CEREMONY VERBS, and that is a FACT rather than an
omission.** Engine P has both because it owns state a room creates: `baseline_state` is
resolved by the route, and the commit ceremony's rationale arrives through a governed UI
flow. Engine F does neither — ADR-0045 Decision 1 is that finance analysis is governed
READING, so there is no scenario handle to inject and no ceremony to supply. The two empty
kinds are declared below as empty rather than left out, because a reader who finds only two
of the four kinds used cannot otherwise tell whether the other two were considered.
"""
from __future__ import annotations

from typing import Dict, List

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    import measures
    from entities import FISCAL_PERIODS
    from utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots
except ImportError:
    from agent_fleet.finance_agent import measures
    from agent_fleet.finance_agent.entities import FISCAL_PERIODS
    from agent_fleet.utils.slot_declarations import NOT_A_SLOT, SLOT_KINDS, derive_slots

# `SLOT_KINDS` is now IMPORTED rather than reproduced. This module's note said it was
# "reproduced verbatim, in order, so a consumer reading declarations from either engine sees one
# vocabulary rather than two that agree" — two that agree is exactly what an extraction removes,
# and the re-export keeps every `from slots import SLOT_KINDS` working.

#: Injected by the route, never spoken. EMPTY FOR THIS ENGINE — see the module docstring.
#: Present as an empty mapping rather than absent, so that adding a route-supplied parameter
#: later has an obvious home and does not become a `str` silently declared spoken.
HANDLE_SLOTS: Dict[str, set] = {}

#: Verbs whose parameters arrive through a governed UI flow. EMPTY FOR THIS ENGINE: no
#: finance verb mutates anything, so there is no ceremony to supply.
CEREMONY_VERBS: set = set()

#: The measure's own state handle. Never a parameter in any sense a caller would recognise.
#: The shared default says the same thing; bound here so the engine still names its own fact.
_NOT_A_SLOT = NOT_A_SLOT

_FIN = "http://invincible-agent/fin#"

#: A spoken slot whose value is an OPAQUE ID, mapped to the CLASS URI of the thing it names.
#:
#: WHY DECLARED RATHER THAN SNIFFED FROM THE `_id` SUFFIX. Lane 1 measured the cost of not
#: declaring it: the filler emitted `site_id="Aurora"` at 0.92 confidence and the engine
#: answered `422 unknown site 'Aurora'` — an honest refusal to a perfectly answerable
#: question. Guessing from the suffix would re-derive a naming convention downstream, which
#: is the hand-maintained shape this module exists to remove.
#:
#: THE VALUE IS THE CLASS URI, NOT A KIND NAME, so a consumer filtering resolver candidates
#: compares `class_uri == referent` and needs no second map of its own.
_REFERENT_KIND = {
    "program_id": _FIN + "Program",
    "ca_id":      _FIN + "ControlAccount",
    # ── NOT ATTACHED TO ANY SLOT TODAY, and that is stated rather than left to be noticed.
    # No verb declares `wp_id`, `wbs_id` or `obs_id`, so these three entries are INERT:
    # `slots_for` only attaches a referent to a parameter that actually exists. Found
    # 2026-08-30 while measuring the resolvable-vs-routable asymmetry — the same measurement
    # that found the dead-end classes, looked at from the slot side.
    #
    # KEPT rather than deleted, because the drill-down is where they become live: the variance
    # tree already reaches work packages, and a verb that takes one is the obvious next step.
    # `test_referent_map_entries_are_attached_or_declared` asserts this set stays HONEST — an
    # entry here that neither attaches nor appears below is a claim about a slot that does not
    # exist, which is the remembered-list shape this module was written to remove.
    "wp_id":      _FIN + "WorkPackage",
    "wbs_id":     _FIN + "WBSElement",
    "obs_id":     _FIN + "OBSElement",
}

#: The `_REFERENT_KIND` keys that intentionally have no slot yet (see the note above).
UNATTACHED_REFERENTS = {"wp_id", "wbs_id", "obs_id"}

#: Slots whose value is a fiscal period. Their vocabulary is DATA, not a `Literal`, so it
#: cannot come from the signature — `window: Optional[list[str]]` states the shape and
#: nothing about which strings are periods. Attached by `with_live_vocabularies` below.
_PERIOD_SLOTS = {"window"}


# `_is_union` and `_type_of` MOVED 2026-09-11 to `agent_fleet/utils/slot_declarations.py`, at
# the third consumer (Engine S, ADR-0051 §4) — the trigger this module's own FILED-NOT-FIXED
# note named. The container-is-part-of-the-contract evidence moved with them, because the
# knowledge is what makes the rule survive an edit.
#
# ONE LOCAL NOTE DID NOT MOVE, because it is Engine F's rather than the derivation's: this
# engine's `periods_in` also wraps a bare string defensively, so a wrong container declaration
# would be survivable here. It is still declared correctly — a runtime that tolerates a wrong
# declaration does not make the declaration right, and the tolerance is a second line rather
# than a licence.


def with_live_vocabularies(
    records: List[dict], *, periods: List[str] | None = None
) -> List[dict]:
    """Attach data-dependent vocabularies to declarations that cannot carry their own.

    WHY THIS IS SEPARATE FROM `slots_for`. Enum values come from a `Literal` and are a fact
    about the CODE; fiscal periods come from the loaded model and are a fact about the DATA.
    Folding the second into the first would make `slots_for` depend on a store, and a pure
    signature-derivation is worth keeping pure. Registration calls both, because registration
    is the moment both are in hand.

    MEASURED CONSEQUENCE OF NOT DOING THIS, on the planning side: the filler answered "what
    does spend look like this quarter" with `window: ["this quarter"]` — not an invented
    period, the raw words — which reaches the measure and raises `unknown fiscal period(s)`.
    With the vocabulary attached, the router refuses it using the enum check it already has.
    """
    values = list(periods) if periods else list(FISCAL_PERIODS)
    out = []
    for r in records:
        if r["name"] in _PERIOD_SLOTS and not r.get("values"):
            r = {**r, "values": values}
        out.append(r)
    return out


def slots_for(fn_name: str) -> List[dict]:
    """The slot declarations for one verb, derived from its signature.

    The derivation lives in `utils/slot_declarations.py`. What stays here is Engine F's own:
    that it has NO handles and NO ceremonies (a fact, not an omission — ADR-0045 Decision 1
    makes this governed reading), and which names are referents and to what class URIs.

    No `decorate` hook: this engine's one data-dependent vocabulary is attached by
    `with_live_vocabularies` at registration, deliberately kept out of the pure derivation.
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
    )


def missing_mandatory(fn_name: str, params: dict) -> List[dict]:
    """The spoken-mandatory slots this call did not supply. The refusal's source of truth.

    THE REFUSAL IS BUILT FROM THE DECLARATION, WHICH IS THE POINT. `fin_eac_calculation`
    refuses a bare "what's the EAC" by naming the three methods — and those three names come
    out of the `Literal` through `slots_for`, not out of a message someone typed. A fourth
    formula added to `EACMethod` therefore appears in the refusal on the same edit that adds
    it, and a message and a signature that cannot disagree is the only kind that stays true.

    A value of `None` counts as NOT SUPPLIED. A router that fills a slot it could not
    resolve with an explicit null is reporting a gap, not answering one, and treating the
    key's presence as sufficient would convert that report into a `TypeError` three frames
    down — which is the same class of failure as the empty-result-means-absent one the
    measures refuse.
    """
    return [
        s for s in slots_for(fn_name)
        if s["kind"] == "spoken-mandatory" and params.get(s["name"]) is None
    ]


def refusal_for(fn_name: str, missing: List[dict]) -> str:
    """The message a missing-slot refusal carries. Names the CHOICE, never the field.

    "missing required parameter: method" is a dead end wearing a gate's clothes — it tells
    the asker they were wrong without telling them what would be right. Where the slot has a
    closed vocabulary, the options are named; where it names a thing in the model, the class
    is named so the asker knows what KIND of thing to say.
    """
    parts: List[str] = []
    for slot in missing:
        if slot.get("values"):
            parts.append(f"which {slot['name']} — " + ", ".join(slot["values"]) + "?")
        elif slot.get("referent"):
            kind = slot["referent"].rsplit("#", 1)[-1]
            parts.append(f"which {kind}?")
        else:
            parts.append(f"what {slot['name']}?")
    return " ".join(parts)
