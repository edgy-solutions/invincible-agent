"""Engine S's instance provider — resolving a spoken safety name to an identifier.

**WHY THIS EXISTS, MEASURED 2026-09-14.** The safety walk asked *"draft a risk assessment for
HAZ-1003"* and got back *"you named a specific item, but no provider in the mesh recognizes it."*
`HAZ-1003` was in the engine's fixture the whole time — **registration is not resolution**, and a
verb that takes a hazard is unreachable by name until something claims that class's identifiers.
The ask then fell through to General search, Engine A and a DATA_ENGINEERING refusal, which is a
routing defect of its own and not this module's to fix.

── THE RULE THIS MODULE INHERITS FROM engine-cost, WHICH PAID FOR IT ───────────────────────────
A provider that scores generously poisons every rival's answer. engine-fin's scorer matched **the
bare digit** in "lot 4" against an `instance_id` and returned 0.500; because a phone-book hit
overrides a classifier's `resolved_uri`, that nonsense **displaced a correct 0.92 cost answer**,
and `banana 4` reproduced it. The lesson was written as a rule and it applies here unchanged:

    A BARE NUMBER IS NOT A NAME unless the caller supplies the class.

Safety identifiers are *prefixed* (`HAZ-1003`, `CSI-5001`, `MIT-2103`, `WO-3001`), which makes
them far less collidable than a bare integer — and that is exactly why the rule is stated rather
than assumed. `1003` alone must not resolve to `HAZ-1003`: some other engine's model may hold a
bare 1003, and a provider claiming every digit in the fleet is the defect this rule exists for.

**THE FLOOR IS A LOCAL CONSTANT, AND THAT IS A KNOWN WEAKNESS STATED RATHER THAN DRESSED UP.**
0.5 is declared here because there is no fleet-wide declaration to read: engine-cost declares its
own `RESOLVE_FLOOR = 0.5` and so does this one. **Two providers agreeing by coincidence is not
agreement** - the same shape as three providers each inventing a default `limit` of 8 and calling
it the fleet default. It is a named constant so a divergence shows in a diff, and the durable fix
is a declared fleet floor every provider reads. Filed, not invented here: a private fourth copy
would deepen the problem while looking like consistency.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:  # flat in the image (/app), packaged in the repo — runbook §5, FLAT FIRST.
    from entities import CRITICAL_ITEMS, HAZARDS, WRITE_UPS
except ImportError:  # pragma: no cover
    from agent_fleet.safety_agent.entities import (  # type: ignore[no-redef]
        CRITICAL_ITEMS,
        HAZARDS,
        WRITE_UPS,
    )

SAFETY = "http://internal/sustainment/safety#"

#: The gate, `>=`, matching the fleet's other providers. Stated here as a named constant so a
#: change is visible in a diff rather than buried in a comparison.
RESOLVE_FLOOR = 0.5

#: Shortest query that may match as a CONTAINED PHRASE. Below this a query is a topic word rather
#: than a name — "the", "bus", "chafed" — and a provider answering those with a specific instance
#: is the phone book this module exists not to be. 8 admits real phrases ("wiring loom", "aft
#: equipment bay") and excludes every single common word in the fixture's descriptions.
_MIN_PHRASE_CHARS = 8


def _members() -> Dict[str, List[Dict[str, str]]]:
    """class URI -> [{identifier, label}], derived from the fixture.

    DERIVED, NOT LISTED. A hand-kept catalogue of what this provider claims would be a second
    declaration of the fixture and would disagree with it on the first change — the same
    hand-kept-list shape this arc has met repeatedly. Adding a hazard to `entities.py` makes it
    resolvable here with no edit.
    """
    return {
        SAFETY + "Hazard": [
            {"identifier": h.hazard_id, "label": h.description} for h in HAZARDS
        ],
        SAFETY + "SafetyCriticalItem": [
            {"identifier": c.csi_id, "label": f"{c.part_number} — {c.description}"}
            for c in CRITICAL_ITEMS
        ],
        SAFETY + "WriteUp": [
            {"identifier": w.write_up_id, "label": w.narrative} for w in WRITE_UPS
        ],
        # ── `maint:WorkOrder` IS DELIBERATELY NOT CLAIMED HERE, AND IT IS A QUESTION, NOT AN
        #    OVERSIGHT ─────────────────────────────────────────────────────────────────────
        #
        # `assessDeferralRisk` takes a work order, so "assess the deferral risk for WO-3001"
        # will fail to resolve exactly the way `HAZ-1003` did until somebody claims that class.
        # This engine is NOT the obvious somebody: work orders are the MAINTENANCE plane's, and
        # ADR-0035's two planes plus this module's own engine docstring say an analysis engine
        # reads a plane it does not own.
        #
        # Claiming them because they happen to sit in this engine's fixture would be an
        # ownership decision made by a convenience — the same shape as filing cost classes under
        # the finance domain because a manifest field was handy. So the gap is left OPEN and
        # NAMED rather than closed quietly, and the scope question goes to the architect: either
        # Engine E resolves work orders, or Engine S is ruled the provider for the ones it holds.
        #
        # THE WALK DOES NOT NEED IT YET. Step 2 asks for a hazard, and `safety:Hazard` is
        # claimed below. Shipping the half that is unambiguous beats claiming a plane to save a
        # later round trip.
    }


def _score(identifier: str, member: Dict[str, str]) -> float:
    """Exact identifier, then exact label, then contained phrase, then token overlap.

    ⛔ NO BARE-SUFFIX MATCHING. `1003` does not score against `HAZ-1003`, and that omission is
    the whole point of the module docstring: matching the numeric tail of a prefixed identifier
    is precisely the `banana 4` behaviour, one naming convention along.
    """
    q = identifier.strip().lower()
    if not q:
        return 0.0
    ident = member["identifier"].lower()
    label = (member["label"] or "").lower()

    if q == ident:
        return 1.0
    if q == label:
        return 0.95
    # The spoken form often carries the identifier inside a sentence fragment.
    if ident in q:
        return 0.9
    # ⛔ A CONTAINED PHRASE MUST BE A PHRASE, AND THIS BRANCH WAS THE PHONE BOOK IN MINIATURE.
    #
    # It read `if q in label: return 0.7` — a bare substring test — so `"the"` resolved to every
    # hazard whose description contains the word, and `"Chafed"` resolved to HAZ-1001 at 0.7.
    # THIS MODULE'S OWN SEAL CAUGHT IT, in the file whose docstring is an essay about not being
    # the fleet's phone book: the rule was stated, attributed to engine-cost, and then not
    # implemented in the branch directly beneath it.
    #
    # Two conditions now and both are needed. WORD BOUNDARIES, so a query cannot match inside a
    # longer word. And a LENGTH FLOOR, because a single short word is a TOPIC, not a NAME —
    # someone saying "chafed" is describing a kind of hazard, not identifying one, and answering
    # with a specific instance turns a vague question into a confident wrong subject.
    if len(q) >= _MIN_PHRASE_CHARS and re.search(rf"\b{re.escape(q)}\b", label):
        return 0.7

    q_tokens = {t for t in q.replace("-", " ").split() if len(t) > 2}
    l_tokens = {t for t in label.replace("-", " ").split() if len(t) > 2}
    if not q_tokens or not l_tokens:
        return 0.0
    shared = q_tokens & l_tokens
    # AT LEAST TWO SHARED TOKENS, AND THIS GUARD WAS MISSING TOO. With one token the overlap
    # ratio is 1.0 and `1.0 * 0.8` clears the 0.5 floor — so any single description word would
    # have resolved, by a DIFFERENT route than the substring branch above. Two independent paths
    # to one defect is why the abstention half of the seal is the load-bearing half.
    if len(shared) < 2:
        return 0.0
    overlap = len(shared) / len(q_tokens)
    # Scaled so a partial overlap lands BELOW the floor: two words out of eight is not an
    # identification, and scoring it at the floor is how a provider starts answering every
    # question that mentions a bus, a bay or a loom.
    return round(overlap * 0.8, 4)


def resolve(identifier: str, class_uri: Optional[str] = None) -> List[Dict[str, Any]]:
    """Candidates at or above the floor, highest first.

    AN EMPTY LIST IS A FIRST-CLASS ANSWER. The provider abstains below its floor rather than
    offering a least-bad match — a wrong instance resolved confidently is worse than no
    instance, because the verb then runs against the wrong subject and answers.
    """
    out: List[Dict[str, Any]] = []
    for cls, members in _members().items():
        if class_uri and class_uri != cls:
            continue
        for m in members:
            score = _score(identifier, m)
            if score >= RESOLVE_FLOOR:
                out.append({
                    "class_uri": cls,
                    "instance_id": m["identifier"],
                    "label": m["label"],
                    "score": score,
                })
    out.sort(key=lambda c: (-c["score"], c["instance_id"]))
    return out


def enumerate_class(class_uri: str, limit: int = 25) -> Dict[str, Any]:
    """Members, `too_many`, or `unsupported` — three named outcomes, never a bare empty list.

    `unsupported` MUST NOT BE SPELLED AS AN EMPTY MEMBER LIST. A class this provider does not
    hold and a class it holds zero members of are different facts, and collapsing them lets an
    elicitation offer "no options" for a class nobody asked this engine about. The discriminant
    is `outcome`; a consumer reads that field and never parses a message.
    """
    members = _members().get(class_uri)
    if members is None:
        return {
            "outcome": "unsupported",
            "class_uri": class_uri,
            "reason": "engine-safety does not hold that class",
            # WHAT IT DOES HOLD, so the caller can correct itself rather than guess. A refusal
            # that names only what failed makes the next attempt another guess.
            "supported": sorted(_members()),
        }
    if len(members) > limit:
        return {
            "outcome": "too_many",
            "class_uri": class_uri,
            "count": len(members),
            "limit": limit,
        }
    return {
        "outcome": "members",
        "class_uri": class_uri,
        "count": len(members),
        "members": members,
    }
