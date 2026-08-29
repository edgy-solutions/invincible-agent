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

import re
from dataclasses import dataclass
from typing import Optional


#: THE `instance_match` VOCABULARY, enumerated here because consumers match on it.
#:
#:     exact | fuzzy | mixed | not_specific | empty | no_providers | timeout
#:
#: ONE VALUE IS PRODUCED OUTSIDE THIS MODULE. `/fill_slots` adds `wrong_class` when a name
#: resolves cleanly and the winner's class disagrees with the slot's declared `referent` —
#: "the ERP Modernization project" resolves to an Initiative against a slot declaring
#: Project. It is an ADDITION rather than a reuse because none of the values above mean it:
#: `mixed` is candidates of DIFFERENT classes, `not_specific` is a vague identifier, and that
#: case was one candidate, specific, real, and of the wrong class. Reusing either would make
#: this vocabulary lie to keep its size.
#:
#: Recorded HERE so an exhaustive match written against this list does not silently fall
#: through on a value it has never seen. This module does not produce `wrong_class` and does
#: not need to handle it; a consumer of `/fill_slots` does.


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


# ---------------------------------------------------------------------------
# SEGMENT SPECIFICITY — the discriminator the phone book never had (2026-08-17)
# ---------------------------------------------------------------------------
# THE CONTRACT THIS REPAIRS. `contracts.baml` tells the extractor to be
# RECALL-BIASED — "a miss costs more than a spurious extraction, THE ROUTER CAN
# VERIFY WITH THE PHONE BOOK." That is sound engineering and the phone book never
# held up its end: a fuzzy match let `cage`, lifted from the words "cage values",
# resolve to `publog/p_cage`. Completing the model's guess is not verifying it.
#
# Measured 2026-08-15/17: the same nonexistent asset (`p_caeg`) alternated between
# honest abstention and a confident answer about a REAL, DIFFERENT dataset as one
# candidate's similarity score moved by 0.006 with no redeploy.
#
# SO THIS GATE IS STRUCTURAL, NOT A THRESHOLD, AND THAT IS THE WHOLE POINT.
# Raising a score cutoff would only move a row from 0.006-away-from-wrong to
# 0.012-away-from-wrong — a wider margin on the same knife edge. A substring is a
# substring at every score, so substrate drift cannot flip this decision.
_SEGMENT_SPLIT = re.compile(r"[^A-Za-z0-9_-]+")


def _segments(text: str) -> list[str]:
    """Lowercased name segments of an identifier or a catalog id.

    Splits on `.`/`/`/`,`/`:`/whitespace and KEEPS `_` and `-`, because those are
    inside real asset names (`p_cage`, `iagent-minio`) rather than between them.
    """
    return [seg for seg in _SEGMENT_SPLIT.split((text or "").lower()) if seg]


def identifier_name_and_qualifiers(identifier: str) -> tuple[str, list[str]]:
    """Split an extracted identifier into its NAME and its QUALIFIERS.

    `publog.p_cage`, `publog p_cage` and `publog's p_cage` all mean the same asset
    and all failed before: the matcher could not see past the qualifier. The name
    is the LAST segment; everything before it corroborates.
    """
    segs = _segments(identifier)
    if not segs:
        return "", []
    return segs[-1], segs[:-1]


def passes_segment_specificity(identifier: str, candidate_text: str) -> bool:
    """True iff `identifier` names a WHOLE segment of `candidate_text`.

    This is the missing half of the extractor's contract. `cage` is a substring of
    the segment `p_cage`, never a segment itself, so it is refused however high the
    similarity score climbs — which is exactly what makes a recall-biased extractor
    safe: the phone book can finally say "that token does not identify an asset."

    Qualifiers are corroboration, not obstruction: `publog.p_cage` passes on its
    name segment, and its `publog` qualifier appearing in the candidate is a bonus,
    never a requirement (a catalog id need not spell the qualifier the same way).
    """
    name, _quals = identifier_name_and_qualifiers(identifier)
    if not name:
        return False
    asset = candidate_asset_name(candidate_text)
    if asset:
        return name == asset
    # No derivable terminal name (a URN shape this rule was not written for —
    # procedure codes, DMCs, tail numbers). Fall back to segment membership and
    # SAY SO, rather than silently applying a rule to a shape it does not fit.
    return name in set(_segments(candidate_text))


