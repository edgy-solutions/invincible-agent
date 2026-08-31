# The nobody-tried-is-not-a-kind-of-no law

> **Every two-valued outcome in this system has eventually grown a third value, and it is always
> the same one: *the question was never asked.* Folded into the negative, it reports a fact about
> the substrate when the truth is a fact about the caller — and it is invisible in exactly the
> way that costs the most time.**

Filed 2026-08-31 on **four verified instances**, one of which predates this arc and belongs to
someone else's code. The generalisation of the guard in
[`a-registration-is-not-a-reachable-call`](a-registration-is-not-a-reachable-call.md), which
gives the same advice for one domain; this law says the shape is not specific to registration.

## Why the third value is always missing at design time

A designer holds the successful case and the failed case in mind, because both are things the
component *does*. "Nobody invoked me" is not something the component does — it is the absence of
an event, and absences do not show up when you enumerate behaviours.

So the vocabulary ships with two values, the third case arrives anyway, and it lands on whichever
existing value is nearest. **It is always the negative one**, because the negative is where
"didn't work" goes — and that is what makes the mislabel expensive: an operator reading *"no
match"* debugs the matcher, and the matcher is fine.

## The instances

| # | vocabulary | the third value | what the fold cost |
|---|---|---|---|
| 1 | `instance_resolution.decide()` — `empty` vs `not_specific` | a result where **nothing was rejected** (`n=0, rejected_n=0`) | **hid the fan-out starvation bug.** In the code's own words: *"the vocabulary said 'the token is not a name' when the truth was 'the phone book was never asked a question it could answer.'"* |
| 2 | slot resolution — filled vs absent | **`not-attempted`**, beside `resolved`/`unresolved` | the natural implementation (substitute an id, pass the raw name through on failure) cannot say *tried and failed*, so an unresolvable name is **indistinguishable at the dispatch point from a success** and 422s |
| 3 | `enumerateInstances` — a list, or not a list | **`unsupported`** beside `too_many`, and **`no_provider`** in the consumer | *"I do not enumerate this"* and *"nobody asked me"* are different facts; merging them is how **"nobody built it" disguises itself as "nothing to offer"** |
| 4 | an ask's trigger — candidates, or `not_specific` | **`slot-unfilled`** — the filler never attempted the slot | a pre-registered prediction enumerated both *outcomes of an attempt* and missed *no attempt*; the case turned out to test extraction, not specificity |

Instance 1 is the load-bearing one for the law's credibility: **it is not mine, it predates this
arc, and its author had already fought and won the same fight** — the fix was to run the empty
check *before* the gate, so `empty` could not absorb a case the gate never saw.

## The tell, and it is available before you have a bug

> **Ask of any two-valued outcome: what does it return when the thing that produces it was never
> invoked?** If the answer is "the same as failure", the vocabulary is one value short.

Cheap and mechanical, and it generalises the registration law's version (*"give 'nobody built the
caller' its own value"*) past registration to **every** propose/dispose boundary — resolution,
enumeration, extraction, dispatch.

The corollary is what makes it worth writing down: **you cannot detect this from inside the
component.** From in there, "I returned no match" is true and complete. It is only wrong from the
caller's side, where the difference between *asked and got nothing* and *never asked* is the
whole diagnosis — which makes this a sibling of
[`check-from-the-consumers-side`](check-from-the-consumers-side.md) as well.

## What this law does NOT say

**Not that every enum needs a null state.** The claim is narrower and it is about *provenance of
the absence*: when a value means "no result", it must be possible to tell whether a result was
sought. A closed vocabulary of *things that exist* (fiscal periods, personas, slot kinds) has no
such question to answer.

**Not that three is the right number.** Instance 3 has three outcomes at the provider and a
fourth at the consumer, because the provider genuinely cannot report a call that never reached
it. **The right number is however many distinct FACTS there are**, and the recurring mistake is
not undercounting in general — it is undercounting this one specific fact, every time.
