# An invariant between declarations is invisible to every per-declaration check

**Ruled 2026-09-12**, from a routing defect in engine-cost's verb catalogue. Routed to this lane
by `invincible-agent-65` after `invincible-agent-22` measured the symptom and declined to seal a
guess about it.

**Read each declaration on its own and every one is correct. The defect exists only in the
relation between two of them, and nothing that examines one at a time can see it.**

## The worked instance

`engine-cost` declares, per verb, a list of `synonyms` and a list of `anti_synonyms`. Two
independent facts:

    cost_price_composition    synonyms      include "how did the price build up"
    cost_category_breakdown   synonyms      include "how did the price build up"
    cost_category_breakdown   anti_synonyms include "show the burden stack"

**Every line is defensible alone.** A price-composition verb should claim the price-build-up
phrasing. A category-breakdown verb plausibly answers "how did the price build up" too, since it
also decomposes a total. And it should push away "show the burden stack", which is its
neighbour's territory.

**Between them, two contradictions:**

1. **A phrase claimed by two verbs decides nothing.** Measured live:

       find_tool("how did the price build up")
         subject cost:ProductionLot  -> costPriceComposition
         subject cost:CostCategory   -> costCategoryBreakdown

   The phrase carried **no discriminating power**, so whichever subject won chose the answer —
   and discriminating is the one job a synonym has.

2. **The same verb declared the same question as both wanted and unwanted.** *"How did the price
   build up"* and *"show the burden stack"* are the same question in different words; one was a
   synonym and the other an anti-synonym, on the same verb.

Neither is visible in a review of either list. Neither is visible to a per-verb test. **The
catalogue comment even calls this pair "the sharpest in the engine"** — the author knew the risk,
was looking straight at it, and still shipped it, because attention was on each declaration in
turn.

## The rule

> **The seal has to quantify over PAIRS.**

    # invisible to per-verb checks; both are two lines
    owner = defaultdict(list)
    for fn, phrases in synonyms.items():
        for p in phrases: owner[p].append(fn)
    assert not {p: v for p, v in owner.items() if len(v) > 1}

    assert not {fn: set(syn[fn]) & set(anti[fn]) for fn in syn if set(syn[fn]) & set(anti[fn])}

**Derive both from the declaration table, never from a list of phrases**, or the seal becomes the
same kind of artefact it is checking and a tenth verb is uncovered until someone remembers.

## Where else this shape lives

Anywhere a registry has per-row rules and an unstated cross-row one:

- **A phrase, name or id claimed by two rows** — routing synonyms, prefix tables, slot names.
- **A row asserting X while its neighbour asserts not-X about the same thing** — the case above.
- **Two computations of one truth by paths that never meet.** Same family, arriving through code
  rather than data: a verb's `available` and a route's `options`, each individually correct, with
  nothing asserting they agree. See
  [`reachability-is-a-property-of-a-path`](reachability-is-a-property-of-a-path.md).
- **Ordering and mutual exclusion**, which only exist between members by definition.

**The tell:** a rule you can state only by naming two things. *"This phrase belongs to that verb"*
is a sentence about a pair, so no assertion about one verb can hold it.

## And a seal over pairs must assert BOTH directions

Removing the duplicate is not enough. A phrase merely *not claimed* by the neighbour is still
available to whichever subject wins — so the neighbour must **actively push it away**, and the
seal must require the anti-synonym as well as forbid the synonym. **Half of a mutual exclusion is
not a weaker version of it; it is a different rule that happens to look similar.**

## A seal I wrote, ran, and deleted — recorded so it is not re-added

While sealing the above I asserted that **every anti-synonym must be the exact synonym string of
some other verb**, reasoning that an anti-synonym pointing at nothing steers away from traffic
that cannot arrive. It went red across five verbs, and **the design was right and the seal was
wrong**: anti-synonyms are deliberately *paraphrases* of a neighbour's territory, not quotations
of it.

Loosening it to a fuzzy match would have made it green while asserting nothing. **A seal relaxed
until it passes is worse than a deleted one, because it keeps the slot filled** — see
[`seals-must-be-proven-to-bite`](seals-must-be-proven-to-bite.md). The exact-match requirement
survives only for the one pair whose phrases really are quotations of each other.

Related: [`a-green-check-proves-only-its-scope`](a-green-check-proves-only-its-scope.md),
[`a-default-invented-locally-becomes-a-contract`](a-default-invented-locally-becomes-a-contract.md).
