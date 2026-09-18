---
id:         adr-reading-notes-data-classes-and-adr-0042
status:     in-flight
owner:      invincible-agent-f3 — ia-5f / lane/5f
blocked-on: both drafts on lane/5f awaiting review
trigger:
closed-by:
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

## ADR-0034 — and WHICH ADR-0034 is a citation that moves, the third

The packet's reading list puts ADR-0034 **"on our side"**. Our ADR-0034 is
`trust-lifecycle-admission-policy-decision-records-autonomous-path` and **does not contain the
word "propagating"**. The propagating/terminal typing is **OpenDDIL's** ADR-0034,
`tier-analytics-are-deployment-configuration`, which is also what ADR-0040's own Related section
means when it cites *"ADR-0034 — propagating-vs-terminal typing, which §5 reuses for writes."*

**Both are plausibly in scope and for different halves**, so this is an ambiguity rather than an
error: ours bears on authority location and decision records for the data-class ADR; OpenDDIL's is
the typing ADR-0042 inherits. **Two repos, one number, and a reading list that does not say which
— the fleet already knows this shape from `engine-f` the prose name versus `engine-f` the
component.** Both drafts should cite repo-qualified.

### The typing, verbatim, and the sentence that transfers

> - **Propagating** — associative/algebraic, safe to emit upward: `count`, `sum`, `min`, `max`,
>   `worst-of`, `distinct`, `mean-via-(mean,count)`.
> - **Terminal** — lossy, valid only at the point of presentation: `top-N`, percentile snapshots.
>
> **The config schema rejects a terminal operation on any stream marked for upward emission.**

and the line that is the whole argument for a declared class, already written one repo over:

> `top-N` becomes what it always was: a presentation-layer operation. The truncation bug becomes
> **unwritable** rather than merely audited-for — **the difference between "we checked" and "the
> system won't let you."**

**THAT IS THE ENFORCEMENT FRAMING THE DATA-CLASS ADR SHOULD BORROW RATHER THAN INVENT.** Our
argument is the same one: a cross-boundary write becomes *unwritable* because the interface's
signature carries the class, not *audited-for* because someone reads the diff. And the four-field
class's **sync obligation** (none / flush-up / mirror-down / write-back) is the direct analogue of
propagating/terminal — a typing of what may cross a boundary, and in which direction.

**One more sentence worth stealing:** *"The audit's classification table is the seed of this type
table."* That is exactly the move being asked of §6.1 — a table in prose becoming a type the schema
enforces — and it means the data-class ADR is not inventing a mechanism but repeating one that has
already been ratified next door.

## ADR-0047 (ours) — the sync-obligation field's hardest value is already refused

§4 gives the **mirror-with-provenance** shape in one sentence, and it is the same shape
`mesh:DocPage` arrived at independently — *locator plus hash, never a second copy*:

> the recipient holds the content and iagent holds the thin reference — the `PublishedArtifact`
> records the locator and the hash, never a second copy of what was sent. Rule 1's *purpose*
> (iagent must not be able to present stale content as live) is preserved exactly; only the party
> holding the content changes.

And the field value `write-back` is **already refused for the export case, with its reason**:

> **NON-GOAL, stated with its reason: there is no write-back path.** … it is a **different
> decision** with its own identity, authorization, provenance and admission questions … **It must
> arrive as its own ruled decision, never as scope creep on an export.** A write-back bolted onto a
> read-only package is an unauthenticated external write path into a governed store.

ADR-0040's `of-record-elsewhere` says the same from the other side — *"a mirror with provenance and
a write-back contract, never the authority."*

> **SO `write-back` IS A VALUE THE CLASS CAN CARRY AND NOBODY CAN SET CASUALLY.** Two ratified ADRs
> agree that instantiating one is its own decision. The data-class ADR should say that declaring
> `sync: write-back` on a store REQUIRES a ruling naming the authority, the submitter's identity and
> what an accepted correction changes — otherwise the field becomes the scope creep ADR-0047
> refuses, wearing a schema.

## ADR-0029 — releasability, and §7 is the rollout the data-class ADR needs

**§3: labels are provenance, stamped at ingress, never re-derived.** Same doctrine as our own
"provenance is a field never a join". And `policy_label` is **reserved, not defined**:

> A structured confidentiality label is a real requirement for some programs and a premature
> abstraction for OpenDDIL today; reserving the field number keeps the door open without shipping a
> shape we would have to guess at.

