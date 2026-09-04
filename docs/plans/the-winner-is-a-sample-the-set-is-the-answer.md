---
id:         the-winner-is-a-sample-the-set-is-the-answer
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0031 (instance resolution ladder); ADR-0025 (the can_view-filtered candidate pool)
code-site:  agent_fleet/ontology_service/main.py (/resolve — candidate recall, then selection), docs/measurements/engine-f-end-to-end-routing-v1.md and engine-f-grounding-corpus-v1.json (the totals this retires)
summary:    MEASURED 2026-09-01, arm A n=3 on one fixed substrate, recording the candidate SET and the WINNER on every draw. The candidate sets are DETERMINISTIC — 0 of 20 flipped. The winner selected from them is NOT — 2 of 20 flipped, and that is a FLOOR rather than a rate: a third row flipped between two earlier runs and held across these three, so n=3 understates it. CONSEQUENCE: a right-class grounding TOTAL is not a usable instrument at this precision, because it sums twenty draws from a partly non-deterministic selection layer sitting on top of a stable one. This retires BOTH published totals for the finance corpus — 11/20 and 12/20 — and, more importantly, retires the DIFFERENCE between them, which was read as substrate evidence and discriminates nothing: one of the two known-unstable rows IS the row the difference consisted of. THE FORBIDDEN ARITHMETIC is treating 2/20 as a noise budget and subtracting it from a delta; the claim the data supports is qualitative and stronger than any budget. What to measure instead: SET DISJOINTNESS, which is measured on the deterministic layer. SCOPE ESCALATED 2026-09-02: the non-determinism is NOT confined to the layer measured here. `"what is the funding status"` — one of the rows already named unstable — produced `subject_uri=UNKNOWN subject_conf=0.0 fallback_reason=subject_unknown` on one draw and grounded to `fin:Program` at 0.9 on both re-draws. That is the GROUNDING layer failing, not a different winner inside a stable set, and it is WORSE: a subject_unknown skips the mesh entirely for the generalist fallback, so the question is answered by a component that was never eligible. n=3 on a known flipper evidences no rate and none is claimed; what changed is the finding's SCOPE.
---

# The winner is a sample; the set is the answer

**Framing owed to Lane 1**, who put it better than I had: *the SET is the system's answer and
the WINNER is a sample from it, so any measurement that scores the winner is measuring the
sampler as much as the system.*

## The measurement

`/resolve`, arm A (`domains=["PROGRAM_FINANCE"]`, `user_email=alice@example.com`), 20 finance
phrasings, **n=3 on one fixed substrate**, recording the candidate set and the winner on every
draw:

| | result |
|---|---|
| rows whose candidate **SET** flipped across 3 draws | **0 / 20** |
| rows whose **WINNER** flipped across 3 draws | **2 / 20** |
| rows where both flipped | 0 / 20 |
| shape occurrences in the sets | 24 across 14 phrases — reproduced exactly |

The two flippers:

```
"show me SPI over time"     EarnedValueTechnique  <-> PerformanceMeasurementBaseline
"how fast are we spending"  FundingLine           <-> PerformanceMeasurementBaseline
```

**The recall layer is deterministic and the selection layer is not.** Same substrate, same
query, minutes apart: identical candidate set, different pick.

## 2/20 IS A FLOOR, NOT A RATE — and the difference matters

`"what is the funding status"` flipped between two earlier runs (`FundingStatusGrid` /
`FundingLine`, identical set both times) and was **stable across these three**. So at least
three rows are unstable and **n=3 understates it**.

> ### ⛔ THE FORBIDDEN ARITHMETIC
>
> Do not treat `2/20` as a noise budget, subtract it from a delta, and believe the remainder.
> That is precisely the reasoning this finding forbids: the floor is an **existence proof**,
> not a magnitude, and a reader who budgets with it will license exactly the comparisons that
> are unavailable.
>
> **The supportable claim is qualitative and stronger than any budget: a right-class grounding
> total is not a usable instrument at this precision.**

