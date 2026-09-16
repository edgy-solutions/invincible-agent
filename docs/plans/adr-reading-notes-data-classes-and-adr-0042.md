---
id:         adr-reading-notes-data-classes-and-adr-0042
status:     in-flight
owner:      invincible-agent-f3 — ia-5f / lane/5f
blocked-on:
trigger:
closed-by:  both drafts on lane/5f for review
repo:       invincible-agent
summary:    Source reading for the two dispatched ADRs — data classes (ours) and OpenDDIL ADR-0042. Citations verified against the documents that actually registered each claim, with two corrections to the dispatch packet and one to my own earlier correction.
---

# Reading notes — data classes, and OpenDDIL ADR-0042

**WRITTEN BECAUSE A READING THAT EXISTS ONLY IN ONE SESSION IS A CONVERSATION, NOT A RECORD.** The
drafts come after the engine artifact; the reading happens now; and the gap between the two is
exactly where a verified citation turns back into a remembered one.

**Every claim below carries the document that REGISTERED it**, not the document that mentions it.
The dispatch packet blurred that twice and my own first correction blurred it once — see
§"Citations that move".

## Citations that move

### 1. Sanitization is ADR-0037's registered gap — and ADR-0040 does point at it

My first correction said sanitization *"is not in ADR-0040's gap list; it comes from ADR-0037
VE-7."* **The first half is right and the second half was too clean.** ADR-0040's own Related
section carries:

> **ADR-0037 VE-7** — sanitization obligations that follow durable local custody of operator
> actions.

So ADR-0040 **names the obligation and does not register the gap**; ADR-0037 registers it, as one
it *creates* rather than inherits. The precise form for ADR-0042: sanitization is an obligation
ADR-0040 §7's custody *incurs*, whose gate is VE-7's open row. Citing it to ADR-0040's gap list
would have been an invention; citing it to ADR-0037 alone drops the link that makes it in scope.

### 2. `asserted-locally-unconfirmed` is ADR-0040's, not ADR-0035's

The packet's reading list says *"ADR-0035 — basis classes, including `asserted-locally-unconfirmed`."*
**Reading ADR-0035 does not find it — the string is absent from that file.** ADR-0035 carries *the
six claim classes*; ADR-0040 §3 is what extends them:

> A locally-raised action is **intent the system of record has never seen and may reject.** It
> renders in its own basis class per ADR-0035 — `asserted-locally-unconfirmed`, which is neither
> *measured* nor *derived* — and it **must never present as an accepted transaction.**

ADR-0040's Related section states the direction outright: *"ADR-0035 — the basis classes §3
extends with `asserted-locally-unconfirmed`."* **The class is 0040's contribution to 0035's
taxonomy**, so a reader sent to 0035 for it finds a taxonomy with a hole where they were told the
answer was.

## Anchors for ADR-0042, verbatim

**Custody attaches to §7 and needs no new principle:**

> **OpenDDIL holds intent durably and authoritatively as intent. It never holds the transaction.**

Local authority over *what happened here*; central authority over *the record*. §7 states the
maintainer's action is *"a real, durable, authoritative fact about the site"* that *"remains a
**request** with respect to the stock balance until the authority says otherwise"* — two objects,
and *"conflating them is precisely how a correlation layer becomes a second system of record."*

**Retention is already half-ruled in Limits**, and the packet was right that it is:

> **Reconciliation outcomes persist on the intent permanently.** An intent that reconciles
> successfully **keeps its outcome record**; it is not discarded on success.

with the reason stated: *"the sequence raised → accepted is the only evidence the offline path
worked"*, and *"it is the default behaviour of most queue implementations, so it must be stated."*

**Severance outlasting retention has a template rather than needing a new one.** Limits' degraded
-mode paragraph is the shape:

> Recorded as a degraded mode so a deployment can choose it knowingly, rather than as the expected
> case that sets the ceiling for everyone.

**The scope is gaps 3 and 4 of ADR-0040's "What this ADR did not establish"**, verbatim: *"Storage,
retention and queue mechanics"* and *"Multi-tier intent"*. Gaps 1 and 2 — the action vocabulary and
the verb set — are excluded by that ADR's own text (*"both are derived from the action vocabulary,
so neither can be designed before it exists"*), and the dispatch's "Do not" agrees.

## VE-7, and the shape it shares with our own laws

VE-7's gate binds **at egress** — *"the moment an artifact leaves the workspace"* — and is *"a step
in the procedure that produces the artifact rather than a separate discipline someone remembers."*
Three reasons it cannot be a post-hoc sweep, all stated: a recording cannot be redacted after
delivery; rewriting history does not undo a leak; an external reader's copy is beyond recall *"by
definition, because being read by someone else IS its purpose."*

**And what is OSS-visible is the RULE, not the pattern list**, because *"publishing an enumeration
of what a sanitizer matches"* is itself an instance of the shape VE-7 names:

> **the apparatus built to manage sensitive material becomes the exposure**, because attention sits
> on the artifact being protected rather than on the protecting… *the control describes what it
> protects*.

**That is the same family as this repo's own instrument laws**, arriving from the security side:
`the instrument and the subject share a surface` (a check flagging its own explanation) and
[`a search by name finds prose about the name`](../principles/a-search-by-name-finds-prose-about-the-name.md)
(a search matching other people's explanation). VE-7's version is the costliest of the three,
because the surface they share is a leak rather than a false result.

**For ADR-0042 this makes the sanitization section short and derived**: intent replicated across a
tier boundary is an egress, so the gate binds at replication rather than at review; the rule is
stated publicly and the patterns are not.

## Still to read

- ADR-0031 + the 2026-09-08 addendum — converged node, state-versus-knowledge, policy modules and
  subject namespace
- ADR-0035 in full — the six claim classes, for what `asserted-locally-unconfirmed` extends
- ADR-0029 — releasability labelling (feeds the data-class ADR's fourth field)
- AUDIT-2026-08-08 — severance-tolerance inventory
- Ours: ADR-0051 §6.1, the prime's clearer invariant at `setup/prime_databases.py`, ADR-0034,
  ADR-0047

**The data-class ADR's population is PROVISIONAL and must say so.** Its input is the eo lane's
fleet-wide write census; until that lands the population is derived from the four known write
paths (registration, artifact writer, human tasks/grants, doc-tools ingest) and is **a sample
wearing a census's clothes** unless labelled.
