# The a-degradation-must-name-itself law

> **A fallback that absorbs every failure class reports none of them.** When N distinct failures
> collapse into one artifact, that artifact stops being an observation — and the system's most
> reassuring output becomes its least informative one.
>
> **A degraded path must report WHICH degradation.** Out of band, if the artifact itself cannot
> carry it.

Filed 2026-09-02 on **four verified instances**, three of them measured in a single week across
two lanes and four services. Framed jointly with the lane that owns two of the four; taken as
standing by both.

## The detection move — and it is the one that pays

> **"I fixed it and nothing changed" is evidence for this law, not against your repair.**

This is the reason the law is worth a principle rather than a packet. A collapsing fallback does
not merely fail to help — **it actively argues for the wrong conclusion.** Repair a real seam
sitting behind another one, and the observable is unchanged, which reads as a failed fix. The
natural next move is to re-open a repair that was already correct.

Measured: fixing the binding seam changed **nothing** a person could see, because two more seams
behind it produced the identical card. What prevented a wasted re-investigation was not insight —
it was three artifacts that discriminated where the card did not: a row count (23 → 29), a direct
probe of the selector (6/6, `source=registered`), and a **pre-registration written before the
run** predicting that the symptom would not move.

**When a correct repair produces no observable change, suspect a collapsing fallback before you
suspect the repair.**

## The four instances

| # | the collapse | distinct facts behind it | what everyone saw |
|---|---|---|---|
| 1 | the presentation fallback | **eleven** seams — missing prefix entry, slot timeout, subject-coverage gap, grounding failure, absent renderer — in four services with four owners | `Knowledge Document · No content available` |
| 2 | `fill_slots` returning `{}` | "the speaker named nothing" vs "we failed to look" — **opposite meanings, identical shape** | an ask card |
| 3 | `rejected: []` on capability registration | counts *admission* refusals only; Contract D graph failures are logged and never reach the response body | `200 OK, accepted: 29, rejected: []` |
| 4 | `dagster_run_failed` on the stream | the run logged `RUN_SUCCESS`; the client stopped waiting | "Pipeline failed." |

**Instances 3 and 4 are the same law pointing the other way.** In 1 and 2 a failure is hidden by a
success-shaped artifact; in 3 and 4 a *success* is hidden by a failure-shaped one. Both are the
artifact carrying less information than the system had.

Instance 4 has a second defect worth naming separately: `dagster_run_failed` is an **inference
stated as a fact**. The event that actually happened was `ui_payload_timeout`. A field that reads
like an observation but holds a guess is the same disease as a field named `rejected` that reports
one of two refusal kinds.

## THE PAIR — the counter-example that makes this arguable rather than merely felt

Same system, same week, two degraded cards. The only difference is whether the refusal named
itself.

| | `Knowledge Document · No content available` | `NOTHING TO DRAW — no numeric amount on any row` |
|---|---|---|
| distinct causes behind it | **eleven**, in four services | one |
| what it tells the reader | that something went wrong | **which contract clause failed** |
| time to root cause | **a night** | **minutes** |
| found by | three out-of-band artifacts and a pre-registration | reading the message |

**The second card is this law being obeyed, by a component nobody wrote it for.** cortex's
`validatePeriodSeries` returns a typed refusal reason — `"no numeric amount on any row"` — and
that one string carried the diagnosis: it named the clause, which named the field set, which
named the archetype mismatch. No probe, no correlation across three logs, no prereg.

It is also worth being precise about what the good card did NOT do. It did not say
`"unable to render"`, and it did not draw a chart with an empty series — **either would have
been a collapse.** The second is the more tempting: a component that draws whatever numbers it
can find always produces something, and what it produces is a confident wrong card. Refusing
*with a reason* is the behaviour, not refusing.

**And the refusal was still not enough on its own.** Two people reported those cards as
drawing — one measuring the selected archetype rather than the rendered artifact, one relaying
that report — and what closed the gap was a person opening the UI. A named refusal shortens the
diagnosis; it does not substitute for looking at the thing.

## The information usually already exists

**This is what makes the law cheap to obey and expensive to ignore: at every measured instance,
the discriminator was already computed and then discarded before it reached anyone.**

* `X-Presentation-Path` stamps four distinct values and **told instances 1 and 11 apart the entire
  time**. It exists because someone added it for an unrelated reason.
* `select_archetype` returns a provenance naming which refusal fired — `unrenderable` vs *"caller
  has no registered capability menu"* vs a `selection_basis` of `payload-only (output_uri matched
  no capability)`. All logged, none rendered.
* The supervisor logs `fill_slots unavailable … running on defaults` and `classify_predicate
  no_match … compatible=[…]`.

Three layers each held the answer. A person held a sentence that fit all of them.

**So the repair is usually plumbing, not construction** — carry what exists to the surface that
renders. Where the artifact genuinely cannot carry it (a card with no field for it, a dict with
one shape), the out-of-band channel is the answer, and the header above is proof that it works.

## Why it is not simply "log better"

A log is for the operator. **The person who asked the question is also a reader**, and the failure
they are shown is the one they act on. An ask that reads as a considered elicitation, produced by
a timeout, sends them to answer a question they already answered. That is not a logging gap; it is
the artifact making a claim that is not true.

And note what was *correct* in the worst instance: every guard downstream of the timeout made the
right decision. The router routed, the disposition correctly refused to default a mandatory slot,
the ask card correctly carried no output, the renderer correctly took its no-output branch.
**A correct decision on a corrupted input is indistinguishable from a correct decision** — which
is precisely why the degradation has to announce itself at the point it occurs.

## The seal

> **No two distinct failure classes may produce byte-identical output at the surface a person
> reads.**

Assertable over a fallback's own reason vocabulary, and it fails on first contact with any of the
four instances above. Where the vocabulary does not yet exist, its absence *is* the finding.

## Relation to the neighbouring laws

* `[[a-fallback-without-a-counter-becomes-the-architecture]]` — the closest sibling, and the
  distinction is worth keeping: that law is about a fallback firing *too often* and quietly
  becoming the normal path. This one is about a fallback that could fire exactly as often as it
  should and still destroy the information about **why**. A fallback can be correctly scoped,
  correctly rare, and still uninformative.
* `[[a-green-check-proves-only-its-scope]]` — the same disease in the affirmative: a signal that
  cannot distinguish two populations is not a measurement, whether it reads green or grey.
* `[[a-plausible-negative-is-not-a-considered-one]]` — the special case where the collapsed
  artifact reads as a *deliberate* negative.
* `[[a-registration-is-not-a-reachable-call]]` — supplies several of the failures that instance 1
  collapsed; the two laws compose, which is exactly how eleven seams reached one card.
