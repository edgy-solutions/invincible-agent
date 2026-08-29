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

from typing import Any, Mapping, NamedTuple, Sequence

#: Slot kinds whose values come from the ROUTE, never from a speaker. `handle` is state the
#: dispatcher resolves (a store reference, a session's op list); `ceremony` is an act's own
#: bookkeeping (an actor, a commit message) that the caller does not get to assert.
ROUTE_SUPPLIED_KINDS = frozenset({"handle", "ceremony"})

#: The full vocabulary, mirrored from `agent_fleet.planning_agent.slots.SLOT_KINDS`. Mirrored
#: rather than imported because this module must not depend on an engine's package — the
#: agreement is pinned by a test instead, which is the same trade the archetype registries make.
SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")


class Refusal(NamedTuple):
    """One slot that was NOT honoured, and why. `spoken` is kept so the log can show what was
    asked for — a refusal that cannot say what it refused is not auditable."""
    name: str
    reason: str
    spoken: Any

    def __str__(self) -> str:  # what lands in the log line
        return f"{self.name}={self.spoken!r} refused ({self.reason})"


class Acceptance(NamedTuple):
    params: dict[str, Any]
    refusals: list[Refusal]

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
    declared: Sequence[Mapping[str, Any]] | None,
) -> Acceptance:
    """Filter `spoken` down to what `declared` permits.

    `declared` is the verb's `mesh_slots` list: records of
    ``{name, kind, type, required, values?, default?}``.

    Every rejection is a `Refusal`, never an exception, and the accepted dict is safe to
    splat into the verb.
    """
    spoken = dict(spoken or {})
    declared = list(declared or [])

    if not spoken:
        return Acceptance({}, [])

    if not declared:
        # Fail closed — see the module docstring. This is the branch that keeps the carry
        # dark until declarations are actually projected.
        return Acceptance({}, [Refusal(n, NO_DECLARATIONS, v) for n, v in sorted(spoken.items())])

    by_name = {d["name"]: d for d in declared if isinstance(d, Mapping) and d.get("name")}

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

    return Acceptance(params, refusals)
