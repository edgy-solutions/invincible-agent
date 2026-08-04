# Principle: a seal isn't done until it's been shown to bite

**Status:** Governing testing principle. Seals guarding critical
properties (exactly-one, no-laundering, redaction, deny-by-default)
cite this. Arrived at through the arc's long habit of distinguishing
asserted-green from proven-green for *system* claims; stated here once
as the same distinction applied to *test* claims.

## The tenet

**Green-on-first-run is the ceremonial-green trap.** A test that has
only ever passed is a claim, not a control: you have not observed it
*fail when the property it guards is broken*, so you do not yet know
it can. For a seal that guards a critical property, the seal is not
done until you have **made the property false and watched the seal go
red** — then restored the code byte-identical and watched it go green
again.

This is the exact sibling of the rule the arc already runs on for
systems: [[feedback_verification_must_fail]] ("a readback that always
logs green is worse than no readback") and
[[feedback_pre_written_fixtures_must_fail_first]] (red→green vs
ceremonial-green). Those govern *system* verification. This governs
*test* verification. A seal is a system claim about a test; mutating
the code under it is how you verify the test the way you'd verify any
other claim — by making it able to fail.

Mechanically: **mutation testing, one property at a time.** Break the
mechanism the seal exists to protect, run the seal, confirm it fails
with a diagnostic that names the real defect, revert, confirm green.
Not a coverage sweep — a targeted demonstration that *this seal*
catches *its* failure mode.

## The teaching example — the PCN dispatch driver's exactly-one seal

The dispatch driver (`pcn_driver.py`, `tests/test_pcn_driver.py`,
`d5b1d56`) guarantees a resolved disposition produces **exactly one**
persona-queue task and **exactly one** graph-state stamp, even across a
crash between the two writes. The seal is a two-direction
failure-injection: kill after each write, replay, assert exactly-one.
Both directions passed on first run. That is precisely when the trap is
live — so each was mutated:

- **Defeat the cross-invocation dedup marker** (drop the early
  `return prior`) → `test_second_invocation_same_key_is_noop` goes red:
  `(2, 2) != (1, 1)`. The marker earns its place.
- **Un-journal the mint** (call `_mint_dispatch_task` directly instead
  of inside `ctx.run`) → the **write_state direction** catches the
  double-mint on replay (`task minted 2x`) that the **mint_task
  direction misses**. One direction alone would have shipped the bug.

That second mutation is the reason the seal is *two-direction*, and it
is the general lesson: **a single crash point can leave a whole class
of convergence bugs invisible.** When a seal asserts a property that
can break at more than one point in a sequence, injecting the fault at
only one point is itself a ceremonial-green — the seal looks
thorough and tests one thing. Enumerate the fault points; inject at
each.

Both mutations were reverted and the driver confirmed byte-identical
before the commit — "proven to bite, two directions, reverted
byte-identical" is the provenance a future reader needs to trust 8/8
green. Put that sentence in the commit message; the mutation story is
part of the seal, not a private step.

## The count that matters is not refusals — it is catches from attacking your own green

The human form of the rule the mutations mechanize, and the reason
this practice is not optional for load-bearing seals.

2026-08-03, mid-migration: a grants guard was written, run, and came
back green. Green was *correct* — and the guard was still wrong. It
tested for the new audience key by SUBSTRING, and both audience names
also appeared in the `reason:` PROSE of the neighbouring entry. A
`reason` line is not a comment, so the check would have passed on a
**sentence about the key** while the key itself was gone. The bug
surfaced only from asking *how would I make this fail?* — not from
the run, which was green, and not from review, which had just
credited the same author with avoiding exactly this class one message
earlier.

Two things generalize:

- **Prose is not a declaration.** When a guard reads a structured file,
  assert on the STRUCTURE (a mapping key: starts with the prefix, ends
  with the colon), never on a substring that documentation, a comment,
  or a `reason:` string can satisfy. A file that honestly records its
  own history will contain every name the guard forbids.
- **A green run is not evidence about the guard; it is evidence about
  the current inputs.** The only thing that tests the guard is an
  input built to defeat it. So the question after green is never
  "does it pass?" but "what would slip past?" — and the answer is
  found by writing that input, not by reasoning about it.

Knowing the rule does not confer immunity to the class. The author
here had the rule, had just been praised for applying it, and
reintroduced it inside the same session — which is the argument for
mechanizing the check rather than trusting the discipline. **Attack
your own green; the catch comes from there or it does not come.**

## When this applies

Not every test. The cost (mutate, run, revert) is justified for
**seals that guard a property whose silent failure is expensive and
invisible** — the ones the arc already treats as load-bearing:

- **Exactly-one / idempotency** — a double-effect looks identical to a
  single effect until you count. (the driver seal)
- **No-laundering / carry-forward** — an unverified provenance that
  rides an automated lane leaves no trace at the point of laundering.
- **Redaction / deny-by-default** — a gate broken in *allow* is
  invisible in the happy path; a gate broken in *deny* is invisible
  entirely ([[feedback_broken_closed_hides_brokenness]]).
- **Conservation / honest-funnel** — a bucket that silently drops
  items still sums plausibly.

For these, "the test passes" is not the finish line. "I made it fail
and it did" is.

## Scope discipline

This is a testing principle, not a mandate to mutation-test the suite.
It names the bar for seals that guard critical invariants, and it names
the two-direction lesson so future seals over *sequenced* properties
enumerate their fault points instead of injecting one and calling it
covered. If applying it turns into chasing coverage numbers, it
overshot — the job is to make each critical seal *demonstrably able to
fail*, once, on record.
