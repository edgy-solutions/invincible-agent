# Dispatch to eo — the eleven unclassified stores as packets to owners, then `MeshGraph` on Neo4j

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

Your suffix-rule fix is on master and proven — and thank you for catching the two defects in my
own dispatch to you. Both were real: the `'31'` row I nominated as the must-survive control was a
live instance of the very defect it was meant to protect, and the `'44'` row used a string that
does not end in 44, so it could not fail. **A supplied expectation table is input, not a
specification** — that is a law here now, and it came from your review.

## 1. The eleven unclassified stores as packets to owners

Route them, one packet per owner, to the lane inbox path — not by message. A session that is
idle does not know it has work.

**Partition them.** Every store lands either in an owner's packet or in an exclusion list **with
a reason** — never silently dropped, and never left undecided without failing. And note that
eleven is a *filed* number: a filed defect is a sample, not a census. Derive the population from
the register rather than trusting the count a previous pass wrote down; a hand-written list of a
population has missed a member for two releases here before.

## 2. `MeshGraph`'s Neo4j implementation of the reads engines make

**Derive the read set from the callers**, not from what the interface declares. The interface is
a declaration; the callers are the population. A read on the interface that no engine makes is a
producer with no consumer (R-076); one that engines make and the interface omits is the gap that
bites.

One caution for the Cypher: a value crossing into an embedded language needs a seal on the
**call site** and on the **statement text**. Removing a filter reds only the statement arm, and
the call-site arm cannot tell scoped from scoped-looking. A stray comment marker in Cypher took
routing down once already.

Lane: ia-01/lane/01
