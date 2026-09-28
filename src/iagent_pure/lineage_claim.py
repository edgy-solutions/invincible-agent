"""WHETHER A TURN'S LINEAGE CLAIM IS HONOURED — the rule, at one address.

`answering_artifact_id` is what the CALLER asserts. `derived_from_artifact_id` is what the
server concluded. This module is the step between them, and it lives here rather than inline in
`gateway.py` for a reason measured twice this month: with a rule inlined in a handler, a seal can
only MIRROR it, and a mirror is not a seal. `cold_start_fallback_domains` in the ontology service
carries the same note over the same mistake — disabling its widening left the arm green, because
the arm was checking the test's copy of the rule.

WHY TWO GATES AND NOT ONE. A single predicate — "does this turn carry a pick or a typed answer?"
— used to decide BOTH whether the lineage arrow was drawn and whether the ask's already-resolved
(subject, verb) could skip routing. Those two rest on different evidence and cost different
things when wrong:

  the ARROW      a wrong one folds two cards together on a lineage nobody produced
  the ROUTE      a wrong one DISPATCHES A VERB AGAINST A SUBJECT nobody confirmed this turn

So the arrow is honoured for a prose turn — the person reading a drawn card and typing a sentence
about it, which descends from that card on any honest reading (HAZ-1003) — and the route is not.

AND THE PROSE ARM PAYS FOR ITSELF WITH A GRAPH READ. `bound_slots` and `spoken_answer` are shapes
only a client that was SHOWN this ask's menu can produce, so their presence is itself weak
evidence the named ask is real. Prose is evidence of nothing: every ordinary question carries
prose, so `named + prose` is satisfiable by any caller typing any sentence at any invented id.
The writer links with `MERGE (parent:AnswerArtifact {id: $parent_id})`, which CREATES the node
when the id is unknown — so an arm reachable on prose alone is how a phantom ancestor is conjured.
`ownership_ok` is therefore required on that arm, and it is a CALLABLE so the round trip happens
only for the turns that could widen anything: two free predicates are decided first.
"""
from __future__ import annotations

from collections.abc import Callable

#: No answer, no prose. An ordinary question does not descend from an ask.
REFUSED_NOTHING_CARRIED = (
    "the turn carries neither a pick, a typed answer, nor prose in `message` — an ordinary "
    "question does not descend from an ask"
)

#: Prose naming an id the graph will not vouch for. THE PHANTOM REFUSAL.
REFUSED_NOT_THE_CALLERS = (
    "the turn is prose naming an ask that does not exist or is not this caller's. Prose alone "
    "cannot vouch for an id, and a MERGE on an unvouched id fabricates the ancestor it appears "
    "to find"
)


def lineage_is_honoured(
    *,
    names_an_ask: bool,
    answers_something: bool,
    carries_prose: bool,
    ownership_ok: Callable[[], bool],
) -> tuple[bool, str]:
    """`(honoured, refusal_reason)`. The reason is `""` whenever `honoured` is true.

    It is also `""` when no ask was named at all: that is not a refusal, it is the ordinary
    shape of every question, and reporting it as a refusal would put a warning on the common
    path and teach the next reader to ignore the line.

    ⚠ THE ANSWERING ARM DOES NOT CALL `ownership_ok`, and that is a KNOWN, NAMED hole in this
    guard rather than an oversight. Closing it would refuse valid lineage in any window where
    the ask's own write has not landed by the time the answer turn arrives, and whether that
    race exists on this path is UNMEASURED. Measure it, then close it. `test_the_answering_arm_
    DOES_NOT_PAY_FOR_THE_GRAPH_READ` pins the current behaviour so that closing it is a
    deliberate act with a red to change, not a silent one.
    """
    if not names_an_ask:
        return False, ""
    if answers_something:
        return True, ""
    if not carries_prose:
        return False, REFUSED_NOTHING_CARRIED
    if not ownership_ok():
        return False, REFUSED_NOT_THE_CALLERS
    return True, ""


def pre_resolved_route_allowed(*, answers_something: bool) -> bool:
    """Whether the ask's stored (subject, verb) may skip routing on this turn.

    ONE ARGUMENT, AND IT IS NOT THE LINEAGE DECISION. It would be shorter to ask the caller for
    `honoured` and add a condition, and that is exactly the shape that re-joined the two gates
    in the first place: the route would then inherit every future widening of the arrow for
    free, silently, on the commit that widened it. A function whose signature cannot express
    the wider gate cannot accidentally be granted it.
    """
    return answers_something
