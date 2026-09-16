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

---

# The data-class ADR — what the artifacts say, read before drafting

## §6.1 is stronger than the packet's summary, and it names its own measured cost

Verbatim, `ADR-0051` §6.1:

> **PRODUCERS WITH DIFFERENT REPRODUCIBILITY DO NOT SHARE A GRAPH.** Added 2026-09-14, because the
> obvious way to seed sandbox hazards — a TTL in the prime manifest — is wrong in a way that only
> shows up on somebody else's data.

| | graph | who writes it | what the prime does |
|---|---|---|---|
| **vocabulary** | `http://internal/{DOMAIN}` | this repo's manifest | **drops and re-lands** it every run |
| **instances** | `http://internal/{DOMAIN}_INSTANCES` | runtime producers | **never touches it** |

The cost is not hypothetical and §6.1 quotes it: an earlier glob over `http://internal/*` *"would
have wiped real extracted parts **on the very prime run meant to enable the pcn dogfood**."*

## THE ARGUMENT FOR THE ADR IS IN THE GAP BETWEEN §6.1's CLAIM AND THE MECHANISM

§6.1 says the split is *"enforced by the clearer, not left to discipline."* **Read the clearer and
the enforcement turns out to be conditional in a way §6.1 does not state.**

`setup/prime_databases.py:398`:

> THE DROP SET IS DERIVED FROM THIS FIELD. `clear_ontology_graphs()` computes
> `{f"http://internal/{e['domain']}"}` over this manifest, so a new domain becomes an eighth graph
> picked up automatically — no change to the clearer is needed, and none should be made.

Measured against the manifest today: **22 entries, 9 domains, and NO `_INSTANCES` domain among
them.** So an instance graph is safe from the clearer **because nobody has filed an instance
producer in the manifest** — not because anything refuses one. §6.1 identifies filing one as
precisely the tempting mistake, and the clearer cannot tell a vocabulary entry from an instance
entry: both are rows with a `domain`.

> **Reproducibility is currently asserted by ABSENCE FROM A LIST, and absence is the one state a
> derived population cannot distinguish from an omission.** A missing row and a row nobody wrote
> look identical — the shape this repo has now paid for in doc pages, in registry sites, and in a
> census that printed a complete-looking table.

**That is the ADR's load-bearing argument, and it comes from the artifacts rather than from the
dispatch: the class turns a negative into a positive.** Declared per graph, the clearer reads
`reproducibility: rebuildable` and drops what SAYS it can be rebuilt, instead of dropping what
happens to be listed. An instance producer filed in the manifest then fails at the declaration
rather than at somebody else's data.

## §6.1 already contains the discipline applied to `page_by_iri` tonight

> **The writer is therefore sequenced AFTER a walk that draws or names its own failure**, rather
> than built against an inferred requirement — which is the same refusal this ADR makes elsewhere
> about a key nothing has been shown to need.

Same law as *declared-but-uncalled comes out* and *no parameter until something can fill it*. The
data-class ADR should cite it rather than restate it: **a declaration with no witness is the shape,
and it has now appeared in a graph writer, an SDK Protocol operation, and a function parameter.**

## `fold, do not hand-run`

§6.1's seeding rule, quoted from `seed_mro_extension_runtime.py`: *"promoted to the gated
`ontologySeed` helm Job so a fresh cluster reaches working routing with **zero hand-run scripts**."*
Hand-seeded state no bootstrap reproduces is a fourth reproducibility state that the four-field
class must be able to express or refuse — **it is neither rebuildable nor stateful-authored; it is
stateful-and-unreproducible, which is the debt, not a class to legitimise.**
