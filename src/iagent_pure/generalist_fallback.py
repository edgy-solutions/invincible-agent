"""When an answer came from the generalist, and whether it SAID so.

RULED 2026-09-26. ADR-0008's decision table is not in question and is not changed here: when
nothing in the registry matched, the generalist IS the honest answer — *"Query is outside registry
coverage; Engine A is the only honest answer."* The defect is one layer up. That answer arrives as
a confident card, indistinguishable from a specialist's, and ADR-0008 already forbids exactly
that: the generalist *"should say 'I am answering as a generalist because no registered tool
matched your request' rather than presenting as authoritative."*

THE WIRE ALREADY CARRIES THE DISCLOSURE. This module invents no field. `gateway.py`'s fallback
projection has emitted all three of these since the Part-0 work —

    "fallback": True
    "fallback_reason": <one of the closed enum below>
    "handled_by": {"provider": "engine_a_fallback", "engine_name": "Engine A (generalist fallback)"}

— so a new `answered_by` key would be a default invented locally becoming a contract, and a second
spelling of a fact already spelled. What was missing is that NOTHING READ THEM. That is the same
shape as `abstained` before [[engine_abstain]]: a field written by one side, read by none, and
therefore free to be wrong for as long as nobody looked.

── WHY `answered_by_generalist` AND `discloses` ARE TWO FUNCTIONS ───────────────────────────────

They answer different questions and the seal needs both. `answered_by_generalist` asks WHAT
HAPPENED — did this answer come from Engine A rather than a specialist. `discloses` asks whether
the answer SAYS SO COMPLETELY. An answer where the first is true and the second is false is the
defect: a fallback that reached the wire without its disclosure. Collapsing them into one predicate
would make that case unnameable, which is how it survived.

`answered_by_generalist` is deliberately the UNION of the two independent indicators, not their
intersection. A projection carrying `provider: engine_a_fallback` with `fallback` missing is still
a generalist answer, and reading it as a specialist because one of its two markers was dropped
would be the census believing a partial disclosure over what happened. The union means a DROPPED
marker still lands in `discloses`'s red rather than disappearing from the population — the guard's
subject cannot be removed by the same edit that breaks it.

── `is True`, NOT TRUTHINESS ────────────────────────────────────────────────────────────────────

The JSON crosses an SSE boundary and a string `"false"` is truthy. Same reasoning as
[[engine_abstain]]; the mutation sheet fires it.
"""

from __future__ import annotations

from typing import Any

#: The projection's own keys. Named here so a rename shows up as one edit in one file and the
#: census does not carry its own spelling of the producer's vocabulary.
FALLBACK_FIELD = "fallback"
REASON_FIELD = "fallback_reason"
PROVIDER = "engine_a_fallback"

#: The disposition a generalist answer scores in the walk census. NOT `drawn`: the generalist draws
#: a card, so `drawn` is true and useless — it is exactly what let three of the four docs rows
#: report as passing while answering from the maintenance ontology.
FALLBACK = "fallback"

#: Every `fallback_reason` the SUPERVISOR can set. Eight — not the six a first draft of this file
#: claimed — and the two it was missing are why the seal parses both source files rather than
#: trusting any comment, this one included.
#:
#: THE FIRST DRAFT WAS WRONG TWICE, IN OPPOSITE DIRECTIONS.
#:
#:   1. It listed six, taken from the supervisor's module docstring, and called them "the closed
#:      enum". That docstring enumerates the SUBJECT-RESOLUTION branches only. Two more literals
#:      are passed as kwargs to `_call_engine_a_fallback` from the PREDICATE side:
#:      `no_predicate_matched` (dynamic_supervisor.py:2536 — the ADR-0008 coverage gap itself) and
#:      `low_confidence` (:2563 — a matched predicate under threshold). A consumer built from the
#:      docstring would have reported the most common honest fallback in the fleet, *"no registered
#:      tool matched your request"*, as carrying an unrecognised reason.
#:
#:   2. It then attributed `no_predicate_matched` to the gateway's backward-compat heuristic and
#:      called it legacy. It is neither: the supervisor spells it at a live call site. That error
#:      came from reading `gateway.py`'s heuristic first and taking its vocabulary for the older one.
#:
#: Both were caught by the reach arm in `tests/test_a_fallback_that_did_not_say_so.py`, which
#: derives this population from the shipping code's own spellings. It found `low_confidence` in the
#: same run in which this module's docstring asserted that nothing emits it.
#:
#: `subject_unknown` / `instance_not_found` / `no_compatible_verbs` / `domain_scope_excluded` reach
#: the wire through the local `_fb_reason` at :903-904 and `fb_reason` at :1101-1107 — a THIRD
#: spelling, which is why the reach arm covers three and positive-controls each one separately.
#:
#: `_ENGINE_O_ABSTENTION_REASONS` (dynamic_supervisor.py:258) is what CLOSES the set: Engine O's own
#: abstention reason passes through verbatim at :903, gated by that frozenset. Without the gate
#: another service's vocabulary would be an open input to the fleet's, and this tuple would be a
#: guess rather than a population.
SUPERVISOR_REASONS = (
    "subject_unknown",
    "instance_not_found",
    "no_compatible_verbs",
    "domain_scope_excluded",
    "no_verb_classified",
    "infra_error",
    "no_predicate_matched",
    "low_confidence",
)

