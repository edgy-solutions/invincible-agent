
---

## 2026-09-11 — AN ABSENCE ASSERTION IS VACUOUSLY SATISFIED BY A BROKEN PRODUCER

**RULED. Pair it with a presence assertion, or it asserts nothing.**

Proposed seal: *materialise the aitool asset against a fixture, then assert **zero edges
without `_tool_urn`**.* It sounds like the join asserted at the writer. It is satisfied by a
build where registration is **broken outright** — a writer that writes nothing writes no bad
edges, and the seal goes green on a dead producer.

**doc-tools-7f's pairing is the fix, and it states the 2026-06-12 property directly rather
than this defect:**

> **Two providers of the same verb must produce TWO edges, with distinct `_tool_urn` and
> identical `iri`.**

That fails in **both** directions — on collapse (one edge where there should be two) and on a
dead writer (no edges at all). The absence assertion alone covers neither honestly.

**AND THEY FLAGGED, UNPROMPTED, THAT THE PRESENCE ASSERTION DOES NOT GO RED UNDER THE DEFECT
MUTATION.** With two genuinely distinct URNs the old code also produced distinct keys, so it
**pins the property, not the bug**. Both pins are needed and neither substitutes for the
other: one catches the regression, the other catches the collapse. That is the join law
applied to the seals themselves — each asserts an endpoint, and only together do they assert
the relation.

**Same shape, already paid for:** the stage-balance check that read **zero events as
balanced**. Zero satisfies "ins equal outs" perfectly, and a pipeline that emitted nothing
passed a check written to prove it emitted correctly.

**The general form, for a lane about to write a seal:**

* *"there are no bad X"* is satisfied by *"there are no X"*;
* *"the counts agree"* is satisfied by *"both counts are zero"*;
* *"nothing was rejected"* is satisfied by *"nothing was submitted"*.

**Every absence claim needs a floor under the population it quantifies over** — and the floor
is not decoration, it is the half that distinguishes a working producer from a silent one.
See [[a-green-seal-can-be-green-for-the-wrong-reason]].
