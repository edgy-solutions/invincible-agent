"""Validate spoken slot values against a verb's declarations before they are dispatched.

WHY THIS EXISTS AS ITS OWN MODULE. The carry — moving extracted slots from the router to
`req.params` — is the join that makes a spoken parameter reach a verb. It is also the join
that makes a spoken parameter reach a verb's ROUTE-SUPPLIED arguments, which is a different
and worse thing. `agent_fleet/planning_agent/main.py` injects `baseline_state`,
`touched_project_ids`, `ops` and `scenario_name` into `params` itself, from the store; a
caller who can name those keys is not parameterising a question, they are supplying the
evidence the answer is computed from.

So the carry ships with its guard from birth rather than gaining one later. Pure and
dependency-free on purpose: it is imported by the Dagster supervisor, by the BFF, and by
tests, and none of those should have to stand up the others.

THE DECLARATIONS ARE THE ACCEPTANCE SCHEMA. `mesh_slots` (derived from signatures by
`agent_fleet/planning_agent/slots.py`) is not merely router-facing metadata — it is the
contract an extraction must satisfy. That is what lets every deterministic join in the slot
pipeline be proven by fixtures, with no model in the loop.

FAIL CLOSED ON MISSING DECLARATIONS, and this is the load-bearing decision. When `declared`
is empty the verb has told us nothing about what it accepts, so nothing is accepted. Two
consequences, both wanted:

  * the carry LANDS DARK. `mesh_slots` is not projected into the graph yet (doc-tools'
    allowlist), so declarations arrive empty and every slot is refused — which is exactly
    today's behaviour, byte for byte. The pipeline lights up when the declarations arrive,
    in the order declare -> project -> honour, and never half-lit.
  * "no declarations" and "empty declarations" cannot be told apart by a consumer, so
    treating absence as permission would make an unprojected verb MORE permissive than a
    declared one. Fail-closed makes the incentive point the right way.

Refusals are returned, never raised. A refused slot is a question the system could not honour
as asked, which is a thing to log loudly and answer honestly — not a crash.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, NamedTuple, Sequence

#: An ISO calendar date, which is what a `period: "date"` slot's measure compares against.
#: Deliberately a SHAPE check and not a parse: this module is stdlib-only by its package's
#: rule, and the question here is "is this the kind of thing the measure understands", not
#: "is this a real date". A shaped-but-impossible date reaches the measure and is its to
#: judge; a fiscal label or "this quarter" never gets that far.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Slot kinds whose values come from the ROUTE, never from a speaker. `handle` is state the
#: dispatcher resolves (a store reference, a session's op list); `ceremony` is an act's own
#: bookkeeping (an actor, a commit message) that the caller does not get to assert.
ROUTE_SUPPLIED_KINDS = frozenset({"handle", "ceremony"})

#: The full vocabulary, mirrored from `agent_fleet.planning_agent.slots.SLOT_KINDS`. Mirrored
#: rather than imported because this module must not depend on an engine's package — the
#: agreement is pinned by a test instead, which is the same trade the archetype registries make.
SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")


def decode_declarations(raw: Any) -> list[dict]:
    """Normalise a verb's declarations to a list of records, whatever shape they arrive in.

    THEY ARRIVE AS A JSON STRING, and that is not an accident of transport. `slots` is a
    list of MAPS, and a Neo4j property may only be a primitive or an array of primitives —
    measured against the sandbox graph, in a rolled-back transaction:

        [{"name": "group_by", ...}]    REJECTED  Neo.ClientError.Statement.TypeError
        '[{"name": "group_by", ...}]'  ACCEPTED

    so doc-tools projects the JSON text, following the `openapi_schema` idiom rather than
    the `domains` one. Without this decode the caller does `list(raw)` on that string and
    gets a list of CHARACTERS — every "declaration" a one-character string, `d["name"]`
    raising on each. That is the same shredding the `window` slot already produced once
    (`422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4`), and it is the shape this repo
    keeps meeting: a container silently traded for its elements.

    Accepts a decoded list too, so fixtures and any future projection that can carry
    structure need no special case. Anything unparseable is `[]` — which the guard treats
    as "declare nothing, accept nothing", so a corrupt declaration fails CLOSED.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    return [d for d in raw if isinstance(d, Mapping) and d.get("name")]


class Refusal(NamedTuple):
    """One slot that was NOT honoured, and why. `spoken` is kept so the log can show what was
    asked for — a refusal that cannot say what it refused is not auditable."""
    name: str
    reason: str
    spoken: Any

    def __str__(self) -> str:  # what lands in the log line
        return f"{self.name}={self.spoken!r} refused ({self.reason})"


