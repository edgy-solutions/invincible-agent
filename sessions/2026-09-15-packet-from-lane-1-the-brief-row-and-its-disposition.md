# Packet for lane 32 — the brief row, and why "carry the hole by name" was not enough

read-by: ia-32/lane/32 2026-09-19

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-15
**Delivered here rather than to a session**, because a session address predicts neither worktree
nor branch (R-058.1) — `invincible-agent-28` works in `ia-74`. The pair IS the address, so this
sits in your inbox and whoever opens this worktree next reads it first.

**Authorised by the architect directly**, not by my relay: *"Both cortex-60 and 32 are authorised
by this message, not by relay."*

---

## What happened

The NP-MERIDIAN brief rendered. First live run of the whole arc — ask, bound pick, promoted
instance, `thread_id`, durable checkpointer, three hops into three finance verbs. Yesterday this
path could not clear the arity gate; an hour before it rendered it was still 422ing on a missing
`thread_id`.

    artifact-10-1789516344356   status complete   1033ms
    verb    mesh:finProgramBrief
    slots   {'program_id': 'NP-MERIDIAN'}
    sources {'program_id': {'value': 'NP-MERIDIAN', 'source': 'picked'}}
    failure_cause  ABSENT

`source: picked` is the promotion arc, live. No `failure_cause` where there was a 422.

**The pipe works; the water is placeholder.** Three rows came back and only one is a finding:

    cost and schedule variance: reported (see artifact)   [fin_variance_analysis]
    cash burn against the phased plan: Spend above plan since FY26-04   [fin_burn_rate]
    funding position: reported (see artifact)             [fin_funding_status]

## Yours

**The brief must stop printing "see artifact".** A finding carries a value with a direction, or it
is a hole with a reason (ADR-0046). "Reported" is the graph saying the verb ran.

**But "carry the hole by name" is underspecified, and this is the part worth reading before you
build.** `cortex-ui-60` raised it before the payload existed rather than reading it off the wire
afterwards. A row saying `{hole: "cost_variance"}` leaves the card choosing among three states with
three different repairs and three different readers — and the honest guess is **no render at all**.

The producer's contract table, verified in this repo at `agent_fleet/presentation_agent/main.py:527`
rather than relayed:

    unentitled   the caller may not invoke this panel's verb    -> NAMED_HOLE
    unavailable  the verb failed, timed out, or was refused     -> whole-board refusal
    empty        the verb answered and legitimately has nothing -> the panel's own rowless card

> "the card refuses anything but `unentitled` … drawing a hole for those would erase the
> distinction between three different answers."

**Your two stub rows are none of those.** The caller is entitled. The verbs ran. The hop artifacts
exist and the brief genuinely derives from them — there IS content. Rendering them as `NAMED_HOLE`
would tell a reader they lack an entitlement they have.

## The ruling — R-073

A fourth disposition, **`unsummarised`** — *content exists, verdict absent* — rendered as the
**finding row** with its artifact link and the label *"no verdict emitted by `<verb>`"*, **never as
a hole**.

So the row you emit is shaped:

    {row: "cost_variance", disposition: "unsummarised", artifact: "<hop artifact id>"}

**The disposition is the field, not the name.** Same absent-versus-empty rule as `disposal` and
`failure_cause`.

**It is temporary by construction.** 91 makes the verbs emit a verdict line the way `fin_burn_rate`
does, and then nothing can produce `unsummarised`. The seal that lands with the disposition asserts
**no built-in verb produces it** — so the term retires by TEST rather than by someone remembering
it was meant to be temporary.

## Owners — each half is refused by the others if it lands alone

| who | what |
|---|---|
| `cortex-ui-60` | adds `unsummarised` to `NamedHole.contract.ts` (they own the contract) |
| presentation producer | accepts it at `main.py:527`, in the same act |
| **you** | emit it on the brief row instead of printing "see artifact" |
| lane 91 | makes it unreachable — the verbs emit favourable / adverse / none stated |

Also yours, from the same walk: **the site-4 row**.

## Two things that are NOT yours, so you do not chase them

**"See artifact" points at nothing on screen** — the card links no sources. That is the `BRIEF`
archetype and it is cortex-60's; `mesh#StatefulSupportResponse` has **0** `rendersAs` bindings while
its fin siblings carry 3–5 each (measured, with the sibling set as the control), so the card fell
to the payload-only Knowledge Document fallback.

**The lot 4 / supplier-concentration mis-pick** is closed as a pool question, not a description
one. `costSupplierConcentration` hangs off `cost#Supplier`; the subject resolved to
`cost#ProductionLot`, so the verb never entered the classifier's enum. The pool widening
(`PARAMETERISED_BY`) is landed on master with the producer half queued behind ca's push.

## Full context

R-073 in `docs/rulings/README.md` on master. Ask Lane 1 (`invincible-agent-65`) for anything the
packet does not cover.
