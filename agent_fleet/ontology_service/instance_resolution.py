"""Recipe v2 — instance-resolution decision table.

When ``/resolve``'s LLM extracts a ``instance_identifier`` from the query,
the router fans that token out to every engine registered as a
``mesh:resolveInstance`` provider (discovered through the predicate
graph, NOT by backend name). Each provider returns a (possibly empty)
list of candidate instances with their canonical idp:* class.

This module is the PURE decision function that consumes those
candidates and decides whether the phone-book answer overrides the
LLM's class-resolution guess. No HTTP, no Neo4j, no LLM, no globals —
everything is parameters in, decision out. That isolation is the
point: the design lives or dies on a small set of decision rules and
they need to be exhaustively testable without spinning up a cluster.

The rules (per Recipe v2 §2):

  exact match (score >= ``exact_threshold``)
      → class from that candidate OVERRIDES, confidence 1.0,
        provenance ``instance_match=exact``.

  fuzzy + ALL candidates same class
      → that class overrides, confidence high (top score),
        provenance ``instance_match=fuzzy``, ``instance_n=<count>``.

  fuzzy + MIXED classes
      → abstain (return ``None``). The LLM's guess stands.
        v2 will upgrade this to an ADR-0015 disambiguation
        question; v1 just defers to the existing resolver.

  empty (or all below ``min_score``)
      → abstain. Phone book genuinely doesn't know this token.

The provenance dict is what makes the trace ``"LLM guessed Column,
DataHub said Table, Table won"`` come for free downstream. Always
populated, even on abstain (so the log says WHY we abstained).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class InstanceCandidate:
    """One candidate returned by a ``mesh:resolveInstance`` provider."""

    instance_id: str
    class_uri: str
    label: str
    score: float
    provider: str = ""


@dataclass(frozen=True)
class InstanceResolutionDecision:
    """The decision table's output.

    ``subject_uri`` is None when the router should NOT override the LLM
    guess. ``provenance`` is always populated for downstream
    observability.
    """

    subject_uri: Optional[str]
    confidence: float
    provenance: dict


# Defaults — overridable per call. The provider already abstained below
# its own relevance floor, so ``min_score`` here is a belt-and-
# suspenders check.
DEFAULT_EXACT_THRESHOLD = 0.95
DEFAULT_MIN_SCORE = 0.7


def decide(
    candidates: list[InstanceCandidate],
    *,
    exact_threshold: float = DEFAULT_EXACT_THRESHOLD,
    min_score: float = DEFAULT_MIN_SCORE,
) -> InstanceResolutionDecision:
    """Apply the decision table to a candidate list."""
    above_floor = [c for c in candidates if c.score >= min_score]

    if not above_floor:
        return InstanceResolutionDecision(
            subject_uri=None,
            confidence=0.0,
            provenance={
                "instance_resolved": False,
                "instance_match": "empty",
                "instance_n": len(candidates),
            },
        )

    above_floor = sorted(above_floor, key=lambda c: c.score, reverse=True)
    top = above_floor[0]

    if top.score >= exact_threshold:
        return InstanceResolutionDecision(
            subject_uri=top.class_uri,
            confidence=1.0,
            provenance={
                "instance_resolved": True,
                "instance_match": "exact",
                "instance_provider": top.provider,
                "instance_n": 1,
                "instance_id": top.instance_id,
                "instance_label": top.label,
                "instance_score": top.score,
            },
        )

    distinct_classes = {c.class_uri for c in above_floor}
    if len(distinct_classes) == 1:
        return InstanceResolutionDecision(
            subject_uri=top.class_uri,
            confidence=min(0.9, top.score + 0.05),
            provenance={
                "instance_resolved": True,
                "instance_match": "fuzzy",
                "instance_provider": top.provider,
                "instance_n": len(above_floor),
                "instance_id": top.instance_id,
                "instance_label": top.label,
                "instance_score": top.score,
            },
        )

    return InstanceResolutionDecision(
        subject_uri=None,
        confidence=0.0,
        provenance={
            "instance_resolved": False,
            "instance_match": "mixed",
            "instance_n": len(above_floor),
            "instance_distinct_classes": sorted(distinct_classes),
            "instance_top_candidates": [
                {
                    "instance_id": c.instance_id,
                    "class_uri": c.class_uri,
                    "label": c.label,
                    "score": c.score,
                }
                for c in above_floor[:3]
            ],
        },
    )
