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

import os
from pathlib import Path
from typing import Any, Dict

#: The table this consumer reads. Named once; every error message quotes it so a reader who has
#: never seen this file knows which YAML to open.
SELECTION_DECISION = "safety_acceptance_selection"


class AcceptanceSelectionError(Exception):
    """A selection could not be made. ALWAYS terminal — see the module docstring."""


# ---------------------------------------------------------------------------
# Where the tables live
# ---------------------------------------------------------------------------

def candidate_decision_dirs(module_path: Path) -> list[Path]:
    """The ordered places a decisions directory can live, given this module's path.

    MIRRORS ``workflow_definition.candidate_definition_dirs`` deliberately, including its depth
    guard: the image FLATTENS this service directory into ``/app``, so in the container this
    module is ``/app/acceptance_selection.py`` and ``parents[2]`` would raise IndexError before
    any honest error could be raised.

    SEED FIRST, THEN THE SAMPLE OVERLAY. `policy/decisions/` is structural and ships no domain
    rows; `safety_acceptance_selection` lives in an overlay because **a domain name may not enter
    the platform seed** (ADR-0036). Both halves must be on disk or composition sees only one.
    """
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:  # repo layout only; guarded, see docstring
        out.append(here.parents[2] / "policy")
    out.append(here.parent / "policy")  # flattened container layout
    return out


def decision_dirs() -> tuple[Path, list[Path]]:
    """``(seed_dir, overlay_dirs)`` for the composer, lowest precedence first.

    ``DECISION_TABLE_DIR`` is an ``os.pathsep``-separated LIST with the same shape and the same
    later-wins rule as ``WORKFLOW_DEFINITIONS_DIR`` — one mechanism, not a fourth one.
    """
    env = os.environ.get("DECISION_TABLE_DIR")
    if env:
        parts = [Path(p.strip()) for p in env.split(os.pathsep) if p.strip()]
        if parts:
            return parts[0], parts[1:]
    for root in candidate_decision_dirs(Path(__file__)):
        seed = root / "decisions"
        if seed.is_dir():
            overlays = sorted(
                p for p in (root / "overlays").glob("*/decisions") if p.is_dir()
            )
            return seed, list(overlays)
    # NOTHING ON DISK. Return the first candidate anyway so the error names a concrete path
    # rather than a guess — the same choice `definition_dirs` makes and for the same reason.
    root = candidate_decision_dirs(Path(__file__))[0]
    return root / "decisions", []


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

def load_table(decision: str = SELECTION_DECISION) -> Dict[str, Any]:
    """The composed table, by `decision` key.

    COMPOSED BY THE SHARED COMPOSER, not by a fourth one. ADR-0039 refuses a new composer by
    name, and `policy/decisions/README.md` names `compose_rows` as the mechanism: an overlay row
    REPLACES a seed row wholesale, keyed on `decision`.

    AN ABSENT TABLE IS NOT AN EMPTY TABLE. A missing file must not read as "no rows matched" —
    that is the silent-degrade this whole layer exists to refuse — so it names every directory it
    looked in and what it did find.
    """
    try:
        from iagent_mesh.declarations import compose_rows
    except ImportError as exc:  # pragma: no cover — the SDK is a hard dependency of the runtime
        raise AcceptanceSelectionError(
            "iagent-mesh SDK is not importable, so the decision layer cannot compose "
            f"{decision!r}. This is a packaging failure, not an empty table: {exc}"
        ) from exc

    seed, overlays = decision_dirs()
    try:
        rows = compose_rows(seed, overlays, key_field="decision",
                            builder=lambda raw: raw, label="decision table")
    except Exception as exc:  # noqa: BLE001 — re-raised as terminal, with the paths named
        raise AcceptanceSelectionError(
            f"could not compose decision tables from seed {str(seed)!r} "
            f"overlays {[str(o) for o in overlays]}: {exc}"
        ) from exc

    for raw in rows:
        if raw.get("decision") == decision:
            return raw
    raise AcceptanceSelectionError(
        f"no decision table {decision!r} in seed {str(seed)!r} or overlays "
        f"{[str(o) for o in overlays]} (have: {sorted(str(r.get('decision')) for r in rows)}). "
        "Presence in the repo is not presence in the running system — check that "
        "policy/decisions/ and policy/overlays/ are both baked into this image."
    )