## What this retires

**Both published finance totals, and the difference between them.**

Two lanes measured the same corpus and got `11/20` and `12/20`. The gap was attributed to
substrate — one set of draws was taken mid-ingest — and one number was retired on those
grounds. **The row the gap consisted of is `"show me SPI over time"`, which is one of the two
rows that flips on a fully-ingested substrate.**

So "biased by an incomplete substrate" and "unstable regardless of substrate" are competing
explanations for one row, and **the 11-vs-12 gap discriminates between them not at all.**
Neither total is reinstated. Reclaiming one would repeat the original error backwards —
treating a total as a fact about the system when it is a draw from a sampler.

*(Five consecutive identical draws is unlikely under an unbiased flip, so substrate bias
remains live as a hypothesis. It is simply not evidenced by this comparison.)*

## What to measure instead

**Set disjointness**, asserted per row, because it reads the layer that holds still:

* did the candidate set change, and how;
* did a named class leave or enter a set;
* aggregate over sets, not over winners.

Concretely for the response-shape exclusion this corpus was built to measure: the assertion is
**24 shape-occurrences across 14 sets → 0**, per-row, with totals reported for continuity and
explicitly **not interpreted**. And record the winner *alongside* the set on every draw, so a
flip reads as a flip rather than being laundered into a total.

## Why the control is not affected

`arm C` (no `domains`, so scoped to `MAINTENANCE`) has reproduced **7/20 across three separate
primes**. That is not a counter-example: most of its rows ground outside `fin:` entirely and
land in the same bucket whichever way an unstable row falls. A stable total over a corpus whose
instability sits inside one bucket is consistent with an unstable sampler — which is itself a
caution, because **a total can look reproducible for reasons unrelated to the thing it
measures**.

## Scope, and what is NOT claimed

* **Not** that `/resolve` is broken. A stable set with a sampled winner may be entirely by
  design — the selection step is BAML-backed and nothing promises determinism.
* **Not** a rate, a budget, or a confidence interval. n=3 over 20 rows supports existence, not
  magnitude.
* **Not** specific to finance. The mechanism is the recall/selection split, which every
  grounded question crosses. A planning or catalog corpus scored by right-class totals inherits
  the same defect; none has been measured for it.

## 2026-09-04 — ONE OF THE FLIPPING ROWS WAS FLIPPING ONTO A DEAD END

**Two lanes had two ends of one incident and neither saw the other.** This packet recorded
`"show me SPI over time"` flipping between `PerformanceMeasurementBaseline` and
`EarnedValueTechnique` and filed it as WINNER INSTABILITY. Engine F separately found that
`fin:EarnedValueTechnique` is **served by no verb in any scope** — verified against the live
graph, 0 verb edges, while every other groundable `fin:` class carries between one and six.

**They are the same row.** The sampler was not choosing between two answers; it was choosing
between an answer and a fall-through.

### This makes the CONSEQUENCE of a winner flip worse than recorded here

The packet treats a flip as landing on a different-but-comparable class, which is why
"a right-class total is not a usable instrument" was the strongest claim drawn from it. That
understates it. A flip between a SERVED and an UNSERVED class is not a coin toss between two
readings — one outcome routes and answers, and the other **grounds at high confidence, finds
no verb, and falls through to the generalist, which answers wearing the caller's persona.**

So a row can be recorded as "unstable" when half its draws are not answers at all. **Nothing
in a winner-scored run distinguishes those two outcomes**, because both produce a class name
to write in the results column.

### What to record per draw, revised again

The escalation below added `subject_unknown` as a third outcome alongside the set and the
winner. This adds a fourth thing, and it is a property of the WINNER rather than of the draw:

> **does the class that won carry a verb in this scope?**

