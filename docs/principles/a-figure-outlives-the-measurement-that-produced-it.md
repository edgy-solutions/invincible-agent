# A figure outlives the measurement that produced it

> **A specific number reads as measured even when it is stale — and precision makes it MORE
> trusted, not less.**

**RULED 2026-09-11**, from `invincible-agent-91`'s catch of a stale docstring that had already
propagated into a draft ADR, and the mechanism `invincible-agent-5f` named for why it propagated.
Companion to [`a-green-seal-can-be-green-for-the-wrong-reason`](a-green-seal-can-be-green-for-the-wrong-reason.md):
that one is about a check answering a different question; this one is about a **written claim**
outliving the state that made it true.

## The tenet

A number with a decimal tail **looks like the output of a measurement rather than the memory of
one**. Sitting beside working code, it is authenticated a second time — the reader infers that
whoever wrote the code also checked the number, recently. So the most concrete-looking sentence in
a document is the one least likely to be re-derived, **and it is the one most likely to be stale**,
because prose does not move when code does.

**None of the instances below were careless. Every one was correct when written.**

## The instances, all from one week

| the claim | true when written | what moved |
|---|---|---|
| a seal docstring citing `1662607.7097505666` as proof float and Decimal paths differ | yes | the row floats were **quantized to the cent two commits later**, making both paths agree. Two mutations then survived. Corrected in `e063e02` |
| an exemption reading *"delete this entry when your case lands"* | yes | the case landed **in a different file**, so the entry needed AMENDING, not deleting |
| a runbook index row placing `DERIVED_BINDINGS` in `cortex-ui` | yes | it moved. Readers were sent to the wrong repository |
| a dispatch instructing *"expect red until the prime"* in a commit message | yes | that commit's seals were **green** |
| *"26 occurrences"* of a symbol, quoted three times in one argument | no — 26 was LINES | `grep -c` counts lines; two lanes then agreed loudly about different quantities |

The last is the same defect one step earlier: a figure that was never what its unit claimed.
See [`name what the number counts`](a-green-seal-can-be-green-for-the-wrong-reason.md).

## The defences

**RECORD THE COMMAND, NOT THE FIGURE.** A number is true at one commit and rots silently; a
command is re-runnable and its answer moves with the tree. Where a figure must be quoted, quote it
**with the command and the date** so a reader can tell a stale number from a changed system.

**REVIEWING? RE-DERIVE THE MOST CONCRETE-LOOKING SENTENCE.** Not the one that sounds shakiest —
the one that sounds most measured. It is the one nobody else will check.

**SCOPE A REVIEW BY WHOSE TREE THE CLAIM DESCRIBES, not by how plausible it sounds.** The gate
that caught the instance above was five claims singled out *because they were about another
lane's code*, not because any of them looked doubtful. Plausibility is exactly the signal that
fails here, since every one of these claims was true once.

**AND A CORRECTION REPEATED ON TRUST IS THE SAME DEFECT AS THE CLAIM IT CORRECTS.** When a
reviewer hands you a fix, verify it against the tree before rewriting on it. Otherwise their
correction arrives **exactly as pre-authenticated as their error** — same author, same apparent
recency, and now with the added authority of having caught something.

## What it costs to get wrong

The docstring instance was **one review from being published in an ADR**, where it would have
become a correctness result the Decimal work had not earned. The figure was the most concrete
thing in the draft, which is precisely why it was the most dangerous: it needed no argument, and
it invited none.
