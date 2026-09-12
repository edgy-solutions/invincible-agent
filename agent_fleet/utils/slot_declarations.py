"""The slot derivation, extracted at the THIRD consumer.

WHY THIS FILE EXISTS, AND WHY NOW. Lane 1 landed the derivation for Engine P; Engine F landed a
second implementation of it and filed the duplication rather than fixing it, for two reasons that
were true at the time — `agent_fleet/utils/` was shared code another lane was in, and a cross-engine
import has to survive containerisation. Its own note named the trigger:

    "a third engine is the point at which it stops being a cost and becomes the defect."

Engine S (sustainment safety, ADR-0051 §4) is the third engine. So this is that extraction, and the
third copy is refused by name.

── THE CONTAINERISATION QUESTION, ANSWERED RATHER THAN ASSUMED ─────────────────────────────────
The objection on file was that a cross-engine import does not survive the flat image layout, where
`COPY ${AGENT_DIR}/ /app/` puts one engine's modules flat at the top of the interpreter's path and
`agent_fleet` does not exist. That objection is real for an import of another ENGINE. It does not
apply here, because `.github/workflows/build-containers.yml:356` copies this directory into every
engine image:

    COPY agent_fleet/utils/ /app/utils/

So `utils.slot_declarations` resolves flat in the image and `agent_fleet.utils.slot_declarations`
resolves packaged in the repo — the same dual form `utils.mesh_registration` and
`utils.version_endpoint` already use from six engines. Consumers import it with the house
try/except idiom (runbook §5), NOT with a bare relative import, which dies at container start.

── WHAT IS SHARED AND WHAT IS DELIBERATELY NOT ─────────────────────────────────────────────────
Shared: HOW an annotation becomes a declaration — union unwrapping, container preservation, enum
extraction, the `eval_str=True` signature read, and the record's shape and field order.

NOT shared, and each engine keeps its own: WHICH parameters are route-supplied handles, WHICH verbs
are ceremonies, WHICH names are referents and to what class URIs, and any data-dependent vocabulary.
Those are facts about a domain, not about derivation, and folding them in would make this module the
registry that both copies exist to remove.

The extension point is `decorate`, and it is deliberately narrow: it may enrich the record and may
replace the enum values, and it cannot change the record's identity fields. Engine P uses it for the
fiscal-period vocabulary; Engine F passes nothing.

── THE TWO ASYMMETRIES THAT MUST SURVIVE ANY EDIT TO THIS FILE ─────────────────────────────────
Both were paid for in measured failures, both are sealed, and both live in `type_of`/`signature_of`
below with the evidence attached. Do not "simplify" either one:

  1. `eval_str=True`, because the engines use `from __future__ import annotations` and without it
     every `Literal` arrives as its own literal TEXT.
  2. Unwrap `Optional[X]` but STOP at a real container, because unwrapping twice declares a
     multi-valued slot a scalar.
"""
from __future__ import annotations

import inspect
import types
import typing
from typing import Any, Callable, Dict, Iterable, List, Optional

#: The four-kind vocabulary, established by Lane 1 and reproduced here as the single copy.
#: Order is part of it: a consumer reading declarations from any engine sees one vocabulary
#: rather than several that happen to agree.
SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")

#: The measure's own state handle. Never a parameter in any sense a caller would recognise.
#: Overridable per engine, because "what is not a slot" is an engine's fact, but every engine
#: so far agrees and the default saves each one restating it.
NOT_A_SLOT = frozenset({"state"})


def is_union(origin: Any) -> bool:
    """`Optional[X]` and `X | None` have DIFFERENT origins (`typing.Union` and
    `types.UnionType`), and both must be treated as unwrappable — otherwise the same annotation
    declares differently depending on which syntax the author happened to use."""
    if origin is typing.Union:
        return True
    UnionType = getattr(types, "UnionType", None)  # 3.10+; absent on older runtimes
    return UnionType is not None and origin is UnionType


def type_of(annotation: Any) -> tuple[str, List[str] | None]:
    """(type-name, enum-values) read from the annotation — never from a remembered list."""
    if annotation is inspect.Parameter.empty:
        return "unknown", None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return "enum", [str(v) for v in typing.get_args(annotation)]
    if origin is not None:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        # Optional[X] / X | None — unwrap to the single remaining arm.
        if is_union(origin):
            if len(args) == 1:
                return type_of(args[0])
            return "union", None
        # A REAL CONTAINER, AND THE CONTAINER IS PART OF THE CONTRACT.
        #
        # The unwrap rule above was written for Optional and silently ate this case:
        # `Optional[list[str]]` unwrapped to `list[str]`, then unwrapped AGAIN to `str`, so a
        # multi-valued slot was declared a scalar. Measured consequence, on real bytes: a router
        # filling that slot from "in FY26-Q4" sends the STRING, the measure iterates it, and the
        # engine refuses with
        #     422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4
        # — a message that names CHARACTERS and blames the engine for the declaration's lie.
        #
        # So the container is reported. Enum values, if any, come from INSIDE it
        # (`list[Literal[...]]` is a multi-select over a closed vocabulary), because the values
        # are a fact about what may be said, not about how many may be said.
        inner_name, inner_values = type_of(args[0]) if args else ("unknown", None)
        cname = getattr(origin, "__name__", None) or str(origin)
        return f"{cname}[{inner_name}]", inner_values
    name = getattr(annotation, "__name__", None)
    return (name or str(annotation)), None