**That is the honest option for our fourth field.** Releasability can be *reserved* rather than
invented, citing this reasoning, instead of our ADR shipping a taxonomy it would be guessing at.

**§7 IS THE ONE THAT CHANGES OUR ROLLOUT, and it is the hazard our clearer inherits exactly:**

> Deny-unlabeled is only safe once every row is labelled. Turning it on against a partially
> -labelled dataset **silently blanks legitimate data, and the failure mode is indistinguishable
> from correct enforcement — an operator sees an empty screen either way.**

Our version: a clearer that drops what declares itself rebuildable, run against a partially
-declared manifest, **keeps** the undeclared instead of dropping it — the mirror failure, equally
indistinguishable. So the sequencing is theirs, verbatim: **label first, enforce second, never the
reverse**, with a hard gate that must return zero before the clearer reads the class in that
environment, and the census's *"refuses an unclassified store"* is what makes that gate real.

And the distinction that keeps it honest:

> Entities without a derivable national origin … receive a default from deployment configuration —
> so that **"unlabelled" means "genuinely unknown", not "we haven't got to it yet"**.

**Plus the constraint on the gate itself, which is our own derive-the-population law ratified next
door:**

> The gate must enumerate the labelled tables from `information_schema` at run time. **It must never
> carry a hardcoded list.**

## Where the data-class ADR now stands before a word is drafted

**Almost every mechanism it needs is ratified precedent, in someone's words rather than mine:**

| the ADR needs | already ruled, cite it |
|---|---|
| a prose table becoming an enforced type | OpenDDIL ADR-0034 — *"the audit's classification table is the seed of this type table"* |
| enforcement that refuses rather than audits | OpenDDIL ADR-0034 — *"we checked"* vs *"the system won't let you"* |
| the reproducibility split itself | ADR-0051 §6.1, with its measured cost |
| why a declaration beats absence-from-a-list | the clearer's own derived drop set, and three instances this week |
| the hardest sync value | ADR-0047 §4's refusal + ADR-0040's `of-record-elsewhere` |
| releasability without inventing a taxonomy | ADR-0029 §3's *reserved, not defined* |
| the rollout, and its indistinguishable failure | ADR-0029 §7 — label first, hard gate, derived population |

**What is genuinely new is only this:** the four fields as one declared object, carried in three
write interfaces' signatures, so that crossing a boundary is unwritable rather than reviewed.

## ADR-0031's addendum — the same line, drawn a third time

> **OpenDDIL holds the STATE of the world.** … observation and derivation over a fleet that exists
> right now.
> **The reasoning plane holds KNOWLEDGE about the world.** … true of a platform CLASS and changes
> when a manual is revised, not when an asset moves.
>
> That line is the same one the wear-component manifest drew (GD-14): **a fact about a platform
> class does not belong in a per-asset record.** Here it is drawn between systems rather than
> between files.

**THAT IS ADR-0051 §6.1's SPLIT, DRAWN BETWEEN SYSTEMS INSTEAD OF BETWEEN GRAPHS** — and GD-14
drew it between files. Three instances, three granularities, one line: vocabulary is knowledge
(true of a class, changes when someone revises it); instances are state (true of a thing that
exists now). **So the reproducibility field is not an implementation detail of our prime; it is a
recurring boundary that three ratified documents have found independently.**

*Self-check, since it is cheap:* the doc corpus this lane just built is KNOWLEDGE by that line —
true of a class, changing when a page is revised — which is why it is rebuildable and prime-wiped,
and the split agrees with the design rather than merely permitting it.

`OpenDDIL proposes; the system of record disposes` is also the third appearance of ADR-0040 §7's
custody line and our own *acceptance is not a verb*.

## ADR-0035's six classes — and class 6 is an argument about OUR SHAPE

Two of the six are already how this lane builds, which is a useful confirmation rather than a find:

* **Class 2 — absence renders as absence, never as a zero**, with two distinct empty states
  *"because the operator's next action differs"*. That is `BodyUnavailable` versus
  `BodyShaMismatch`, and the abstain that names its subject.
* **Class 3 — "Honesty is asymmetric on purpose: we are quicker to say we have lost something than
  to say we have it back."**

**Class 4 is the sentence for the data-class ADR's centre:**

> **a session-scoped accumulator never wears the noun of a durable record.** "Expended" alone is a
> stockpile claim. "Expended since session start" is an observation claim, which is what the data
> is.