# Env qualifiers trail a catalog id and are not part of the asset's name. A short,
# explicit list beats a clever heuristic: anything not listed stays part of the name,
# so an unknown suffix makes the gate STRICTER (reject), never looser.
_ENV_SUFFIXES = frozenset({"prod", "dev", "test", "stage", "staging", "qa", "uat"})


def candidate_asset_name(candidate_text: str) -> str:
    """The candidate's OWN name — its terminal segment, ignoring env suffixes.

    Why terminal rather than any-segment: `publog` is a real segment of
    `publog-lake/publog/p_cage`, so plain membership let a SCHEMA name resolve to a
    TABLE inside it (measured: `bare-join-01`, where the extractor emitted `publog`
    for a question about `p_cage`). A container is not the thing it contains.
    """
    segs = _segments(candidate_text)
    while segs and segs[-1] in _ENV_SUFFIXES:
        segs.pop()
    return segs[-1] if segs else ""


def decide(
    candidates: list[InstanceCandidate],
    *,
    exact_threshold: float = DEFAULT_EXACT_THRESHOLD,
    min_score: float = DEFAULT_MIN_SCORE,
    identifier: str = "",
) -> InstanceResolutionDecision:
    """Apply the decision table to a candidate list."""
    above_floor = [c for c in candidates if c.score >= min_score]

    # SPECIFICITY GATE. A candidate only survives if the extracted identifier names
    # a whole segment of it. Applied BEFORE ranking on purpose: this is not a
    # tie-break between plausible candidates, it is a statement that a token which
    # merely appears inside a name does not identify anything. Skipped when no
    # identifier reached us, so existing callers that do not pass one are unchanged.
    # ORDER MATTERS: the empty check runs FIRST. Placing the gate above it made an
    # EMPTY PROVIDER RESULT report `not_specific` — a rejection's name on a result where
    # nothing was rejected (n=0, rejected_n=0), which is precisely what hid the fan-out
    # starvation bug: the vocabulary said "the token is not a name" when the truth was
    # "the phone book was never asked a question it could answer."
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

    if identifier:
        specific = [c for c in above_floor
                    if passes_segment_specificity(identifier, c.instance_id)
                    or passes_segment_specificity(identifier, c.label)]
        if not specific:
            return InstanceResolutionDecision(
                subject_uri=None,
                confidence=0.0,
                provenance={
                    "instance_resolved": False,
                    # A DISTINCT reason, not folded into `empty`: the phone book DID
                    # know things, and refused them because the token is not a name.
                    # Folding it into "empty" would hide the gate's every action.
                    "instance_match": "not_specific",
                    "instance_n": len(candidates),
                    "instance_rejected_n": len(above_floor),
                    "instance_identifier": identifier,
                },
            )
        above_floor = specific

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


# ---------------------------------------------------------------------------
# Structural abstention gate (ADR-0026 abstention-gate arc, 2026-07-03)
# ---------------------------------------------------------------------------
# THE PROBLEM this closes: when the LLM extracts an `instance_identifier`
# but the phone-book fan-out finds nothing, the resolver used to fall back
# to the LLM's CLASS guess unconditionally. So whether a query naming a
# non-existent specific individual (e.g. "foo.bar.zzz_nope") ABSTAINS or
# gets a confident-but-wrong class answer rode entirely on the LLM's
# sampling — the no-margin, LLM-mediated gate.
#
# THE RULING (see [[project_abstention_gate_llm_mediated]]): the
# discriminator between "you named a real-looking individual that doesn't
# exist" (abstain, actionably) and "you used a generic term the extractor
# over-eagerly flagged as an identifier" (class-fallback is correct) is
# STRUCTURAL — never another LLM judgment (that would rebuild the no-margin
# gate one layer up). It is policy over two DETERMINISTIC signals:
#   1. Identifier FORM  — does the token look like a specific named
#      individual (namespace-qualified / dotted / coded), or a plain
#      generic word?  (`is_instance_shaped`)
#   2. Recorded RESOLUTION FACT — did the providers get asked and cleanly
#      return nothing (`instance_match == "empty"`), as opposed to an
#      infra non-answer (timeout / error / no_providers)?
#
# Both signals are facts already on the table (the form of the extracted
# identifier; the provenance the decision table above recorded). The gate
# is a pure function over them — no cluster, no model, exhaustively
# testable. This is ALSO the shared form-discrimination primitive Hole 2
# ([[resolve-instance-provider-gap]], the identifier-form-mismatch /
# token-subset matching) will consume — built once here, on purpose, so
# the form check is not written twice.

