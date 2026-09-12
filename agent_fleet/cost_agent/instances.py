"""The instance provider for engine-cost: who the lots, suppliers and rate tables ARE.

WHY THIS MODULE EXISTS, and it is not symmetry with engine-fin.

Four questions from `docs/measurements/cost-card-walk-sheet.md` were typed into the UI on
2026-09-11 and none of them reached this engine. The classifier was right — `cost:Supplier`
at 0.92, with reasoning that correctly called "lot 4" a filter rather than the subject — and
the answer was thrown away by the instance pre-step, because a phone-book hit OVERRIDES
`resolved_uri` and the only provider holding a claim on "lot 4" was engine-fin's.

It answered `fin:WBSElement` at exactly 0.500, matching THE BARE DIGIT against `instance_id`.
Measured, not inferred (`docs/measurements/lot-4-resolves-to-program-support-2026-09-11.md`):

    'lot 4'    -> Program Support  0.500        'banana 4' -> Program Support  0.500
    'site 4'   -> Program Support  0.500        'xyzzy 4'  -> Program Support  0.500
    'lot four' -> (nothing)                     '4'        -> Program Support  1.000

`banana 4` is a fabricated control AND IT RESOLVED. `lot four` — the same meaning, spelled —
resolved to nothing. The digit was doing all the work.

So engine-cost had no claim to make on its own lots, which is why finance's stood unopposed.
That is the gap this module closes.

── THE PART THAT IS A DESIGN RULE, NOT A COPY ──────────────────────────────────────────
This engine's identifiers ARE BARE INTEGERS. `cost:ProductionLot` 4 has `instance_id` "4".
So a provider written the way the defect was written would not merely repeat it — it would
repeat it on the class where the collision is most natural, and the fleet would then have
TWO providers claiming every digit instead of one.

`candidates` below therefore carries three rules the fin scorer does not, each named with
the failure it prevents. They are stated here because the next provider author will copy
whichever file they open first, and the scoring tiers look interchangeable from outside.
"""
from __future__ import annotations

import re
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import COST, CostState
    from seed import RECIPIENT_SCOPES
except ImportError:
    from agent_fleet.cost_agent.entities import COST, CostState
    from agent_fleet.cost_agent.seed import RECIPIENT_SCOPES

MESH = "http://invincible-agent/mesh#"