# ── WHERE A BOUND VALUE CAME FROM ───────────────────────────────────────────────────────────
#
# THE VOCABULARY LIVES HERE, not at the reader, because this module is the one door every
# binding passes through. It was declared in `gateway.py` and consumed there; the writer and
# the promotion rule then needed it too, and a second copy is how a rename makes a feature stop
# silently. Gateway imports these.
#
# The distinction is NOT cosmetic and the split must survive refactoring: `picked` and `spoken`
# both mean "a person answered", and only `picked` was validated against a menu THIS SYSTEM
# enumerated. Flattening them loses the one fact the promotion rule turns on.
SLOT_SOURCE_PICKED = "picked"        # chosen from a menu this system offered
SLOT_SOURCE_SPOKEN = "spoken"        # typed in answer to a RESPEAK ask (no menu existed)
SLOT_SOURCE_SUPPLIED = "supplied"    # sent by an API caller with the request
SLOT_SOURCE_FILLED = "filled"        # extracted from the question by the slot filler

SLOT_SOURCES = (
    SLOT_SOURCE_PICKED, SLOT_SOURCE_SPOKEN, SLOT_SOURCE_SUPPLIED, SLOT_SOURCE_FILLED,
)


class Acceptance(NamedTuple):
    params: dict[str, Any]
    refusals: list[Refusal]
    #: `{slot: {"value": v, "source": s}}` for ACCEPTED params only — the provenance record the
    #: chain reads back. A refused slot is not a binding and must not appear here.
    bound_slot_sources: dict[str, Any] = {}
    #: Accepted params whose caller named no source. NOT silently defaulted: an invented source
    #: would launder a caller string past the menu check, which is the one thing the split
    #: protects. Surfaced so a caller that forgets is visible rather than quietly unprovenanced.
    unsourced: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.refusals


# Reasons — named constants because they are asserted on in tests and read in logs, and a
# typo in a string literal is a test that passes for the wrong reason.
NO_DECLARATIONS = "no-declarations"
UNDECLARED = "undeclared"
ROUTE_SUPPLIED = "route-supplied"
NOT_A_PERMITTED_VALUE = "not-a-permitted-value"
WRONG_SHAPE = "wrong-shape"