# `instance_match` values that mean "providers answered cleanly and the
# registry genuinely does not know this token." Distinct from the infra
# non-answers (timeout / error / no_providers) where we did NOT get a
# trustworthy "no" — those must NOT be reported to the user as not-found.
_GENUINE_NOT_FOUND_MATCHES = frozenset({"empty"})

# Structural markers of a specific named individual (vs a generic class
# term). Namespace colons (urn:li:dataset:…) and dotted qualification
# (foo.bar.baz) are the unambiguous ones; a coded single token bearing
# digits or an ALLCAPS/hyphenated segment (NSN-123, DMC-XYZ_A) is the
# next tier. A plain natural-language word or phrase ("mechanics",
# "customer records") is deliberately NOT instance-shaped.
_DOTTED_QUALIFIED = re.compile(r"\w\.\w")
_CODED_SEGMENT = re.compile(r"[A-Z0-9]{2,}[-_/]")


def is_instance_shaped(identifier: str) -> bool:
    """Deterministic FORM discriminator (signal #1 of the abstention gate).

    True when ``identifier`` carries the STRUCTURE of a specific named
    individual — a namespace-qualified URN, a dotted qualified name, or a
    coded token (embedded digits / ALLCAPS-hyphen segment). False for a
    plain natural-language word or phrase, which is what a generic class
    term looks like when an over-eager extractor mislabels it as an
    identifier.

    Conservative by design: the safe failure direction is a FALSE
    (generic-looking → class-fallback → current LLM-mediated behavior).
    A false-positive here would wrongly abstain on a real class query, so
    we only return True on unambiguous structure. Multi-word phrases are
    treated as generic (they degrade to class-fallback), which is the
    intended conservative posture — this gate exists to catch the
    clearly-coded ``foo.bar.zzz_nope`` shape, not to abstain broadly.
    """
    s = (identifier or "").strip()
    if not s:
        return False
    # A namespace colon is unambiguous and can't contain whitespace.
    if ":" in s and " " not in s:
        return True
    # Remaining structural signals only apply to a single (whitespace-
    # free) token; a phrase with spaces reads as natural language.
    if " " in s:
        return False
    if _DOTTED_QUALIFIED.search(s):
        return True
    if any(ch.isdigit() for ch in s):
        return True
    if _CODED_SEGMENT.search(s):
        return True
    return False


def decide_instance_abstention(
    identifier: Optional[str],
    instance_subject: Optional[str],
    instance_match: str,
) -> Optional[str]:
    """The structural abstention gate — policy over the two recorded facts.

    Returns ``"instance_not_found"`` when the query named a specific
    individual (form: ``is_instance_shaped``) that the phone book was
    asked about and genuinely does not know (fact:
    ``instance_match == "empty"``). In that case the caller must ABSTAIN
    with an actionable message rather than fall back to the LLM's class
    guess.

    Returns ``None`` — keep the LLM class guess (current behavior) — in
    every other case:
      * the instance actually resolved (not an abstention at all),
      * an INFRA non-answer (timeout / error / no_providers): we did not
        get a trustworthy "no", so we must not tell the user "no provider
        knows it",
      * the identifier is NOT instance-shaped: a generic term the
        extractor over-eagerly flagged — class-fallback is the correct
        answer, and abstaining would wrongly refuse a valid class query.

    NO LLM. NO network. A pure decision over (form, recorded-fact).
    """
    if instance_subject is not None:
        return None  # resolved upstream — nothing to abstain about
    if instance_match not in _GENUINE_NOT_FOUND_MATCHES:
        return None  # infra non-answer, not a clean not-found
    if not is_instance_shaped(identifier or ""):
        return None  # generic term mislabeled as identifier → class-fallback
    return "instance_not_found"


def instance_not_found_message(identifier: str) -> str:
    """The ACTIONABLE abstention text (honest-empty is only honest if it
    tells the user what to do). Names the exact token and the next step —
    a bare "UNKNOWN" would leave the user with nowhere to go."""
    return (
        f"No provider in the mesh recognizes '{identifier}'. It has the "
        f"form of a specific named item, but the instance registry "
        f"returned no match. Check that the identifier is exact, or ask "
        f"about its general category instead of the specific instance."
    )
