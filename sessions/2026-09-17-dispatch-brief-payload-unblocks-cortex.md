# Packet for lane 32 — the BRIEF payload, and it unblocks cortex-60

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-17. **Architect's dispatch, relayed — for the ruling go
to them.** Delivered to the worktree/branch pair per R-058.1.

---

## Your three

1. **The BRIEF payload shape with `unsummarised` rows and artifact links** — *so cortex-60 has a
   real artifact to build against.* **This is first because it unblocks another lane.**
2. **The second-process resume seal run green against the real database.**
3. **A third graph chosen to exercise `timed_out`.**

## Item 1 — what the payload must carry, and why cortex-60 is waiting rather than building

They have refused to build the BRIEF archetype against a shape described in a message, and they
are right to: they will build against **the first artifact that actually carries it**. So your
payload is the unblocking artifact, not a schema doc.

**R-073 ruled the disposition, and the disposition is a FIELD, not a name.** A row carries:

    {row: "cost_variance", disposition: "unsummarised", artifact: "<hop artifact id>"}

**`unsummarised` — content exists, verdict absent.** It renders as the **finding row** with its
artifact link and the label *"no verdict emitted by `<verb>`"*, **never as a hole.**

**Why not a hole, measured rather than asserted:** `NAMED_HOLE`'s contract accepts only
`unentitled`, and the producer now enforces that rather than describing it
(`presentation_agent/main.py`, `_HOLE_DISPOSITIONS`). Drawing `unsummarised` as a hole would tell
a reader they lack an entitlement they hold — the one error on that surface that cannot be taken
back.

**The vocabulary, as declared:**

    unentitled    the caller may not invoke this panel's verb    -> NAMED_HOLE
    unavailable   the verb failed, timed out, or was refused     -> whole-board refusal
    empty         the verb answered and legitimately has nothing -> the panel's rowless card
    unsummarised  content exists, verdict absent (R-073)         -> the FINDING row

**`unsummarised` is temporary by construction.** 91 makes the verbs emit a verdict line the way
`fin_burn_rate` does, and then nothing can produce it — the seal landing with the disposition
asserts **no built-in verb produces `unsummarised`**, so the term retires by test rather than by
somebody remembering it was meant to be temporary.

## The artifact link is the half that makes it a brief

**ADR-0046's lineage is currently invisible.** The NP-MERIDIAN brief derives from three hop
artifacts that genuinely exist, and the card links none of them — *"see artifact"* points at
nothing on screen. Three rows, each a finding or a hole, **each opening its source artifact**.
That link is what makes it a brief rather than three sentences.

The measured baseline, so you know what you are replacing:

    artifact-10-1789516344356   status complete   1033ms
    components: 1               archetype KNOWLEDGE_DOCUMENT  (the payload-only fallback)
    provenance: "no registered capability's contract is satisfied by this payload"

`mesh#StatefulSupportResponse` has **0** `rendersAs` bindings against 3–5 on every fin sibling —
that binding is cortex-60's half.

## R-075, ratified today, and it governs your payload

> **If a message string enumerates anything, the enumeration is a field.**
> *A card can build prose from data and cannot reliably recover data from prose.*

Three instances in one night. The one that cost nothing was caught **before the payload existed** —
which is exactly the position you are in now.

---

Fleet: master `0fb94c7`, deployed `cfa3f0d` until this window's roll. A FAILED artifact now always
records a cause at the one exit every route passes through. **Run on the declared environment** —
`uv sync --locked --extra agent-fleet`; system python reports ~40 failures that measure the runner.

Ask Lane 1 (`invincible-agent-65`) for anything this does not cover.
