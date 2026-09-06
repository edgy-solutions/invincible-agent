"""Slot declarations for engine-cost's six verbs, DERIVED from the measure signatures.

BORN DECLARING, like Engine F and for the same reason: a router that cannot see a slot is
missing knows only that nothing cleared threshold, so a slot-shaped question surfaces as
NO_VERB_CLASSIFIED — an INFORMATION gap wearing a threshold gap's clothes.

`rate_vintage` is why this engine had to declare from its first registration. It IS the
designed refusal (see `entities.VintageRequired`), and a refusal the router cannot see is a
refusal that never fires: the question routes, the verb raises, and a caller gets a Python
error where they should have got a menu of vintages.

── DERIVED, NOT HAND-KEPT ──────────────────────────────────────────────────────────────
Names, types, defaults and mandatory-ness are read from `inspect.signature`. Nothing below
restates what the signature already says, so a parameter renamed in `measures.py` moves its
declaration with it instead of leaving a stale literal behind.

── THE ONE FACT NO TYPE SYSTEM CARRIES ─────────────────────────────────────────────────
Lane 1's finding, and it holds here: two `str` parameters can have opposite provenance —
one supplied by the route from context, the other necessarily spoken — and a type system
cannot tell them apart. So KIND is declared by hand wherever mandatory-ness does not already
imply it.

── ON THE DUPLICATION WITH finance_agent/slots.py AND planning_agent/slots.py ───────────
THIS IS THE THIRD COPY, and both prior copies' authors named the third as the point where
duplication "stops being a cost and becomes the defect"
(`agent_fleet/finance_agent/slots.py`). This module is deliberately the THINNEST of the
three — it derives names/types/defaults and declares kinds, and does NOT re-implement the
referent map or arity, precisely so the extraction to `agent_fleet/utils/slot_declarations.py`
has less to reconcile rather than more. **The extraction is on ADR-0046 §9 slice 1's
critical path and is filed, not fixed here**; adding a full third derivation would have made
it strictly harder while this engine gained nothing from it.

── ENGINE-COST HAS NO HANDLE SLOTS AND NO CEREMONY VERBS, and that is a FACT rather than
an omission. Nothing here mutates state, so there is no ceremony to supply; and no verb
takes a route-injected scenario handle, because cost reporting is governed READING over a
fixed seed. Both kinds are declared below as empty rather than left out, so a reader who
finds only two of the four kinds used can tell the other two were considered.
"""
from __future__ import annotations

import inspect
import typing
from decimal import Decimal
from typing import Any, Dict, List

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    import measures
    from entities import COST, CostCategory
except ImportError:
    from agent_fleet.cost_agent import measures
    from agent_fleet.cost_agent.entities import COST, CostCategory

#: The four-kind vocabulary Lane 1 established. Reproduced verbatim, in order, so a consumer
#: reading declarations from any engine sees one vocabulary rather than three that agree.
SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")

#: Injected by the route, never spoken. EMPTY FOR THIS ENGINE — see the module docstring.
HANDLE_SLOTS: Dict[str, set] = {}

#: Verbs whose parameters arrive through a governed UI flow. EMPTY: nothing here mutates.
CEREMONY_VERBS: set = set()

#: The state handle. Never a parameter in any sense a caller would recognize.
_NOT_A_SLOT = {"state"}

#: A spoken slot whose value NAMES an instance, mapped to the CLASS URI of what it names.
#: Declared rather than sniffed from an `_id`/`lot` suffix: Lane 1 measured the cost of
#: guessing — the filler emitted a plausible value at 0.92 confidence and the engine
#: answered an honest 422 to a perfectly answerable question.
_REFERENT_KIND: Dict[str, str] = {
    "lot": COST + "ProductionLot",
}

#: Enum vocabularies, READ OUT OF THE TYPE so they cannot drift from what the verbs accept.
#: `category` is the five accounting buckets; the Literal in `entities.py` is the source.
_ENUM_VALUES: Dict[str, List[str]] = {
    "category": list(typing.get_args(CostCategory)),
}


def _type_of(annotation: Any) -> str:
    """A wire-level type name for a declaration. Unwraps Optional[...] to its inner type."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(origin) == "typing.Union":
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _type_of(args[0])
        return "string"
    if annotation in (int,):
        return "integer"
    if annotation in (Decimal, float):
        return "number"
    if annotation in (bool,):
        return "boolean"
    return "string"


def slots_for(fn_name: str) -> List[dict]:
    """Declarations for one verb, derived from its signature.

    KIND RULES, stated here because they are the judgment the signature cannot make:
      * a parameter with NO DEFAULT is spoken-mandatory — the caller must say it
      * a parameter WITH a default is spoken-optional
      * `rate_vintage` is spoken-mandatory WHEREVER IT APPEARS WITHOUT A DEFAULT, and that
        is the engine's designed refusal rather than an accident of signature order
    """
    fn = measures.VERBS[fn_name]
    # eval_str=True IS LOAD-BEARING, NOT TIDINESS. `measures.py` carries
    # `from __future__ import annotations`, so without it every annotation arrives as the
    # STRING "int" and `_type_of` falls through to its default — declaring `lot` a string
    # to every consumer while the verb takes an integer. Caught on the first derivation
    # run here; both sibling copies carry the same handling for the same reason.
    sig = inspect.signature(fn, eval_str=True)
    out: List[dict] = []
    for name, p in sig.parameters.items():
        if name in _NOT_A_SLOT or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        mandatory = p.default is inspect.Parameter.empty
        decl: dict = {
            "name": name,
            "type": _type_of(p.annotation),
            # THE WIRE KEY IS `required`, NOT `mandatory`, AND THE CONSUMER IS WHY.
            # agent_fleet/ontology_service/main.py:2673 builds the slot-filling prompt and
            # marks a slot REQUIRED from `d.get("required")`. This engine originally emitted
            # `mandatory`, which that line never reads — so every spoken-mandatory slot here
            # went to the filler UNMARKED. The cost is a weaker fill and a needless ask
            # rather than a wrong answer, which is exactly why it survived: nothing failed.
            # Engines F and P both emit `required`; this file was the odd one out, and the
            # divergence was found by the lane scoping the shared-derivation extraction.
            # Settled HERE, before that extraction, so it does not inherit a disagreement as
            # if it were a feature.
            "required": mandatory,
            "kind": "spoken-mandatory" if mandatory else "spoken-optional",
        }
        if not mandatory and p.default is not None:
            decl["default"] = p.default
        if name in _REFERENT_KIND:
            # Only SPOKEN slots carry a referent — a handle is resolved by the dispatcher
            # from the store and was never something a speaker names.
            decl["referent"] = _REFERENT_KIND[name]
        if name in _ENUM_VALUES:
            decl["values"] = _ENUM_VALUES[name]
        out.append(decl)
    return out


def all_declarations() -> Dict[str, List[dict]]:
    """Every verb's slots, for the registration payload and for the seals."""
    return {name: slots_for(name) for name in measures.VERBS}


def mandatory_slots(fn_name: str) -> List[str]:
    """Names a caller must supply. Used to build the refusal, not just to check it."""
    return [s["name"] for s in slots_for(fn_name) if s["required"]]
