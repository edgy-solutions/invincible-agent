"""Resolve free-text names in a planning question — via the EXISTING ladder.

ADR-0031's ladder is the resolver for this codebase. This module does NOT
implement a second fuzzy matcher; it supplies candidates from the planning seed
and calls `instance_resolution.decide`, which is the same decision table Engine O
uses.

── WHY IMPORT RATHER THAN REIMPLEMENT ──────────────────────────────────────────

Two of the ladder's rules were expensive to get right and are invisible from a
one-line description of it:

  * QUALIFIED FORMS NORMALIZE FOR LOOKUP. `publog.p_cage` was sent to providers
    verbatim, matched nothing on the literal string, and starved the gate that
    would have decided correctly — the decision table was right and simply never
    given a question it could answer.
  * SPECIFICITY IS JUDGED ON WHAT THE USER SAID. A token that merely APPEARS
    INSIDE a name does not identify anything; the gate runs BEFORE ranking
    because it is not a tie-break, it is a statement about naming. And it runs
    AFTER the empty check, because an empty provider result reporting
    `not_specific` names a rejection where nothing was rejected — which is
    exactly what hid a fan-out starvation bug.

Inheriting those by DESCRIPTION would be the two-masters seed with extra steps:
the copy drifts, and the drift shows up as a resolution that is subtly wrong in
one engine and right in the other. Inheriting them by IMPORT means planning
cannot drift from them at all.

── WHAT THIS ADAPTER ADDS, AND IT IS ONLY PLUMBING ─────────────────────────────

The ladder resolves against DISCOVERED PROVIDERS over the network. Planning's
names live in Engine P's in-memory seed store, so there is no provider and no
hop to make. The composition works because `instance_resolution.py` already
separates the DECISION layer from the TRANSPORT layer — `_resolve_instance` does
provider fan-out, `decide()` does the ladder. Planning supplies its own
candidates and calls the same table.

That separation is the reason this is twenty lines instead of a fork, and it is
worth recording as a property of the ladder's interface rather than luck.

── THE THREE OUTCOMES, WHICH MUST NOT COLLAPSE ────────────────────────────────

  * RESOLVED   → one entity, confidently named.
  * AMBIGUOUS  → candidates exist and none dominates. The rail renders an
                 INTERPRETATION CARD listing them; the user picks. This is not a
                 failure — it is the system declining to guess on the user's
                 behalf.
  * UNRESOLVED → nothing plausible. REFUSAL, naming what was looked for.

Collapsing ambiguous into resolved is the confident-wrong answer Gate 2 fails the
whole gate for; collapsing it into unresolved throws away a list the user could
have picked from in one click.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

# The ladder lives with Engine O but its decision layer is transport-free. Import
# it rather than copying it; a second matcher is the thing ADR-0031 exists to
# prevent.
_ENGINE_O = Path(__file__).resolve().parents[1] / "ontology_service"
if str(_ENGINE_O) not in sys.path:
    sys.path.insert(0, str(_ENGINE_O))

try:  # flattened image layout puts modules side by side
    from instance_resolution import (  # type: ignore
        InstanceCandidate,
        decide,
        identifier_name_and_qualifiers,
    )
except ImportError:  # repo layout
    from agent_fleet.ontology_service.instance_resolution import (  # type: ignore
        InstanceCandidate,
        decide,
        identifier_name_and_qualifiers,
    )


@dataclass(frozen=True)
class PlanningResolution:
    """One resolution attempt against the planning seed."""

    status: str  # "resolved" | "ambiguous" | "unresolved"
    entity_id: Optional[str]
    candidates: list[dict]
    provenance: dict

    @property
    def needs_interpretation_card(self) -> bool:
        return self.status == "ambiguous"


def _score(identifier: str, label: str) -> float:
    """Cheap lexical score over seed labels.

    Deliberately simple: the LADDER decides, this only ranks. A clever scorer
    here would be the second matcher wearing a helper's name — the thresholds,
    the specificity gate and the abstention rules all live in `decide`.
    """
    name, _quals = identifier_name_and_qualifiers(identifier)
    a, b = name.strip().lower(), label.strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b.split() or b in a.split():
        return 0.85
    if a in b or b in a:
        return 0.6
    return 0.0


def resolve_planning_entity(
    identifier: str,
    seed_entities: Iterable[dict[str, Any]],
    *,
    class_uri: str = "",
) -> PlanningResolution:
    """Resolve a free-text name against seed entities using ADR-0031's ladder.

    `seed_entities` are ``{"id": ..., "label": ...}`` from Engine P's store. The
    caller scopes them by kind (sites, projects, capabilities...) because a slot
    already declares which kind it wants — resolving a site name against project
    labels would invent ambiguity the question never had.
    """
    candidates = [
        InstanceCandidate(
            instance_id=str(e.get("id") or ""),
            class_uri=class_uri,
            label=str(e.get("label") or ""),
            score=_score(identifier, str(e.get("label") or "")),
            provider="planning_seed",
        )
        for e in seed_entities
    ]
    candidates = [c for c in candidates if c.score > 0.0]

    decision = decide(candidates, identifier=identifier)

    as_dicts = [
        {"id": c.instance_id, "label": c.label, "score": c.score}
        for c in sorted(candidates, key=lambda c: c.score, reverse=True)
    ]

    # ── AN INTERFACE FINDING, NOT A BUG ────────────────────────────────────
    # `decision.subject_uri` is the CLASS uri, not the entity. ADR-0031's ladder
    # exists to tell Engine O's router WHICH CLASS to use, overriding the LLM's
    # guess; the resolved ENTITY rides in provenance as `instance_id`. Planning
    # asks a different question — "which entity" — so it reads the provenance
    # field, and `subject_uri` is legitimately empty here because planning passes
    # no class_uri and does not want one.
    #
    # Recorded rather than worked around silently: a caller who assumes
    # subject_uri is "the answer" gets an empty string that reads as "unresolved"
    # while the ladder is reporting a confident exact match. That is a
    # same-observation-opposite-meaning trap, and the next planning-shaped caller
    # of this ladder will hit it too.
    prov = dict(decision.provenance)
    if prov.get("instance_resolved") and prov.get("instance_id"):
        return PlanningResolution(
            status="resolved",
            entity_id=str(prov["instance_id"]),
            candidates=as_dicts,
            provenance=prov,
        )

    # ABSTAIN SPLITS INTO TWO OUTCOMES. The ladder returns None for "do not
    # override"; for a planning slot there is nothing to fall back TO, so the
    # distinction that matters downstream is whether the user has something to
    # pick from. Candidates surviving the score floor but not the ladder is
    # exactly the ambiguous case an interpretation card exists for.
    if as_dicts:
        return PlanningResolution(
            status="ambiguous",
            entity_id=None,
            candidates=as_dicts,
            provenance=prov,
        )

    return PlanningResolution(
        status="unresolved",
        entity_id=None,
        candidates=[],
        provenance=prov,
    )
