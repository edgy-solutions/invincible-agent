# Ruling: two seed routes are CORRECT — and the real hazard is one layer in

**Date:** 2026-08-26 · **Lane:** 1 · **Status:** ruled; one item escalated to the eval agent

## The question

`/canvas/seed` and `/seed/portfolio_canvas` are both deployed and the client calls the first.
Raised as "two doors to one room" — the shape that ends with someone gating, changing, or
removing the wrong one. The lean offered was: make `/canvas/seed` canonical, deprecate or delete
the other.

## Ruling: KEEP BOTH. No change. Acting on that lean would remove a working adapter.

I raised this, so I am the one who has to say it was not the defect it looked like.

**It is an alias by DELEGATION, not by duplication** — the divergence risk that makes two doors
dangerous does not exist here:

```python
inner  = SeedPortfolioCanvasRequest(session_id="canvas-seed-" + uuid.uuid4().hex[:8])
result = await seed_portfolio_canvas(inner, http_request, current_user)
```

One implementation. The alias calls it. There is no second copy of the question list, the slot
order, or the sequencing to drift.

**Both rows are already declared**, and the gating manifest says so in the field built for
exactly this: `gate: "auth; delegates:/seed/portfolio_canvas -> /interview/stream per-ask cell
entitlement"`. The `delegates` class exists precisely so a route that forwards can be classified
as forwarding rather than re-justified from scratch.

**And they are NOT redundant — they do different things.** This is the part that makes "delete
one" actively wrong:

| route | what it is |
|---|---|
| `/seed/portfolio_canvas` | the IMPLEMENTATION. Holds the five questions, runs them in slot order, returns a **slot-aligned** array where a failed ask leaves a `null` hole |
| `/canvas/seed` | the CLIENT ADAPTER. Fixes `canvas_type`, mints a session id, and **strips the nulls**, because the client does `for (const id of artifactIds) addItemAuto(...)` and a null becomes a broken item |

Deleting `/seed/portfolio_canvas` would delete the slot-aligned answer. Deleting `/canvas/seed`
would hand the client an array with holes it cannot iterate. The adapter is not ceremony around
the implementation; it is a documented behavioural transform between two different contracts.

**What I would change: nothing in the routing.** One implementation, two declared surfaces, a
stated delegation. That is the shape this project asks for.

---

## The actual hazard, which is one layer in and worth more than the routing question

The eval agent flagged it inside the alias's own docstring, honestly and in full — and it is
**unresolved**:

> Stripping is therefore required by the receiver's contract, and it reintroduces the shift for
> PARTIAL seeds only: if the cost curve fails, site load lands in the cost-curve slot, every card
> is real, and nothing reports it.

Read that consequence again, because it is the seed's version of a defect this project has now
paid for four times:

**A partial seed composes a board that is WRONG AND PLAUSIBLE.** Every card is real. Every card
renders. Nothing errors. The anchor slot holds whatever survived, and the only way to know is to
have expected a different card there. The slot-aligned array was built specifically to prevent
this — "a shifted list would silently put the cost curve in the anchor slot and still look like
a working canvas" — and the strip at the adapter undoes that guarantee for exactly the case it
was built for.

**Neither layer is wrong on its own.** The implementation is right to keep holes; the client
genuinely cannot iterate them. The defect lives in the seam, which is where every defect this
week has lived.

### Why this matters TODAY, not later

The verification cascade is being run right now, and **step 3 is the seed**. If that run is
partial:

- five cards appear, all real, all rendering
- the anchor is whatever survived, not necessarily the timeline
- **the screen gives no tell at all**

The only signal is server-side, and it is a log line, not a response field:

```
canvas_seed: PARTIAL seed 4/5 — the returned list is compacted, so cards after the
failed slot shift up one. The board will look plausible and be wrong.
```

**Check it before trusting the seeded board:**

```bash
kubectl --context edge logs -n sandbox deploy/iagent-cortex-bff --tail=200 | grep -i "PARTIAL seed"
```

A clean run logs `seeded == total` (measured 5/5 in 17.7 min). Anything else means the board is
mis-slotted and any conclusion drawn from card POSITION is unsafe — including "the anchor
renders the timeline", which is a step-3 acceptance criterion.

### The open product question — the eval agent's to rule, not mine

Their docstring says it plainly and correctly declines to decide silently:

> Whether a partial seed should compose at all or refuse outright is a PRODUCT ruling, not mine
> to make silently at this layer.

Both options are defensible and they trade different things:

- **Refuse a partial seed** — the client already has a no-canvas path for an empty array. Honest,
  and costs a demo-day retry if one ask times out.
- **Compose, but carry the truth** — return `{artifact_ids, seeded, total}` and let the client
  render the gap as a gap. Keeps a partial board usable and makes the hole visible.

**My input, not my ruling:** the second preserves the property the slot alignment was built for —
absence stays representationally distinct from content — and it is the same answer this model
gives everywhere else (a cell never assessed is ABSENT, never level 0; a project with no capability
is `(none)`, never dropped). But the response contract is cortex's and the route is the eval
agent's, and a unilateral change here would put a third opinion into a two-lane seam.

**What I did instead:** wrote it down, and made sure whoever is looking at a seeded board today
knows the one command that tells them whether to trust its slot order.