def accept_slots(
    spoken: Mapping[str, Any] | None,
    declared: Sequence[Mapping[str, Any]] | str | None,
    sources: Mapping[str, str] | None = None,
) -> Acceptance:
    """Filter `spoken` down to what `declared` permits.

    `declared` is the verb's `mesh_slots` list: records of
    ``{name, kind, type, required, values?, default?}``.

    Every rejection is a `Refusal`, never an exception, and the accepted dict is safe to
    splat into the verb.
    """
    spoken = dict(spoken or {})
    # Normalised HERE rather than at each call site, because a caller that forgets gets the
    # character-shredding described in `decode_declarations` — silently, and looking like
    # "this verb declared 47 slots, all of them one character long".
    declared = decode_declarations(declared)

    if not spoken:
        return Acceptance({}, [], {}, ())

    if not declared:
        # Fail closed — see the module docstring. This is the branch that keeps the carry
        # dark until declarations are actually projected.
        return Acceptance(
            {}, [Refusal(n, NO_DECLARATIONS, v) for n, v in sorted(spoken.items())], {}, (),
        )

    by_name = {d["name"]: d for d in declared}  # decode_declarations already filtered

    params: dict[str, Any] = {}
    refusals: list[Refusal] = []

    for name, value in sorted(spoken.items()):
        decl = by_name.get(name)
        if decl is None:
            # An extraction inventing a parameter. Dropped LOUDLY: passing it through would
            # reach `func(state, **params)` and surface as a 400 naming the engine, which
            # blames the wrong layer for the router's mistake.
            refusals.append(Refusal(name, UNDECLARED, value))
            continue

        if decl.get("kind") in ROUTE_SUPPLIED_KINDS:
            # The boundary this module exists for.
            refusals.append(Refusal(name, ROUTE_SUPPLIED, value))
            continue

        declared_type = str(decl.get("type") or "")
        if declared_type.startswith(("list[", "set[", "tuple[")) and isinstance(value, str):
            # A COLLECTION SLOT GIVEN A BARE STRING. Refused rather than coerced: wrapping
            # it as [value] is the router guessing at what was meant, and the guess is
            # wrong the moment a speaker names two periods.
            #
            # Refusing here is what makes the failure legible. Passed through, the measure
            # iterates the string and the engine answers
            #   422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4
            # which names characters, blames the engine, and tells nobody that the
            # extraction produced the wrong shape.
            refusals.append(Refusal(name, WRONG_SHAPE, value))
            continue

        # ── AN INTEGER SLOT GIVEN A STRING, THREE-VALUED ─────────────────────────
        #
        # MEASURED 2026-09-08, walking the first INTEGER slot this system has ever been
        # asked. Every prior walk used string slots — `capability_id: "C8"`,
        # `program_id: "NP-MERIDIAN"` — so this had never fired.
        #
        # A spoken answer arrives as text. `lot` is declared `"type": "integer"`, the value
        # reached engine-cost as "1", and its model is a dict keyed by int, so `lots["1"]`
        # raised KeyError and the engine refused with:
        #
        #     lot 1 is not in the model; known lots are [1, 2, 3, 4, 5, 6, 7, 8, 9]
        #
        # A refusal that lists the value it just rejected. The message is accurate from
        # inside the code — the types are simply invisible in it — and to a reader it is
        # nonsense, which sends them looking for a data problem that does not exist.
        #
        # WHY COERCING HERE IS NOT THE THING THIS MODULE REFUSES TO DO. The collection case
        # above declines to wrap a bare string because `[value]` GUESSES AT STRUCTURE and the
        # guess is wrong the moment a speaker names two periods. `int("1")` guesses at
        # nothing: it is total where it is defined and fails loudly where it is not. So this
        # takes the same three-valued shape as the period resolution below —
        #
        #   an integral string   -> parsed, because "1" and 1 are the same answer
        #   already an int       -> passed through untouched
        #   anything else        -> REFUSED, with the value named
        #
        # — and never a fourth outcome where a non-numeric string reaches a measure and the
        # engine blames its own model for it.
        if declared_type in ("integer", "int") and isinstance(value, str):
            _candidate = value.strip()
            _negative = _candidate.startswith("-")
            if (_candidate[1:] if _negative else _candidate).isdigit():
                params[name] = int(_candidate)
                continue
            # `.isdigit()` rather than a try/except around int(): it refuses "1.0", "1_000"
            # and unicode oddities that int() would silently accept or mangle. A lot number
            # is an identifier, not an arithmetic expression.
            refusals.append(Refusal(name, WRONG_SHAPE, value))
            continue

        # ── PERIOD RESOLUTION, THREE-VALUED ──────────────────────────────────────
        # A `period: "date"` slot is compared LEXICALLY against ISO dates by its measure, so
        # a fiscal label there is not a weak filter — it is a COMPLETE NO-OP. Measured:
        # `as_of="FY26-Q4"` returns the unfiltered set byte-identical to passing nothing,
        # because ('9999-12-31' <= 'FY26-Q4') is True.
        #
        # The failure being removed is ACCEPTED AND IGNORED. It must not be replaced by
        # ACCEPTED AND COERCED, so there are three outcomes and no fourth:
        #
        #   a known fiscal label  -> resolved to that period's END date
        #   an ISO date           -> passed through, it is already what the measure wants
        #   anything else         -> REFUSED, with the vocabulary named
        #
        # Resolution is DECLARATION-DRIVEN: the boundaries ride on `period_end`, derived from
        # FISCAL_PERIODS at declaration time, so this module holds no copy of the fiscal
        # calendar and cannot drift from it.
        if decl.get("period") == "date" and isinstance(value, str):
            boundaries = decl.get("period_end") or {}
            if value in boundaries:
                params[name] = boundaries[value]
                continue
            if not _ISO_DATE.fullmatch(value):
                refusals.append(Refusal(name, NOT_A_PERMITTED_VALUE, value))
                continue
            params[name] = value
            continue

        values = decl.get("values")
        if values:
            # A closed enum, derived from the signature's `Literal`, so this is the verb's
            # own vocabulary and not a guess. Refusing beats passing it on to be rejected as
            # a TypeError deep in the measure.
            #
            # Checked ELEMENTWISE for a collection slot: `list[Literal[...]]` is a
            # multi-select over the same closed vocabulary, and testing the list itself for
            # membership would refuse every legitimate multi-select.
            offered = list(value) if isinstance(value, (list, tuple, set)) else [value]
            bad = [v for v in offered if v not in values]
            if bad:
                refusals.append(Refusal(name, NOT_A_PERMITTED_VALUE, value))
                continue

        params[name] = value

    # ── THE PROVENANCE RECORD, WRITTEN ONCE, HERE ───────────────────────────────────────────
    #
    # `bound_slot_sources` was READ by `_accumulated_slots` and written NOWHERE — measured
    # 2026-09-14 against the database: 356 artifacts carried `resolved_intent`, ZERO carried
    # this field. So the chain-slot carry, the arity gate's bound-slot read and the instance
    # promotion were all inert in production while every seal over them was green, because the
    # seals supplied the field the world did not (R-057).
    #
    # IT IS BUILT AT THIS ONE SITE ON PURPOSE. Every path — the fast dispatch and the
    # supervisor — already passes through `accept_slots` to project onto the declaration, so
    # writing it here means no path can acquire a binding without recording where it came from.
    # Building it per call site is precisely how "the pre-resolved site" turned out to be two.
    #
    # ACCEPTED PARAMS ONLY. A refused slot is not a binding; recording one would put a value
    # the verb rejected into the set a later hop treats as already answered.
    _src = dict(sources or {})
    _bound: dict[str, Any] = {}
    _unsourced: list[str] = []
    for _name, _value in params.items():
        _s = str(_src.get(_name) or "")
        if not _s:
            # NOT DEFAULTED. An invented source would launder an unvalidated value past the
            # menu check — the same refusal `_accumulated_slots` makes on the read side.
            _unsourced.append(_name)
            continue
        _bound[_name] = {"value": _value, "source": _s}
    return Acceptance(params, refusals, _bound, tuple(_unsourced))
