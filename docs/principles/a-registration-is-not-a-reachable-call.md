# The a-registration-is-not-a-reachable-call law

> **A declaration is a claim about what exists. A capability is a fact about a call that
> happens.** Between them sits a hop that has no ceremony, produces no artifact, and fails by
> silence — and the hop can be missing on *either* side of the registration.

Filed 2026-08-29 on two verified instances; **promoted to three the same day** when the third was
named and checked; **a fourth arrived 2026-08-30**, found by the detection move in *Instance 4 adds
the DETECTION move* below. The title names the commonest direction, not the whole family — see *the two
directions* below, because an instance nobody recognises as this law is an instance that gets met
as a novelty.

## Why the mistake is so easy to make

The registration is the loud half. It has a mint, a schema, a graph write, an ontology class that
must exist first, and a 422 if any of it is wrong. Getting it to succeed *feels* like completing
the capability — and it is genuinely most of the work.

**The hop is the quiet half, and it is the half that makes the capability exist.** It produces no
artifact and fails by *silence*: nothing 422s when nobody calls, and nothing 422s when the code
that would register is never run. So the reading error is not carelessness. It is that **the half
that looks like a milestone completed, and the half that has no milestone was never started.**

## The two directions, which is why the family kept being met as a novelty

| direction | the gap | reads as |
|---|---|---|
| **upstream** — the declaration never became a registration | the artifact exists; nothing publishes it, or the publishing code never runs | "we built that" — and the server has never heard of it |
| **downstream** — the registration never became a call | the registration is live and correct; nothing dispatches to it | "the provider is registered" — and no consumer can reach it |

Same reader's error in both: **treating the artifact as the capability.**

## The instances

| # | what was declared | the missing hop | direction |
|---|---|---|---|
| 1 | **`intent_catalog.yaml`** — slots for every verb | nothing **projects** it onto the graph the router reads. It is consumed by tests and eval runners only — *a catalog entry is not a registration* | upstream |
| 2 | **`mesh:enumerateInstances`** on Engine P — minted, ontology-classed, three-outcome, correct | **nothing in Engine O dispatches an enumerate** the way `/resolve` fans out a resolve. No caller exists | downstream |
| 3 | **`CANVAS_SEED`** in `assembleCapabilities(CORTEX_UI_CAPABILITIES)` — shipped in the bundle | the POST to `/register_frontend_capabilities` runs from a `useEffect` **gated on `auth.isAuthenticated`** (`cortex-ui` `src/App.tsx:103`, via `src/api/client.ts:635`). **Nobody had loaded the page**, so it sat registered-in-source and unregistered-in-fact for days | upstream |
| 4 | **`ProcessInterviewerV2`** — the SPO interview (ADR-0029 Slice 2), with the authorized-set menu and server-side `validate_pick`. Defined `restate_analyst/main.py:2384`, mounted `:3259` | **zero callers** in `src/`, `agent_fleet/`, `tests/` or the `cortex-ui` sibling. The gateway's only two interview calls both target **V1** — the BPMN-era interview V2's own docstring says it *supersedes*. **The supersession happened in the code and not on the wire** | downstream |

Instance 1 was caught by a correction inside ADR-0033, which retracted a clause naming a source
that did not exist. Instance 2 was caught by wiring the consumer and finding nothing to wire *to*.
Instance 3 was reported by the architect and **verified here against the sibling repo** rather
than taken on recollection.

### Instance 3 is what makes this a law rather than a server-side habit

> **THE MISSING HOP NEED NOT BE CODE.** In 1 and 2 the hop is a dispatcher somebody has to write.
> In 3 the hop is **a human loading a page** — the code was correct, shipped, and inert because
> the event that runs it had not happened.
>
> So the guard question is not *"did I write the caller?"* It is **"what causes the caller to run,
> and has that happened?"** A registration behind a lazy trigger — a page load, a first request, a
> cron that has not fired, a pod that has not restarted — is a registration that does not exist
> yet, and nothing in the code review will say so.

### Instance 3 also explains why searching for it failed — itself a property of the species

Instance 3 did not surface in a repo-wide grep **because it is in `cortex-ui`, not here.** The
declaration and the consumer sit in different repositories, which is exactly the boundary a
single-repo search cannot see across.