#: AND WHAT THE GATEWAY ITSELF CAN INVENT THAT NO SUPERVISOR PATH SETS.
#:
#: The census reads the gateway's projection, not the supervisor's metadata, and
#: `gateway.py:3494-3499` derives a reason from subject/verb/status when a materialization carries
#: no structured one (pre-Part-0 rows). Three of its four literals the supervisor also spells;
#: `no_subject` is the gateway's alone, and a consumer whose population came from the supervisor
#: would have reported it as unrecognised — a false red on an answer that disclosed perfectly, with
#: the reader sent to the wrong file to fix it.
#:
#: Kept SEPARATE rather than folded into the tuple above because the two sets retire differently:
#: this one empties out as pre-Part-0 materializations age out, and one flat tuple would leave
#: nothing to measure that against.
GATEWAY_ONLY_REASONS = ("no_subject",)

#: What the wire can actually carry. The union, because a consumer refusing half of it is refusing
#: answers that disclosed correctly.
REASONS = SUPERVISOR_REASONS + GATEWAY_ONLY_REASONS


def _provider_of(routing: Any) -> str:
    if not isinstance(routing, dict):
        return ""
    handled = routing.get("handled_by")
    if not isinstance(handled, dict):
        return ""
    return str(handled.get("provider") or "")


def answered_by_generalist(routing: Any) -> bool:
    """Did this answer come from Engine A rather than a specialist?

    The UNION of the two markers — see the module docstring. Either one alone is enough.
    """
    if not isinstance(routing, dict):
        return False
    return routing.get(FALLBACK_FIELD) is True or _provider_of(routing) == PROVIDER


def missing_disclosure(routing: Any) -> list:
    """What this fallback answer FAILED to say. Empty list = fully disclosed.

    RETURNS THE GAPS, NOT A BOOLEAN, because a seal that can only say "not disclosed" makes the
    reader open the payload to find out which half was missing — and the three markers fail for
    different reasons and get fixed in different places.

    Says nothing about an answer that is not a fallback: a specialist answer has no disclosure to
    make, and reporting one as undisclosed would be an over-strict arm whose symptom is a false red.
    """
    if not answered_by_generalist(routing):
        return []

    gaps = []
    if routing.get(FALLBACK_FIELD) is not True:
        gaps.append(f"{FALLBACK_FIELD} is not True (got {routing.get(FALLBACK_FIELD)!r})")
    if _provider_of(routing) != PROVIDER:
        gaps.append(f"handled_by.provider is not {PROVIDER!r} (got {_provider_of(routing)!r})")

    reason = routing.get(REASON_FIELD)
    if not isinstance(reason, str) or not reason.strip():
        gaps.append(f"{REASON_FIELD} is empty (got {reason!r})")
    elif reason not in REASONS:
        # REPORTED, NOT REFUSED. An unknown reason is still a disclosure — the user is told the
        # answer is a fallback and told why, which is what ADR-0008 asks for. What it is NOT is a
        # value anything downstream can key on, so it is named here rather than passed silently.
        gaps.append(f"{REASON_FIELD}={reason!r} is outside the wire's enum {list(REASONS)}")
    return gaps


def discloses(routing: Any) -> bool:
    """A generalist answer that says all three of the things it should. See `missing_disclosure`."""
    return answered_by_generalist(routing) and not missing_disclosure(routing)
