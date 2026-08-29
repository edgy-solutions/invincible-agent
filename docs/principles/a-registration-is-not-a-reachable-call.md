# The a-registration-is-not-a-reachable-call law

> **Declaring a capability in one place does not make it callable from the place that needs it.
> A registration is a claim about what exists; reachability is a fact about a caller.**

Filed 2026-08-29 on **two verified instances**, following the precedent of
[`check-from-the-consumers-side`](check-from-the-consumers-side.md), which was filed the same way
and for the same reason: the pattern is the kind that produces a third quietly. A third is
suspected and is recorded below as **unverified**, deliberately not counted.

## Why the mistake is so easy to make

The registration is the hard, visible, ceremonious part. It has a mint, a schema, a graph write,
an ontology class that must exist first, and a 422 if any of it is wrong. Getting it to succeed
*feels* like completing the capability — and it is genuinely most of the work.

**The caller is the boring part, and it is the part that makes the capability exist.** Between a
registered provider and a working feature sits a dispatch: something that looks the provider up
and calls it. That hop has no ceremony, produces no artifact, and fails by *silence* rather than
by error — nothing 422s when nobody calls.

So the reading error is not carelessness. It is that **the loud half completed and the quiet half
was never started**, and the loud half is the one that looks like a milestone.

## The instances

| # | what was declared | where it was assumed reachable | what was actually missing |
|---|---|---|---|
| 1 | **`intent_catalog.yaml`** — slots for every verb | the router, which "should" know a verb's parameters | the catalog is read by **tests and eval runners only**. *A catalog entry is not a registration* — nothing projects it onto the graph the router reads. |
| 2 | **`mesh:enumerateInstances`** on Engine P — the option source for `ask` | the supervisor, building an elicitation menu | **nothing in Engine O dispatches an enumerate** the way `/resolve` fans out a resolve. The provider is registered, minted, ontology-classed and correct. No caller exists. |

Instance 1 was caught by a correction inside ADR-0033, which retracted a clause naming a source
that did not exist. Instance 2 was caught by wiring the consumer and finding there was nothing to
wire *to*.

**Both were found by reading from the caller's side**, which is why this law is a sibling of
`check-from-the-consumers-side` rather than a restatement of it: that law is about *who the defect
lands on*; this one is about *what a declaration does not buy you*.

### Suspected third, NOT counted

A frontend-capability instance is believed to exist in this same month. **I could not locate it**
and it is recorded here as an open thread rather than folded into the count, because a law filed
on two verified instances plus one remembered is a law resting on a neighbour of its evidence.
The nearest in-repo candidates, neither of which I would claim without checking:

- `[[broker-advertises-unminted-credential]]`'s sibling finding — **namespace-local hostnames
  relayed to readers in other namespaces**. An advertised address that does not resolve from the
  consumer is arguably the same shape wearing DNS.
- `[[disposition-contracts-do-not-export-what-composition-needs]]` — the disposition vocabulary is
  *"real and complete SERVER-side"* and the frontend contracts do not express it. Closer to a
  composition gap than a reachability one.

If either is confirmed, add it and delete this section.

## The guard, and it is not "remember to wire the caller"

`[[naming-a-class-is-not-a-guard]]` applies to this law as much as to any other: writing it down
prevents nothing. What works is making the **absence of a caller observable at the consumer**, so
the gap reports itself instead of presenting as a missing feature.

The `ask` disposition's handling is the worked example:

- the consumer takes the provider's address from **`ENUMERATE_INSTANCES_URL`, unset**, rather than
  constructing it — because inventing a provider's URL is the phantom-service-URL shape, and a
  guessed address fails as a *timeout* rather than as *nobody built this*;
- with no address it emits `free_text_reason: "no_provider"` — a **named** outcome from a closed
  set, sitting beside the provider's own `too_many` and `unsupported`;
- and a test asserts that a degraded result **always carries a reason**, so silence cannot pass.

> **The generalisable move: give "nobody built the caller" its own value in the outcome
> vocabulary, distinct from every value the provider itself can return.** Then the gap is visible
> in logs and assertable in tests, and closing it is one line rather than an investigation.

Collapsing it into a provider-shaped answer is what makes the defect invisible: *"I do not
enumerate this"* and *"nobody asked me"* are different facts, and merging them is how an unbuilt
hop disguises itself as a substrate limitation.

## What this law does NOT say

**Not that registrations are low-value.** They are what makes the caller possible and
provider-agnostic; the point is only that they are the first of two halves.

**Not that every registration needs a caller today.** A provider registered ahead of its consumer
is a reasonable sequence. What is not reasonable is *believing the capability is available*
because the registration succeeded — which is the reading that costs a build its estimate.
