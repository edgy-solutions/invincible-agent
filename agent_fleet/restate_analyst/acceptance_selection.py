"""The `review_request` CONSUMER's decision half — which definition opens the acceptance.

ADR-0039's 2026-09-12 amendment: **the CHOICE that opens a safety acceptance is a decision-table
row, not a branch inside a definition.** `engine-safety` emits a `level` and stops — it does not
know the word "concurrence". This module reads `safety_acceptance_selection` and answers with a
definition id, and it is the ONLY place that mapping exists.

R-076 IS WHY THIS FILE EXISTS. `measures.py:411` has emitted `review_request` unconditionally
since 2026-09-12, with a comment naming the gateway as its reader, and **that reader was never
written** — a producer that did the right thing, documented it, and shipped into silence. The
comment made it expensive: it reads as a wired contract, so nobody looked.

## THE TRAP THIS FILE REFUSES, AND IT IS THE REASON THE CONSUMER IS NOT ONE LINE

`measures.py` says the draft "carries a request the gateway can hand to `register_task`
VERBATIM", and the keys ARE that function's parameters. **Handing it over verbatim would be
wrong for exactly the two levels MIL-STD-882E treats specially.** `register_task` materialises an
acceptance queue row immediately; for Serious and High the standard (§4.3.7) requires the user
representative's formal concurrence FIRST, and the amendment enforces that "before" through the
ROUTE — the acceptance definition is not reachable for those levels except through the
concurrence chain. A direct `register_task` bypasses the route, opens the acceptance, and looks
completely correct while doing it.

**So the request supplies the ARGUMENTS and the table supplies the ORDERING.** The keys still
have to match `register_task`'s signature (the `human_await` step ends up there) — that is what
`test_the_review_request_can_actually_open.py` already seals — but the CALL belongs to the
definition's step, never to the reader of the artifact.

## WHY SELECTION IS NOT DONE BY THE CALLER

`review_starter` computes its trust rung server-side and never accepts it from the request,
"because handing the route over the wire would let anyone entitled to `mesh:startReview` select
their own supervision level". The same argument applies one notch harder here: a caller that
could name the definition could name `safety_acceptance_direct` for a High hazard and skip
concurrence. So the caller hands over the REQUEST, and the selection happens behind the workflow
boundary, where the table is the only authority.

## A FALL-THROUGH IS A REFUSAL, NEVER A DEFAULT

`policy/decisions/README.md`: *"a fall-through in a selection table means NO DEFINITION WAS
CHOSEN at the moment a human risk decision was due."* Every failure below raises. There is no
default definition, no "safest" fallback and no empty return — a level with no row must stop the
acceptance loudly, because the alternative is a hazard that was drafted, routed nowhere, and
recorded as handled.
"""
from __future__ import annotations

from typing import Any, Dict

# PACKAGE FIRST, then the flattened container layout: two import paths make two module
# objects, and an exception class caught under one name and raised under the other is not
# caught at all.
try:
    from agent_fleet.restate_analyst import decision_table as _dt
except ImportError:  # pragma: no cover — the image flattens this directory into /app
    import decision_table as _dt  # type: ignore[no-redef]

#: The table this consumer reads. Named once; every error message quotes it so a reader who has
#: never seen this file knows which YAML to open.
SELECTION_DECISION = "safety_acceptance_selection"


class AcceptanceSelectionError(_dt.DecisionError):
    """A selection could not be made. ALWAYS terminal — see the module docstring.

    A SUBCLASS of the generic `DecisionError`, so a caller of the generic runner catches it and
    every existing `except AcceptanceSelectionError` still does."""


# Where the tables live, and how they compose, is the generic module's now. Re-exported so the
# Dockerfile comment and every reader that names `acceptance_selection.decision_dirs` still
# resolve to the one implementation.
candidate_decision_dirs = _dt.candidate_decision_dirs
decision_dirs = _dt.decision_dirs


def load_table(decision: str = SELECTION_DECISION) -> Dict[str, Any]:
    """The composed table, by `decision` key. See `decision_table.load_table`."""
    try:
        return _dt.load_table(decision)
    except AcceptanceSelectionError:
        raise
    except _dt.DecisionError as exc:
        raise AcceptanceSelectionError(str(exc)) from exc


def select(level: str, table: Dict[str, Any] | None = None) -> str:
    """The definition id that opens an acceptance at `level`. Raises rather than defaulting.

    THE EVALUATION IS `decision_table.decide`, the one the workflow runner uses; this adds only
    what is particular to OPENING an acceptance:

    * the table must read `level` and nothing else — engine-safety emits a level and stops, so a
      table replaced by an overlay that reads another attribute cannot be evaluated here;
    * the row must name a DEFINITION. A terminal ends a process; it cannot open an acceptance.

    THE MATCH IS EXACT AND CASE-SENSITIVE. `domain.level` is `[Low, Medium, Serious, High]` and
    the engine emits exactly those; a tailored `MEDIUM` row would silently never fire.
    """
    table = load_table() if table is None else table

    matches = list(table.get("matches") or [])
    if matches != ["level"]:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} declares matches={matches!r}; this consumer supplies only "
            "'level'. A table that reads an attribute the engine does not emit cannot be "
            "evaluated here — extend the engine's measure, or the table, deliberately."
        )
    try:
        decision = _dt.decide(table, {"level": level})
    except _dt.DecisionError as exc:
        raise AcceptanceSelectionError(f"engine-safety emitted level {level!r}: {exc}") from exc
    if decision.terminal:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} routes level {level!r} to the TERMINAL {decision.then!r}, not "
            "to a definition. A terminal ends a process; it cannot open an acceptance."
        )
    return decision.then


def selectable_definitions(table: Dict[str, Any] | None = None) -> tuple[str, ...]:
    """Every definition `SafetyAcceptance` could be asked to run, DERIVED from the table.

    THE BOOT INVARIANT'S INPUT, AND IT MUST NOT BE A HAND-WRITTEN LIST. `_EXPECTED_DEFINITIONS`
    refuses to start the engine when a definition it may be asked to run is not loadable — a
    guard whose whole value is covering the reachable set. Reading the table's own `then` values
    (`decision_table.targets`) is the enumerate-before-asserting rule applied to the only register
    that knows. Terminals are excluded: a terminal is a state, not a process.

    IT LIVES HERE RATHER THAN IN `main.py` SO IT CAN BE SEALED. `agent_fleet.restate_analyst.main`
    is not importable in the repo layout (line 633 imports `orchestrator.auth` with no
    source-layout fallback, unlike every other import in that file), so a derivation defined
    there could only ever be checked by reading its source text.
    """
    return _dt.targets(load_table() if table is None else table)
