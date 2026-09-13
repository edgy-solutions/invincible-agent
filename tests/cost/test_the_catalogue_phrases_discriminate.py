"""A synonym claimed by two verbs decides nothing, which is the one job a synonym has.

MEASURED ON THE LIVE FLEET 2026-09-12, after `invincible-agent-22` observed that
"how does base cost build up to the price" returned `costCategoryBreakdown` at 0.72 and
declined to seal their preferred answer — *"a preferred answer written into a baseline is a
guess wearing a baseline's clothes."*

The cause was in this engine's own declarations, not in the router:

    find_tool("how did the price build up"):
      subject cost:ProductionLot  -> costPriceComposition
      subject cost:CostCategory   -> costCategoryBreakdown

**The phrase was a declared synonym of BOTH verbs**, so it carried no discriminating power at
all and whichever subject won chose the answer. And the same verb declared "show the burden
stack" as an ANTI-synonym while claiming "how did the price build up" — the same question in
different words. Each list was correct read on its own; the contradiction only existed
between them, which is why review never caught it.

These seals are derived from `CATALOGUE` rather than listing phrases, so a tenth verb is
covered by the commit that adds it.
"""
from __future__ import annotations

import collections

from agent_fleet.cost_agent.main import CATALOGUE


def _synonyms():
    return {e["fn"]: list(e["synonyms"]) for e in CATALOGUE}


def _anti():
    return {e["fn"]: list(e.get("anti_synonyms", ())) for e in CATALOGUE}


def test_no_phrase_is_a_synonym_of_TWO_verbs():
    """The defect that reached a live card, asserted directly."""
    owner = collections.defaultdict(list)
    for fn, phrases in _synonyms().items():
        for p in phrases:
            owner[p].append(fn)

    shared = {p: v for p, v in owner.items() if len(v) > 1}
    assert not shared, (
        f"these phrases are claimed by more than one verb, so they cannot decide between "
        f"them and the SUBJECT silently chooses the answer: {shared}"
    )


def test_no_verb_declares_a_phrase_as_BOTH_synonym_and_anti_synonym():
    """The direct contradiction. Cheap, and it had never been checked."""
    syn, anti = _synonyms(), _anti()
    contradictions = {
        fn: sorted(set(syn[fn]) & set(anti.get(fn, [])))
        for fn in syn if set(syn[fn]) & set(anti.get(fn, []))
    }
    assert not contradictions, contradictions


# ── A SEAL I WROTE, RAN, AND DELETED — recorded so it is not re-added ───────────────────
# I asserted that every anti-synonym must be the EXACT synonym string of some other verb,
# reasoning that an anti-synonym pointing at nothing steers away from traffic that cannot
# arrive. It went red across five verbs, and the design is right and the seal was wrong:
# anti-synonyms are deliberately PARAPHRASES of a neighbour's territory, not quotations of
# it. `cost_category_breakdown` pushes away "what were the labor hours"; the labor verb's
# declared synonyms are "labor split for a lot" and "touch versus support hours". Both are
# correct, and no exact match exists between them by design.
#
# Loosening it to a fuzzy match would have made it pass without asserting anything, which is
# the worse of the two outcomes. So the exact-match requirement survives only where the
# phrases really are quotations of each other — the pair below, which is where the defect was.


def test_the_price_walk_and_the_bucket_split_are_kept_apart_IN_BOTH_DIRECTIONS():
    """The specific pair this file exists for, asserted as a mutual exclusion.

    `cost_price_composition` decomposes a total by BURDEN STEP; `cost_category_breakdown`
    reports what SHARE each accounting bucket is. They decompose the same total along
    different axes, which is why the catalogue calls them the sharpest pair in the engine —
    and why one quietly claiming the other's phrase went unnoticed for so long.
    """
    syn, anti = _synonyms(), _anti()

    assert "how did the price build up" in syn["cost_price_composition"]
    assert "how did the price build up" in anti["cost_category_breakdown"], (
        "the bucket-split verb must actively push the price-walk phrasing away; merely not "
        "claiming it leaves the phrase to whichever subject happens to win"
    )
    assert "show the burden stack" in anti["cost_category_breakdown"]