A value's NOUN must match its class. That is the whole ADR in one line, arrived at from the
rendering side.

### Class 6 is a warning about the four-field shape itself

> ADR-0026 established that entity posture is three orthogonal axes, and that **collapsing them is
> lossy**. The corollary at the presentation layer: **a value derived from one axis may not be
> rendered in another axis's words.**

**THE PACKET GIVES FOUR FIELDS AND THREE LIFECYCLE SHAPES, AND THE SHAPES ARE COMBINATIONS OF THE
FIELDS.** `rebuildable`, `stateful iagent-authored`, `of-record-elsewhere` each fix several axes at
once. Class 6 says what goes wrong if the names replace the fields: **"stateful" starts meaning
things about authority and sync obligation that it does not carry**, and a store that is stateful
with an upstream authority has no honest name.

So the ADR must say it: **the three shapes are NAMES FOR COMMON COMBINATIONS, never a substitute
for declaring the four.** The class is four fields; the shapes are shorthand, and a store that fits
none of them declares its fields anyway rather than being forced into the nearest.

**That is also how `fold, do not hand-run`'s debt stays a refusal rather than a fifth shape** —
hand-seeded state declares `reproducibility: stateful` and has no bootstrap, and the honest outcome
is that the census refuses it, not that it earns a name.

## AUDIT-2026-08-08 — and the line ADR-0042 must not step over

**The audit declares its own unverified status, and that governs how ADR-0042 may use it:**

> Live verification of any classification (no populated-cluster access). **This table is derived
> from charts and source, not observed behaviour under an actual sever.**

So the severance-tolerance classifications are a **reading**, not a measurement. ADR-0042's
multi-tier custody rules rest on them, and the ADR must say that plainly rather than inheriting
their confidence — *a skip is not a pass*, one repo over and one artifact class along. **Custody
under severance has never been watched happening.**

**Three findings bear directly on custody:**

* **The reachback failure is WRITE-SIDE, not read-side.** `projector-<edge>` *"reads a local broker
  and writes a root database"*, and its non-tolerance is that *"the data reaches it fine during
  severance; it simply cannot store it anywhere the local tier can read."* That is the shape intent
  custody exists to answer: the problem is never getting the fact, it is having somewhere local and
  durable to put it.
* **The sweep paid for itself by finding a twin.** `cm-service` is structurally identical to
  fusion — a third instance of one shape, found by deriving the inventory rather than listing the
  known cases. *"Will the sweep surface another one: yes, and it is fusion's twin."*
* **The constraint is concentrated.** Only Restate constrains tier placement, and it constrains
  exactly two services — so custody at a severed intermediate tier is *"a two-service problem, not
  a stack-wide one"*.

---

# Reading complete — what the two drafts now rest on

**THE DATA-CLASS ADR.** Its shape is fixed by ADR-0035 class 6 before a word is written: **four
fields are the declaration, three shapes are names for common combinations, and a store fitting
none of them declares its fields anyway.** Collapsing four axes into three names is lossy exactly
where the odd case lives — *stateful with an upstream authority* — which is the case the FRACAS and
OpenDDIL work is about. It opens on ADR-0035 class 4: **a value's noun must match its class.**

Its argument is the gap between §6.1's claim of enforcement and the clearer's derived drop set:
reproducibility is asserted by **absence from a list**, and absence is the one state a derived
population cannot distinguish from an omission. Its enforcement framing is borrowed from OpenDDIL
ADR-0034 — *unwritable rather than audited-for*. Its rollout is ADR-0029 §7 — label first, hard gate
at zero per environment, population derived at run time. Its fourth field is **reserved, not
defined**, on ADR-0029 §3's reasoning. Its population is **provisional** until the eo lane's write
census lands.

**ADR-0042.** Scope is ADR-0040's gaps 3 and 4 only. Custody attaches to §7's line; retention is
half-ruled in Limits and the degraded-mode paragraph is the template for severance outlasting it;
sanitization is VE-7's gate at egress, which for intent means **at tier replication**, rule public
and patterns not. Multi-tier custody rests on an inventory **derived from charts and source and
never observed under a sever**, and the ADR says so.

**Every mechanism in both is cited to the document that registered it.** Three citations moved
during the reading — `asserted-locally-unconfirmed` (ADR-0040 §3, not ADR-0035), sanitization
(ADR-0037 registers, ADR-0040 points), and ADR-0034 (two repos, one number) — and one of the three
was a correction to my own first correction.