That makes this a sibling of [`check-from-the-consumers-side`](check-from-the-consumers-side.md)
rather than a restatement: that law is about *who the defect lands on*; this one is about *what a
declaration does not buy you*. Both are found by standing somewhere other than where the code was
written — and **both hide best at a repo boundary**, where "somewhere else" is also "not in my
`git grep`".

### Instance 4 adds the DETECTION move, which the first three only gestured at

Instances 1–3 were each found by accident of adjacency — someone happened to need the thing.
Instance 4 was found by a **question**, and the question generalises:

> **"Can I reuse this?"**
>
> It is the only ordinary engineering question that *forces* you to trace an actual call path.
> You cannot answer it from the module: you have to find who calls it, in order to copy them.
> **From the producer's side V2 looks complete — because it IS complete.** Nothing about reading
> the implementation reveals that nothing reaches it.

That is the operational tell for the whole family, and it is sharper than *"read from the
consumer's side"* — which is a posture, and easy to believe you are already in. The reuse question
is an **action** that puts you there involuntarily, and it has a definite answer.

Cheap mechanical form, and it is what turned up instance 4 in about a minute:

```
grep -rn "<TheThing>" src/ agent_fleet/ tests/ <sibling-repos>/src | grep -v vendored
```

Zero non-definition hits **is the finding**. Note `tests/` is listed to be *excluded from the
count*, not to be searched for reassurance: instance 1 was consumed by tests and eval runners
only, and *a catalog entry is not a registration.*

### AND THE CLAIM PROPAGATES THROUGH DOCUMENTATION, WHICH IS HOW IT SURVIVES REVIEW

Instance 4's most instructive property is not that it happened — it is how long it stood.

ADR-0033's Context reasons from *"widget interrogation **already shipped once** — the SPO
interview asks 'which subject did you mean' from a menu."* True of the module. **False of the
path.** That sentence was then repeated, in good faith, as an argument for why elicitation should
reuse the interview — and would have been built on.

> **A citation is not a call either.** Once a document asserts a capability, every later reader
> inherits the claim without the cost of checking it, and the assertion is *more* durable than the
> code because nothing recompiles it. **The unreachable thing in instance 4 is an ADR's own
> prior-art claim** — which means this law caught a document, an author, and a reader in one
> sentence.
>
> Practical consequence: when an ADR reasons from *"we already have X"*, that phrase is a
> **load-bearing factual claim** and deserves the same treatment as a measured number — verified at
> the wire, or written as *"X exists in the codebase; reachability unverified."*

## The guard, and it is not "remember to wire the caller"

[`naming-a-class-is-not-a-guard`](naming-a-class-is-not-a-guard.md) applies to this law as much as
to any other: writing it down prevents nothing. What works is making the **absence of the hop
observable at the consumer**, so the gap reports itself instead of presenting as a missing feature.

The `ask` disposition's handling is the worked example:

- the consumer takes the provider's address from **`ENUMERATE_INSTANCES_URL`, unset**, rather than
  constructing it — because inventing a provider's URL is the phantom-service-URL shape, and a
  guessed address fails as a *timeout* rather than as *nobody built this*;
- with no address it emits `free_text_reason: "no_provider"` — a **named** outcome from a closed
  set, sitting beside the provider's own `too_many` and `unsupported`;
- and a test asserts a degraded result **always carries a reason**, so silence cannot pass.

> ### THE GENERALISABLE MOVE
>
> **Give "nobody built the caller" its own value in the outcome vocabulary, distinct from every
> value the provider itself can return.**
>
> Then the gap is visible in logs, assertable in a test, and closing it is one line rather than an
> investigation.

Collapsing it into a provider-shaped answer is what makes the defect invisible: *"I do not
enumerate this"* and *"nobody asked me"* are different facts, and merging them is how **"nobody
built it" disguises itself as "nothing to offer"** — which is the sentence this project has now
paid for three times.

The tripwire-on-silence rule is the same principle one layer up: an ask with no menu must name its
reason from a closed set, because a menuless ask that cannot say why is indistinguishable from one
nobody thought about.

## What this law does NOT say

**Not that registrations are low-value.** They are what makes the caller possible and
provider-agnostic; the point is only that they are one of two halves.

**Not that every registration needs a caller today.** A provider registered ahead of its consumer
is a reasonable sequence — instance 2 is exactly that, and correctly so. What is not reasonable is
*believing the capability is available* because the registration succeeded, which is the reading
that costs a build its estimate.