#: Human labels for the accounting buckets. Importing `measures._CATEGORY_LABELS` would be
#: DRY-er and worse: reaching across modules for a private name to save four lines is the
#: trade that makes a rename silent. Sealed against drift instead.
_CATEGORY_LABELS = {
    "labor": "Labor", "material": "Material", "other_direct": "Other direct",
    "warranty": "Warranty", "contracts": "Contracted effort",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# Members — one builder per class, all read off STATE
# ---------------------------------------------------------------------------

def _lots(state: CostState) -> list[dict[str, str]]:
    # THE LABEL CARRIES THE CLASS WORD. "Lot 4", never "4". This is what lets an unscoped
    # identifier of "lot 4" match a LABEL exactly at 1.0 instead of arriving at the
    # token-overlap tier — which is the tier the engine-fin defect lives in.
    return [{"instance_id": str(n), "label": f"Lot {n}"} for n in state.lot_numbers]


def _suppliers(state: CostState) -> list[dict[str, str]]:
    # DEDUPED ACROSS LOTS. Every lot carries the same four shares, so iterating lots offers
    # each supplier nine times — the same duplication engine-fin hit on period-scoped
    # funding lines, arriving here by a different route.
    seen: dict[str, str] = {}
    for number in state.lot_numbers:
        for share in state.lot(number).suppliers:
            seen.setdefault(_slug(share.name), share.name)
    return [{"instance_id": k, "label": v} for k, v in sorted(seen.items())]


def _program(state: CostState) -> list[dict[str, str]]:
    return [{"instance_id": _slug(state.program_name), "label": state.program_name}]


def _categories(_state: CostState) -> list[dict[str, str]]:
    return [{"instance_id": k, "label": v} for k, v in sorted(_CATEGORY_LABELS.items())]


def _rate_tables(state: CostState) -> list[dict[str, str]]:
    # ONE INSTANCE PER (fiscal year, vintage) PAIR, because that is what identifies a rate
    # table here — `cost_rate_assumptions` takes both, and two vintages of one year are BOTH
    # correct (`entities.VintageRequired` exists for exactly that ambiguity). Enumerating by
    # year alone would build a menu that cannot answer the question it is offered for.
    return [{"instance_id": f"{fy}-{vintage}", "label": f"FY{fy} {vintage}"}
            for (fy, vintage) in sorted(state.rates)]


def _recipients(_state: CostState) -> list[dict[str, str]]:
    # A DISCLOSURE SLOT IS THE STRONGEST CASE FOR A MENU, not the weakest. `recipient_scope`
    # is spoken-mandatory with no default and no "all lots" fallback; without enumeration an
    # elicitation offers FREE TEXT for the one slot that decides who may see the data.
    return [{"instance_id": k, "label": k} for k in sorted(RECIPIENT_SCOPES)]


#: The classes this provider holds. ONE MAP read by both the resolver and the enumerator, so
#: they cannot disagree about what this engine offers — two lists of one thing is the
#: second-registry shape that produced `unsupported` for a class engine-fin routed on.
_RESOLVABLE: dict[str, Any] = {
    COST + "ProductionLot":       _lots,
    COST + "Supplier":            _suppliers,
    COST + "ProductionProgram":   _program,
    COST + "CostCategory":        _categories,
    COST + "RateTable":           _rate_tables,
    COST + "DisclosureRecipient": _recipients,
}

#: EMPTY, AND THAT IS A CHECKED CLAIM rather than an omission: every class this engine
#: registers a verb on appears in `_RESOLVABLE` above. `assert_subject_coverage` proves it
#: at boot, so a tenth verb on a new class fails at STARTUP and not at an elicitation.
_NOT_ENUMERABLE: set[str] = set()

#: Classes this provider can find that no verb serves. Also empty, also asserted at boot.
_NO_VERB_BY_DESIGN: set[str] = set()


def members_of(state: CostState, class_uri: str) -> list[dict[str, str]]:
    builder = _RESOLVABLE.get(class_uri)
    return list(builder(state)) if builder else []


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_DIGIT_TOKEN = re.compile(r"^\d+$")


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower())) - {""}


def _digits(tokens: set[str]) -> set[str]:
    return {t for t in tokens if _DIGIT_TOKEN.match(t)}


#: Below this the provider abstains. AN EMPTY LIST IS A FIRST-CLASS ANSWER — a least-bad id
#: is how a confidently wrong answer reaches a verb and comes back as a number.
RESOLVE_FLOOR = 0.5