def signature_of(fn: Callable) -> inspect.Signature:
    """The signature, with string annotations RESOLVED.

    `eval_str=True` because the engines' `measures.py` use `from __future__ import annotations`,
    which makes every annotation a STRING. Without it `Literal["CPI", ...]` arrives as the literal
    text `"Literal['CPI', ...]"` — the enum values reduced to prose, which is exactly the
    hand-maintained shape this derivation exists to avoid, arriving through the back door.

    Falls back to the UNEVALUATED signature if a forward reference will not resolve. A slot typed
    "unknown" is honest; a slot whose values were parsed out of a string is not, so the fallback
    never string-scrapes.
    """
    try:
        return inspect.signature(fn, eval_str=True)
    except Exception:  # noqa: BLE001 - an unresolvable annotation must not break registration
        return inspect.signature(fn)


def kind_for(name: str, *, required: bool, handles: Iterable[str], ceremony: bool) -> str:
    """Which of `SLOT_KINDS` this parameter is.

    THE ONE FACT NO TYPE SYSTEM CARRIES, and the reason `handles` is passed in rather than
    inferred: two `str` parameters can have opposite provenance — one supplied by the route from
    context, the other necessarily spoken — and a type system cannot tell them apart. So the kind
    is declared by the engine wherever mandatory-ness does not already imply it.
    """
    if name in handles:
        return "handle"
    if ceremony:
        return "ceremony"
    return "spoken-mandatory" if required else "spoken-optional"


def derive_slots(
    fn: Callable,
    *,
    handles: Iterable[str] = (),
    ceremony: bool = False,
    referents: Optional[Dict[str, str]] = None,
    not_a_slot: Iterable[str] = NOT_A_SLOT,
    decorate: Optional[Callable[..., List[str] | None]] = None,
) -> List[dict]:
    """One verb's slot declarations, derived from its signature.

    `referents` maps a PARAMETER name to the CLASS URI of the thing it identifies, and is attached
    only to spoken slots — a route-supplied handle is resolved by the dispatcher and needs no
    referent hint. The value is the class URI rather than a kind name so a consumer comparing
    `class_uri == referent` needs no second map of its own; a kind name would have to be translated
    to a class somewhere, and that somewhere becomes the second registry this arc keeps paying for.

    `decorate(rec, name=, prm=, kind=, values=)` is called after the identity fields and `referent`
    are set and before `values` and `default` are written. It may add keys to `rec`, and it RETURNS
    the enum values — unchanged, or replaced with a data-dependent vocabulary the signature cannot
    carry. Returning `None` leaves the slot with no `values` key.
    """
    handles = frozenset(handles)
    not_a_slot = frozenset(not_a_slot)
    out: List[dict] = []
    for name, prm in signature_of(fn).parameters.items():
        if name in not_a_slot:
            continue
        required = prm.default is inspect.Parameter.empty
        type_name, values = type_of(prm.annotation)
        kind = kind_for(name, required=required, handles=handles, ceremony=ceremony)
        rec: dict = {"name": name, "kind": kind, "type": type_name, "required": required}
        # WHAT KIND OF THING THIS SLOT NAMES, when it names one. Present only on spoken slots;
        # absent means "a literal the speaker supplies", which is the common case.
        #
        # Measured cost of not declaring it: the filler emitted `site_id="Aurora"` at 0.92
        # confidence and the engine answered `422 unknown site 'Aurora'` — an honest refusal to a
        # perfectly answerable question, and the largest single failure class in the planning
        # corpus. Guessing from the `_id` suffix would re-derive a naming convention downstream,
        # which is the hand-maintained shape this module exists to remove.
        if kind.startswith("spoken") and referents and name in referents:
            rec["referent"] = referents[name]
        if decorate is not None:
            values = decorate(rec, name=name, prm=prm, kind=kind, values=values)
        if values is not None:
            rec["values"] = values
        if not required and prm.default is not None:
            rec["default"] = prm.default if isinstance(
                prm.default, (str, int, float, bool)
            ) else str(prm.default)
        out.append(rec)
    return out
