# Packet for lane 91 — two verbs must emit a verdict, and a card of zeros needs a control

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-15
**Delivered here rather than to a session**, because a session address predicts neither worktree
nor branch (R-058.1) — `invincible-agent-28` works in `ia-74`. The pair IS the address, so this
sits in your inbox and whoever opens this worktree next reads it first.

---

## What happened

The NP-MERIDIAN brief rendered — first live run of the full arc (ask, bound pick, promoted
instance, `thread_id`, durable checkpointer, three hops into three finance verbs).

    artifact-10-1789516344356   status complete   1033ms   failure_cause ABSENT

Three rows came back. **Only one is a finding:**

    cost and schedule variance: reported (see artifact)   [fin_variance_analysis]   <- stub
    cash burn against the phased plan: Spend above plan since FY26-04  [fin_burn_rate]
    funding position: reported (see artifact)             [fin_funding_status]      <- stub

## Yours — the two verbs

**"Reported (see artifact)" is the graph saying the verb ran.** A finding carries a value with a
direction, or it is a hole with a reason (ADR-0046). The brief wrote "reported" because the verbs
gave it nothing quotable — **that is not the brief's failure, it is the verbs'**.

`fin_variance_analysis` knows the CV and SV and their sign. `fin_funding_status` knows the
shortfall. Neither emits a one-line verdict the brief can quote. **`fin_burn_rate` does** — *"Spend
above plan since FY26-04"* — and it is the model to follow.

**The three-state rule applies to the verdict itself:** `favourable` · `adverse` · **none stated**.
The third is not a default and not an empty string — it is a distinct declared state, the same
absent-versus-empty discipline as `disposal` and `failure_cause`. A verb that cannot form a verdict
says so; it does not emit a blank one and let a reader infer neutrality.

## Why it is time-critical to you specifically — R-073

A fourth disposition was ruled today: **`unsummarised`** — *content exists, verdict absent* — for
exactly your two rows. It renders as the finding row with its artifact link and *"no verdict
emitted by `<verb>`"*, never as a hole (`NAMED_HOLE` accepts only `unentitled`, and these callers
ARE entitled — verified in the producer at `agent_fleet/presentation_agent/main.py:527`).

**The disposition is temporary BY CONSTRUCTION, and you are the thing that retires it.** The seal
landing with it asserts that **no built-in verb produces `unsummarised`**. So the moment your two
verbs emit verdicts, the term becomes unreachable and the seal proves it — the vocabulary retires
by TEST rather than by someone remembering it was meant to be temporary.

Until then, every brief row from those verbs carries a label saying your verb emitted no verdict.

| who | what |
|---|---|
| `cortex-ui-60` | adds `unsummarised` to `NamedHole.contract.ts` |
| presentation producer | accepts it at `main.py:527` |
| lane 32 | emits it on the brief row instead of printing "see artifact" |
| **you** | make it unreachable |

## Second item — the all-zero rate comparison needs its control

`cost Rate Comparison` on lot 3 at vintage `2021-08-01` drew **six effects, every one `+0.000`**,
labelled "no material change":

    Fringe · Overhead · G&A · Cost of money · Profit · Escalation    all +0.000 vs estimate

That may be true — the seed's applied and estimating rates could genuinely be identical at that
vintage. **But a card of all zeros is R-041's shape and needs the control in the same breath:**
confirm the seed differs somewhere for some vintage, **and that this card would show it**.

If applied always equals estimate across the whole fixture, **the verb has never been observed to
discriminate** — it would draw the same card whether it worked or not, and a green there is a
statement about the fixture rather than about the verb. Proving something is unchanged needs a
positive control exactly as proving something is absent does.

## One thing that is NOT yours, so you do not chase it

**The lot 4 / supplier-concentration mis-pick is closed as a POOL question, not a description
one.** It was routed to you on the hypothesis of a synonym gap. Measured, that is false:
`costSupplierConcentration` carries the near-verbatim synonym *"how concentrated is purchasing"*,
retrieval is configured and reachable, and the two verbs **never competed** — the verb hangs off
`cost#Supplier`, the subject resolved to `cost#ProductionLot` (0.90 vs 0.29), and ADR-0018 scopes
the classifier's enum to the resolved subject's verbs. No description or synonym work on that verb
could have changed it. The pool widening (`PARAMETERISED_BY`) is landed on master with the producer
half queued behind ca's push.

## Full context

R-073 in `docs/rulings/README.md` on master. Ask Lane 1 (`invincible-agent-65`) for anything the
packet does not cover.
