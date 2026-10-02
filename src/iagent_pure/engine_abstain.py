"""AN ENGINE THAT ABSTAINS HAS NOT MATCHED, and until now nothing said so.

`agent_fleet/docs_agent/explain.py` has returned `{"abstained": True, "reason":
"no_page_explains_this_subject", "subject": <iri>, ...}` since the explain verb was written. Its
docstring is explicit that this is *a RESULT, and the corpus's normal state* — nobody writes a
page for a task nobody has done — and that it names the subject so the reader can act on it.

**MEASURED 2026-09-26: `abstained` had ZERO readers.** A repo-wide search for the field across
`src/` and `agent_fleet/` found exactly one site, the producer at `explain.py:114`. Both ends of
this were never wired: the engine decided honestly and the decision reached nobody. The
supervisor stamped `route_status: "matched"` — *"the specialist answered"* — and the turn drew an
ordinary `KNOWLEDGE_DOCUMENT` card with no sections.

What that cost, measured on the live fleet across three fires (2026-09-26, repo `e207baec`):
census row `docs-how-do-i-roll-a-service-abstains` came back `drawn`. That row exists precisely
because `rolling-a-service` declares `explains: none` — its own frontmatter says the emptiness IS
the measurement — so no question can ever return it through `mesh:explain`. The walk census says
in words that `drawn` *"would be the defect here"*. A walker asking *"how do I roll a service"*
got a confident card instead of the refusal the design specifies.

THIS IS THE `assets: []` CLASS, and the fleet already has one guard against it. The arity
precondition in `dynamic_supervisor` abstains when a single-asset verb meets a set question with
nothing to ask about, and its comment names the original: `describeAsset` resolved, routed, and
*"honestly returned `assets: []`"*, and that zero-asset answer came straight back. That guard
defends ONE instance — a declared-single verb with no askable slot. A routed verb whose payload
says it abstained is the same defect one door over, and it was unguarded.

WHY THIS IS NOT AN `ELICITATION`. The abstain-as-ask ruling (2026-09-17) draws an abstain as a
menu whose options are verbs, and `presentation_agent/main.py` follows it — but only when
candidates exist. The no-candidates branch is explicit that an empty menu must NOT be drawn: *"it
means the registry held nothing comparable for this subject, which the ordinary refusal path says
in words."* A doc-corpus gap has nothing to offer as options either, so inventing an empty menu
here would contradict a live ruling. The abstain stays a worded answer; what changes is that the
ROUTING LAYER now says it abstained, which is the layer ADR-0033's `route | ask | abstain` lives
at and the one a consumer can key on.

WHY `is True` AND NOT TRUTHINESS. Every payload field here crosses a JSON boundary from an engine
this module does not control. `"abstained": "false"` is a truthy string, and a bare truthiness
test would read an engine's *denial* as an abstain. The same trap classified-refusal tuples set in
`mesh_registration` — a tuple is truthy, so the retry there compares `is True` as well.

TWO SPELLINGS ON TWO AXES, KEPT APART DELIBERATELY. `route_status` says `"abstained"` (past
tense; `dynamic_supervisor` has used that spelling for the classifier's abstain since ADR-0008's
amendment). The ADR-0033 DISPOSITION vocabulary says `"abstain"` (`direct_dispatch.ABSTAIN`).
They describe different axes — what the run's routing concluded, versus which of route/ask/abstain
the disposition chose — and collapsing them would give one word two meanings. `MATCHED` is
imported rather than restated so that "matched" has exactly one spelling in this codebase.

A CONSEQUENCE, RECORDED BECAUSE IT IS REAL. `primary_selection.pick_primary` picks the first
subtask whose status is `MATCHED`, falling back to the first item when none matched. An abstaining
subtask therefore stops being eligible as primary and yields to a sibling that answered — which is
the behaviour you want, and is already true of the classifier's abstain. A single-subtask turn
(every docs census row) is unaffected: with nothing matched, the fallback returns that same item.
"""
from __future__ import annotations

from typing import Any

from iagent_pure.primary_selection import MATCHED

#: The `route_status` an abstaining engine's subtask carries. NOT a new value: `dynamic_supervisor`
#: already stamps this exact string for the classifier's abstain, and one axis gets one spelling.
ABSTAINED = "abstained"

#: The payload field an engine sets to say it declined to answer. Named here, once, so the
#: producer and every reader agree on it by import rather than by two matching string literals.
ABSTAIN_FIELD = "abstained"


def engine_abstained(payload: Any) -> bool:
    """True when an engine's payload says it abstained.

    STRICTLY `is True`, for the reason in the module docstring: this value crossed a JSON
    boundary, and a truthy `"false"` must not read as an abstain.
    """
    if not isinstance(payload, dict):
        return False
    return payload.get(ABSTAIN_FIELD) is True


def route_status_for(payload: Any) -> str:
    """The `route_status` a dispatched engine's answer earns: `ABSTAINED`, else `MATCHED`.

    One function so the supervisor and the census runner cannot drift into two rules that only
    agree in a docstring — the failure `pick_primary` was extracted to prevent, twice.
    """
    return ABSTAINED if engine_abstained(payload) else MATCHED