It is cheap — one lookup against the registered verb edges — and without it a corpus cannot
tell a wrong answer from no answer. Both of this lane's measurement instruments were blind to
it: the grounding corpus scored the class name, and the boot guard could not see the class at
all (`[[a-namespace-is-declared-in-four-places]]`'s sibling — the guard reads what the ENGINE
resolves, the router reads what the PRIME seeded).

### And "unserved" is DOMAIN-RELATIVE, which neither lane had right at first

Credit where it is owed: a first pass over `idp:` reported **four** unserved classes by
counting verb subjects globally from source. Checked per scope against the live graph it is
**two** — `Dashboard` and `Table` carry nine verbs each in `DATA_ENGINEERING` and correctly
zero under `PORTFOLIO_PLANNING`, which is the domain filter working rather than a gap.

**So the assertion that holds is UNSERVED IN EVERY SCOPE.** A global count reports a class as
fine when a user in one domain cannot route to it; a per-domain count reports it as a gap when
it is correctly out of scope. Neither number is the answer alone.

`fin:EarnedValueTechnique` was re-checked under the stricter test and still qualifies: 0 verb
edges in every scope.

## SCOPE ESCALATION 2026-09-02 — the recall layer is not unconditionally deterministic either

This packet's central split was: **the candidate SET holds still (0/20 flipped) and the WINNER
does not (≥2/20).** The remedy that follows — assert on the set — depends on the first half.

**One draw has now failed on the set side.** `"what is the funding status"`, measured through
the full path 2026-09-02:

```
draw 1:  subject_uri=UNKNOWN  subject_conf=0.0  fallback_reason=subject_unknown
         → generalist fallback (ADR-0019 Contract B: no LLM call without subject grounding)
draw 2:  subject_uri=fin#Program  subject_conf=0.9   compatible_count=6  → finFundingStatus 0.96
draw 3:  subject_uri=fin#Program  subject_conf=0.9   compatible_count=6  → finFundingStatus 0.96
```

**Note which row this is.** It is the same phrasing recorded above as the third unstable row —
the one that flipped `FundingStatusGrid` / `FundingLine` between earlier runs and then held
across three. It has now failed a third distinct way.

### Why this is worse than a winner flip, and not merely different

A winner flip returns a wrong-but-eligible class from a correct set: the mesh still answers, and
the answer is traceable to a candidate that genuinely competed. **A `subject_unknown` produces no
set at all.** Contract B correctly refuses to make an LLM call without subject grounding, so the
question leaves the mesh and is answered by the generalist fallback — a component that was never
in any candidate set, carries no `output_uri`, and therefore also lands on the undiscriminated
KNOWLEDGE_DOCUMENT floor (`[[a-fallback-that-absorbs-every-failure-reports-none]]`).

So the failure is invisible twice over: it does not appear as a bad choice, and its card looks
like three other failure modes.

### What is NOT claimed

n=3, on a row already known to be unstable. **No rate, no direction, and specifically no claim
that grounding instability is new** — nothing here was measured for it before, so "it now reaches
grounding" is a statement about THIS PACKET'S SCOPE, not about a change in the system. Reading
1-in-3 as a frequency would be the forbidden arithmetic above, in the same shape.

What IS supportable: **"assert on the set" is a narrower remedy than this packet implied.** The
set is the right unit and it is far steadier than the winner, but it is not a fixed point, and a
measurement that assumes a set always exists has an unhandled case. Record `subject_unknown` as a
distinct outcome alongside the set and the winner, rather than as a missing row.

### Owed by this escalation

A determinism run that records THREE things per draw — grounded subject, candidate set, winner —
so a grounding failure is visible as itself. Every run to date recorded the last two.

## Owed

* A determinism run at higher n, on a corpus that is not finance, to establish whether the
  floor is ~10% or much higher. Until then no rate is quotable.
* An annotation on `engine-f-end-to-end-routing-v1.md` pointing here, so its published totals
  are not read as facts. **Done in the same change as this packet.**