def candidates(state: CostState, text: str, class_uri: Optional[str] = None
               ) -> list[dict[str, Any]]:
    """Score a spoken name against this engine's instances. Deterministic, no model.

    THREE RULES THIS SCORER HAS THAT THE ONE IT WAS COPIED FROM DOES NOT. Each is here
    because of a failure that was OBSERVED, not imagined:

    1. **A bare number is not a name unless the caller supplied the class.** An identifier
       of "4" with no `class_uri` returns nothing. This engine's lot ids ARE bare integers,
       so without this rule engine-cost would claim every digit in the fleet — the exact
       defect it was built to stop being the only victim of. WITH a `class_uri`, "4" is a
       legitimate 1.0, because then something other than the digit established the class.

    2. **A contradicted digit disqualifies; it never merely fails to help.** "lot 9"
       compared against Lot 4 shares the token "lot" and would otherwise score 0.6 — a
       confident WRONG lot, which is worse than no lot. If the needle names a number and
       the member has one, they must agree.

    3. **Words establish, digits corroborate.** The overlap tier requires a WORD in common
       before a digit may add anything. `banana 4` and `xyzzy 4` — the controls that caught
       the original defect — reach this tier and are refused by it. `lot 4 cost` is not,
       because "lot" carries the claim and "4" then sharpens it.

    Tiers carry DISTINCT scores so a caller's gate can tell "exact" from "shared one common
    word". A single blended score is where a least-bad id gets promoted into an answer.
    """
    needle = text.strip().lower()
    if not needle:
        return []

    needle_tokens = _tokens(needle)
    needle_digits = _digits(needle_tokens)
    needle_words = needle_tokens - needle_digits

    # RULE 1 — refuse an unscoped bare number before looking at a single member.
    if needle_digits and not needle_words and not class_uri:
        return []

    out: list[dict[str, Any]] = []
    for uri in _RESOLVABLE:
        if class_uri and class_uri != uri:
            continue
        for member in members_of(state, uri):
            ident, label = member["instance_id"], member["label"]
            hay_id, hay_label = ident.lower(), label.lower()
            hay_tokens = _tokens(hay_label) | _tokens(hay_id)
            hay_digits = _digits(hay_tokens)
            hay_words = hay_tokens - hay_digits

            # RULE 2 — a named number that disagrees is disqualifying.
            if needle_digits and hay_digits and not (needle_digits & hay_digits):
                continue

            if needle in (hay_label, hay_id):
                score = 1.0
            elif needle in (hay_id.replace("-", " "), hay_label.replace("-", " ")):
                score = 0.95
            elif needle in hay_label or needle in hay_id:
                score = 0.75
            else:
                # RULE 3 — words establish, digits corroborate.
                word_overlap = needle_words & hay_words
                if not word_overlap:
                    continue
                score = 0.4 + 0.2 * (len(word_overlap) / max(len(needle_words), 1))
                if needle_digits & hay_digits:
                    score += 0.2
            out.append({
                # `instance_id`, NEVER `identity`. Engine O reads `c.get("instance_id")` and
                # coerces a miss to "" — so the wrong key resolves "successfully" with no
                # usable id, which is a success message wrapped around a blank.
                "instance_id": ident, "label": label,
                "class_uri": uri, "score": round(min(score, 1.0), 3),
            })
    out.sort(key=lambda c: (-c["score"], c["class_uri"], c["instance_id"]))
    return out


def resolve(state: CostState, identifier: str, class_uri: Optional[str] = None
            ) -> list[dict[str, Any]]:
    """Candidates at or above the floor. The gate is `>=`, and that matters here.

    The defect this module answers passed a `>=` gate at EXACTLY 0.5 — a boundary value
    clearing by the narrowest margin the code permits. Rules 1-3 above are what keep this
    engine's floor from being reachable by an accident of tokenization; the comparison is
    left as `>=` deliberately, so the fleet's providers agree on the gate and disagree only
    where they should, which is in what they are willing to score.
    """
    return [c for c in candidates(state, identifier, class_uri)
            if c["score"] >= RESOLVE_FLOOR]


def enumerate_class(state: CostState, class_uri: str, limit: int = 8) -> dict[str, Any]:
    """Members, or a refusal in one of two named ways that mean different things.

      * `members`     — here they are, and a menu is legitimate.
      * `too_many`    — the class is real and larger than a menu, WITH ITS COUNT. An ask may
                        fall back to free text on the strength of this, because a provider
                        REPORTED unboundedness.
      * `unsupported` — this provider does not hold that class. Free text here would be
                        falling back because nobody attempted enumeration, which is the case
                        the distinction exists to refuse.
    """
    base = {"output_uri": MESH + "InstanceEnumeration", "class_uri": class_uri,
            "provider": "engine_cost_production_cost"}
    if class_uri not in _RESOLVABLE:
        return {**base, "outcome": "unsupported",
                "reason": ("engine-cost holds no addressable members of this class. Classes "
                           "it does enumerate: " + ", ".join(sorted(_RESOLVABLE))),
                # CARRIED EMPTY, matching engine-p and engine-fin. A consumer doing
                # `.get("members") or []` should not have to special-case which outcome it
                # is reading.
                "members": []}
    members = members_of(state, class_uri)
    if len(members) > limit:
        # THE COUNT IS THE POINT. "too many" without a number is indistinguishable from "I
        # did not look", and the ask downstream decides on exactly that difference.
        return {**base, "outcome": "too_many", "count": len(members),
                # `bound`, matching engine-p's spelling rather than inventing `limit`. A
                # second spelling for one concept is how the next reader picks the wrong one.
                "bound": limit, "members": []}
    return {**base, "outcome": "members", "members": members, "count": len(members)}