def select(level: str, table: Dict[str, Any] | None = None) -> str:
    """The definition id that opens an acceptance at `level`. Raises rather than defaulting.

    FOUR REFUSALS, AND EACH IS A DIFFERENT FACT:

    * the level is not one the table DECLARES it handles (`domain.level`) — an engine emitted a
      value nobody tailored a row for, which is a policy gap, not a bug;
    * no row matches a declared level — the table is not total, and the build seal that should
      have caught it did not run here;
    * more than one row matches — the outcome would depend on YAML list order, which is not a
      declared property of a list (R-035);
    * the table does not match on `level` at all — it was replaced by an overlay that reads
      something else, and selecting on a stale attribute would be worse than not selecting.

    THE MATCH IS EXACT AND CASE-SENSITIVE. `domain.level` is `[Low, Medium, Serious, High]` and
    the engine emits exactly those; normalising here would make the table's declared domain stop
    describing what is actually accepted, and a tailored `MEDIUM` row would silently never fire.
    """
    table = load_table() if table is None else table

    matches = list(table.get("matches") or [])
    if matches != ["level"]:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} declares matches={matches!r}; this consumer supplies only "
            "'level'. A table that reads an attribute the engine does not emit cannot be "
            "evaluated here — extend the engine's measure, or the table, deliberately."
        )

    declared = list((table.get("domain") or {}).get("level") or [])
    if not declared:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} declares no domain for 'level'. Without it the table is total "
            "over itself by construction and its totality seal asserts nothing (R-026)."
        )
    if level not in declared:
        raise AcceptanceSelectionError(
            f"engine-safety emitted level {level!r}, which {SELECTION_DECISION} does not declare "
            f"(domain: {declared}). No definition is selected and no acceptance is opened — a "
            "level with no row is a policy gap and must not take a default."
        )

    hits = [
        r for r in (table.get("rows") or [])
        if (r.get("when") or {}).get("level") == level
    ]
    if not hits:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} declares level {level!r} in its domain and has NO ROW for it. "
            "A fall-through here means no definition was chosen at the moment a human risk "
            "decision was due."
        )
    if len(hits) > 1:
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} has {len(hits)} rows matching level {level!r}: "
            f"{[r.get('then') for r in hits]}. Two matching rows make the outcome depend on row "
            "order, which a YAML list does not declare (R-035)."
        )

    then = hits[0].get("then")
    if not then or not isinstance(then, str):
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} row for level {level!r} has no 'then': {hits[0]!r}"
        )
    if then in (table.get("terminals") or []):
        raise AcceptanceSelectionError(
            f"{SELECTION_DECISION} routes level {level!r} to the TERMINAL {then!r}, not to a "
            "definition. A terminal ends a process; it cannot open an acceptance."
        )
    return then


def selectable_definitions(table: Dict[str, Any] | None = None) -> tuple[str, ...]:
    """Every definition `SafetyAcceptance` could be asked to run, DERIVED from the table.

    THE BOOT INVARIANT'S INPUT, AND IT MUST NOT BE A HAND-WRITTEN LIST. `_EXPECTED_DEFINITIONS`
    refuses to start the engine when a definition it may be asked to run is not loadable — a
    guard whose whole value is covering the reachable set. A list typed beside the table is a
    SAMPLE of that set, so a tailoring that pointed a level at a third definition would ship an
    unloadable route with the invariant still green. Reading the table's own `then` values is
    the enumerate-before-asserting rule applied to the only register that knows.

    TERMINALS ARE EXCLUDED, because a terminal is a state and not a process: asking the registry
    to load `timed_out` would fail the boot check for a row that is working exactly as declared.

    IT LIVES HERE RATHER THAN IN `main.py` SO IT CAN BE SEALED. `agent_fleet.restate_analyst.main`
    is not importable in the repo layout (line 633 imports `orchestrator.auth` with no
    source-layout fallback, unlike every other import in that file), so a derivation defined
    there could only ever be checked by reading its source text.
    """
    table = load_table() if table is None else table
    terminals = set(table.get("terminals") or [])
    return tuple(sorted({
        str(r.get("then")) for r in (table.get("rows") or [])
        if r.get("then") and str(r.get("then")) not in terminals
    }))
