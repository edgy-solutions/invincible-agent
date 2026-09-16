# ADR-0054 — Data classes: every write declares what it is

> **A session-scoped accumulator never wears the noun of a durable record.**
> — OpenDDIL ADR-0035, class 4

That sentence is this ADR's whole subject, moved from the rendering layer to the storage layer. A
value's **noun must match its class**, and today the mesh has no place to write the class down.

**Status:** **ACCEPTED 2026-09-16**, with two amendments taken at ratification and folded in
rather than appended: §2 now states that **the class is a property of the STORE**, declared once,
with a write carrying it by naming the store — reconciling two claims the draft made as if they
were one — and §2 carries a **worked example of a combination no shape covers** (edge-authored
intent), which is the reader's first evidence that the shapes are not the schema. **Declaration and
enforcement points only; no store is reclassified by this ADR**, and the population it governs is
**provisional** (see §7). The eo lane's fleet-wide write census is the first thing that runs against
it. **Amended the same day** — see the amendment section: four answers to its first consumer's
review, and the class does NOT transition.
**Date:** 2026-09-16
**Deciders:** Architect (the four fields and the three enforcement points), Platform team
**Related — CITED REPO-QUALIFIED, because two of these numbers exist in both repos:**
  - [ADR-0051](ADR-0051-sustainment-safety-the-mesh-drafts-a-risk-and-refuses-to-accept-it.md) §6.1
    (**this repo**) — *producers with different reproducibility do not share a graph*. This ADR
    promotes that from a safety rule to a platform one, and §1 is the gap between its claim and its
    mechanism.
  - [ADR-0047](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) §4 (**this
    repo**) — the mirror shape (*locator and hash, never a second copy*) and the **refusal of a
    write-back path**, which §3 makes the hardest field value's contract.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) (**this repo**) —
    provenance is a field, never a join. The class is a field for the same reason.
  - **OpenDDIL ADR-0034** *tier-analytics-are-deployment-configuration* — propagating/terminal
    typing. §4's enforcement is that mechanism, in its own words.
  - **OpenDDIL ADR-0029** §3, §7 — labels are provenance stamped at ingress; *label first, enforce
    second, never the reverse*. §5 is that rollout.
  - **OpenDDIL ADR-0035** classes 4 and 6 — the opening sentence, and the warning in §2 about this
    ADR's own shape.
  - **OpenDDIL ADR-0031** addendum (2026-09-08) — state versus knowledge, the same line drawn
    between systems that §6.1 draws between graphs.
  - **OpenDDIL ADR-0040** §7 — `of-record-elsewhere`'s definition, verbatim in §2.

---

## 1. Context — §6.1 claims enforcement, and the mechanism enforces something else

ADR-0051 §6.1 (this repo) rules that **producers with different reproducibility do not share a
graph**, and states that the split is *"enforced by the clearer, not left to discipline."* The cost
of getting it wrong is quoted there and was real: an earlier glob over `http://internal/*` *"would
have wiped real extracted parts on the very prime run meant to enable the pcn dogfood."*

**Read the clearer and the enforcement turns out to be conditional in a way §6.1 does not say.**
`setup/prime_databases.py` carries the invariant:

> THE DROP SET IS DERIVED FROM THIS FIELD. `clear_ontology_graphs()` computes
> `{f"http://internal/{e['domain']}"}` over this manifest, so a new domain becomes an eighth graph
> picked up automatically — no change to the clearer is needed, and none should be made.

Measured against the manifest on 2026-09-16: **22 entries, 9 domains, and no `_INSTANCES` domain
among them.** So an instance graph survives the prime **because nobody has filed an instance
producer in the manifest** — not because anything refuses one. And filing one is exactly the
mistake §6.1 was written to catch: the clearer cannot tell a vocabulary row from an instance row,
because both are rows with a `domain`.

> **REPRODUCIBILITY IS ASSERTED TODAY BY ABSENCE FROM A LIST, AND ABSENCE IS THE ONE STATE A DERIVED
> POPULATION CANNOT DISTINGUISH FROM AN OMISSION.**

That shape has been paid for three times in this repo in one week, which is why it is cited as a
population rather than as a principle: a doc page with no frontmatter produces no row and reads
exactly like a page nobody wrote; four registry sites omitted made four *checks* go quiet rather
than making anything fail; and the engine census printed a complete-looking table with an engine
missing. **The principle is what those three make.**

**The line is not ours and not new.** OpenDDIL ADR-0031's 2026-09-08 addendum draws it between
*systems* — *"OpenDDIL holds the STATE of the world… the reasoning plane holds KNOWLEDGE about the
world"* — and records that GD-14 drew it between *files*: *"a fact about a platform class does not
belong in a per-asset record."* §6.1 draws it between *graphs*. **Three granularities, three
documents, one boundary, found independently.** A boundary that keeps being rediscovered is real
rather than chosen.

## 2. Decision — four fields, and the three shapes are NOT a substitute for them

**THE CLASS IS A PROPERTY OF THE STORE, DECLARED ONCE. A WRITE CARRIES IT BY NAMING THE STORE.**

Stated first because the title is a slogan and this is the claim. *"Every write declares what it
is"* and *"a declaration per store"* are different assertions, and only the second is enforceable:
a per-write declaration is a field a caller fills in, which can disagree with the store it lands
in and gives the census nothing countable. A per-store declaration is one row per store, and a
write inherits it.

**That is what makes §4's third enforcement point mean anything:** the write interface refuses a
store whose class it may not write — the registrar cannot be handed a `stateful` store, the trace
writer cannot be handed a `rebuildable` one — so the disagreement is caught at the interface rather
than discovered in the data. And it gives the census **one thing to count**: stores, not writes.

**A store's class is four fields:**

| field | values | what it answers |
|---|---|---|
| **reproducibility** | `rebuildable` \| `stateful` | can a bootstrap produce this again from seed and overlay? |
| **authority** | `here` \| `upstream` \| `external system of record` | who decides what the value IS? |
| **sync obligation** | `none` \| `flush-up` \| `mirror-down` \| `write-back` | what must cross a location boundary, and in which direction? |
| **releasability** | **RESERVED — see §6** | who may be shown it? |

**Three lifecycle shapes are named for the common combinations, with their first consumers:**

- **`rebuildable`** — ontology, vectors, registrations, `PARAMETERISED_BY`, markers. The prime may
  drop and re-land it.
- **`stateful`, iagent-authored** — artifacts, lineage, `bound_slot_sources`, assessments and
  acceptances, checkpoints. Preserved; retention is a rail row per kind; `valid_until` honoured.
- **`of-record-elsewhere`** — FRACAS: Eagle events, CAPA records. OpenDDIL: any intent once
  accepted. ADR-0040 §7's line, verbatim: **a mirror with provenance and a write-back contract,
  never the authority.**

### THE SHAPES ARE NAMES FOR COMBINATIONS AND NEVER A SUBSTITUTE FOR DECLARING THE FOUR

**This is the load-bearing constraint on this ADR's own schema**, and it comes from OpenDDIL
ADR-0035 class 6, which records that ADR-0026 established entity posture as three orthogonal axes
and that **collapsing them is lossy** — *"a value derived from one axis may not be rendered in
another axis's words."*

Each shape above fixes several axes at once. If the names are allowed to replace the fields,
**`stateful` starts meaning things about authority and sync obligation that it does not carry**,
and the odd case has no honest name. The odd case is not hypothetical — **a store that is stateful
with an upstream authority** is exactly what the FRACAS and OpenDDIL work is about.

> **A store that fits none of the three shapes declares its four fields anyway**, rather than being
> filed under the nearest. The shapes are shorthand for a reader; the declaration is the four.

### The worked example, because a rule with no instance is a rule nobody applies

**Edge-authored intent fits none of the three shapes, and it is the case the companion ADR attaches
to.** OpenDDIL ADR-0040 §3 names it: a locally-raised action is *"intent the system of record has
never seen and may reject"*, rendered as `asserted-locally-unconfirmed`, *"which is neither
measured nor derived — and it must never present as an accepted transaction."*

Its four fields:

| field | value | why |
|---|---|---|
| reproducibility | `stateful` | a maintainer's action at a severed site is not rebuildable from seed and overlay by anything |
| authority | `upstream`, **pending** | ADR-0040 §7: *"OpenDDIL holds intent durably and authoritatively as intent. It never holds the transaction."* Local authority over what happened here; central authority over the record |
| sync obligation | `flush-up` | it reconciles toward the authority when the link returns, and never downward |
| releasability | reserved (§6) | |

**No shape name fits.** It is not `rebuildable`; it is not `stateful` iagent-authored, because the
authority is elsewhere; and it is not `of-record-elsewhere`, because the record does not exist yet
anywhere — that shape describes a **mirror of an accepted fact**, and this is a request that may be
refused. Forced into the nearest, it would be filed as `of-record-elsewhere` and would then claim a
transaction that nobody has made — **which is precisely the failure ADR-0040 §3 exists to prevent,
arriving through a schema instead of through a screen.**

**That is the class-6 rule doing what it says**, and it is the reader's first evidence that the
shapes are not the schema. The custody, retention and reconciliation rules for this combination are
the companion ADR's subject, not this one's.

## 3. `write-back` is a value the class can carry and nobody may set casually

Two ratified ADRs already refuse it from opposite sides. ADR-0047 §4 (this repo), as a non-goal
with its reason:

> there is no write-back path… it is a **different decision** with its own identity, authorization,
> provenance and admission questions… **It must arrive as its own ruled decision, never as scope
> creep on an export.** A write-back bolted onto a read-only package is an unauthenticated external
> write path into a governed store.

and OpenDDIL ADR-0040 §7's `of-record-elsewhere` from the other: *a mirror with provenance and a
write-back contract, **never the authority***.

**So declaring `sync: write-back` on a store REQUIRES its own ruling**, naming the authority, the
submitter's identity, and what an accepted correction changes for answers already derived from the
disputed value. Without that, the field becomes precisely the scope creep ADR-0047 refuses, wearing
a schema. The FRACAS phase-2 flip — corrective actions writing back to Eagle — is therefore its own
decision, which is what the two-phase plan already said.

## 4. Enforcement — unwritable, not audited-for

**The framing is borrowed rather than invented**, because it is already ratified next door.
OpenDDIL ADR-0034 types every aggregation as propagating or terminal, and:

> The config schema rejects a terminal operation on any stream marked for upward emission… The
> truncation bug becomes **unwritable** rather than merely audited-for — **the difference between
> "we checked" and "the system won't let you."**

That ADR also names the move this one is making: *"the audit's classification table is the seed of
this type table."* **§6.1 is a table in prose; the class is that table becoming a type the schema
enforces; the sync-obligation field is propagating/terminal for writes.**

Three enforcement points, and nothing writes across a location boundary except the third:

1. **The prime's clearer reads the class instead of deriving a drop set from `domain`.** It drops
   what *declares* `reproducibility: rebuildable`. An instance producer filed in the manifest then
   fails at its own declaration rather than on somebody else's data.
2. **The census refuses an unclassified store.** This is what makes §5's gate real rather than
   advisory.
3. **The three write interfaces carry the class in their signature** — the registrar writes
   `rebuildable`, the trace writer writes `stateful`, and **the sync adapter alone writes across a
   location boundary.** A caller cannot express a cross-boundary write through the first two,
   because the type does not permit it.

## 5. Rollout — label first, enforce second, never the reverse

**OpenDDIL ADR-0029 §7, and its hazard is ours exactly mirrored:**

> Deny-unlabeled is only safe once every row is labelled. Turning it on against a partially
> -labelled dataset **silently blanks legitimate data, and the failure mode is indistinguishable
> from correct enforcement — an operator sees an empty screen either way.**

Ours inverts and is equally indistinguishable: **a clearer that drops what declares itself
rebuildable, run against a partially-declared manifest, KEEPS the undeclared** — a prime that looks
like it worked, leaving a stale vocabulary graph that nothing will re-land. So:

- **No enforcement point reads the class in an environment until every store in that environment is
  classified**, and the check is a count that must return zero there.
- **The gate derives its population at run time and never carries a hardcoded list** — ADR-0029
  §7's own constraint, and this repo's law arriving from the other side.
- **`unclassified` must mean genuinely unknown, not "we haven't got to it yet."** ADR-0029 supplies
  a default from deployment configuration for entities with no derivable answer; the equivalent
  here is that a store with no honest class is a **refusal**, not a default.

### Hand-seeded state is a refusal, not a fifth shape

§6.1's seeding rule — **fold, do not hand-run** — names a state that is neither `rebuildable` nor
`stateful` iagent-authored: a value with no bootstrap that reproduces it. **It gets no name here.**
It declares `reproducibility: stateful`, has no bootstrap, and the census refuses it. Giving it a
class would legitimise the debt this rule exists to end.

## 6. Releasability is RESERVED, not defined

**On OpenDDIL ADR-0029 §3's reasoning, quoted because the reasoning is the point:**

> A structured confidentiality label is a real requirement for some programs and a premature
> abstraction… reserving the field number keeps the door open without shipping a shape we would
> have to guess at.

This ADR reserves the field and does not define its vocabulary. What it does adopt is that ADR's
discipline: **a label is provenance, stamped by the party that knows the answer, never re-derived
downstream** — which is ADR-0035 (this repo)'s *provenance is a field, never a join*, in another
repo's words.

## 7. The population is PROVISIONAL and this ADR says so

The input is the eo lane's fleet-wide write census. **Until it lands, the population is derived
from four known write paths** — registration, the artifact writer, human tasks and grants, and
doc-tools ingest — **and four known paths is a sample wearing a census's clothes unless it is
labelled.** It is labelled here.

**No store is reclassified by this ADR.** The declaration exists; the classification of each store
is the census's output, and §5 forbids enforcement until it is complete in an environment.

## 8. A declaration with no witness — one law, three shapes, one week

§6.1 already contains this ADR's own discipline, one domain over:

> **The writer is sequenced AFTER a walk that draws or names its own failure**, rather than built
> against an inferred requirement.

The same refusal appeared twice more in the week this ADR was drafted: a Protocol operation with no
caller was **removed rather than implemented**, and a parameter every caller would pass `None` to
was **not added**. A graph writer, an SDK operation, and a function parameter — **one law in three
shapes.** This ADR cites it rather than restating it, and obeys it: the fields are declared because
three enforcement points will read them, and `releasability` is reserved precisely because nothing
reads it yet.

## AMENDMENT 2026-09-16 — four answers from the first consumer, and two notes

**Raised by `openddil-contracts`' architecture review while drafting
`openddil:ADR-0042`, which is this ADR's first consumer.** Folded in as an
amendment rather than edited into the sections above, because this ADR is Accepted and the
questions are more legible beside their answers than dissolved into the text that prompted them.

**The pairing did what a pairing is for: the schema met its first uncovered case in a neighbour's
hardest store, and the case wrote a value this vocabulary does not contain.** That is the whole
argument for drafting the two together, and it happened before either was enforced.

### 1. The class is PER STORE and does not transition. `pending` is a ROW's status.

The review asked whether a class has a lifecycle, since an intent's looks like it moves:
`authority: upstream, pending` at raise, `external system of record` at acceptance; `flush-up`
becoming `none`.

**It does not move, and the appearance came from a value that should not exist.** `pending` is not
a qualifier on `authority` — **it is the intent row's reconciliation status.** An intent row lives
in the intent store, and that store is `stateful · authority: upstream · flush-up` from the moment
it is created until long after: acceptance changes **the row's status**, and the row's outcome
persists on it (`openddil:ADR-0040`'s Limits requires exactly that). Nothing about the store
changed.

> **A class with a lifecycle would reintroduce the per-write field this ADR removed at
> ratification.** If a class can transition, something must carry the current value per row, and
> that is a field a caller fills in — which can disagree with the store it lands in, and gives the
> census nothing countable. The status is a row's; the class is the store's; they are different
> facts and the intent case is where they look alike.

### 2. `rebuildable` NAMES ITS PRODUCER, and the clearer refuses one that does not

**The review caught an asymmetry this ADR had not priced.** §5 covers enforcement switched on
before the count returns zero. It does not cover a **misdeclaration**, and for `rebuildable` a
misdeclaration inverts the failure: the clearer *drops* what declares itself rebuildable, so a
store wrongly declared is not kept-stale, it is **dropped and never re-landed**.

So: **a `rebuildable` declaration names the producer that re-lands it** — the manifest entry, the
seed job — and **the clearer refuses a `rebuildable` declaration with no producer.**

**The witness is a bootstrap that has been SEEN to rebuild it**, which is §8's own discipline
applied to this ADR's own field: a declaration with no witness. Without a producer, a store
declaring `rebuildable` is the hand-seeded case of §5 wearing the wrong label — and the label is
the one that gets it deleted.

### 3. Sync obligation says NOTHING about retention

The review's question, and it is exactly the right one: *a queue that drains and forgets is
`flush-up`; custody that retains after flush is also `flush-up`.*

**Both are `flush-up`, and this field is not where they differ.** Whether the local copy survives
the flush is the **retention rail row's** question, per kind. Stated explicitly here because the
first consumer's load-bearing line depends on the answer — `openddil:ADR-0042`'s *"a queue that
only drains upward is not custody"* is a **retention** claim, and reading it off the sync
obligation would make it unstatable.

### 4. Releasability is reserved at ROW granularity

`openddil:ADR-0029` stamps labels per row — originator, audience, by the party that knows. **A
per-store reservation would mislead the adopter into thinking a store has a releasability**, which
is the wrong shape to leave a door open in. The reservation stands; its granularity is the row's,
matching where that ADR put it.

### Note A — the citation convention, in force from this date

**`openddil:ADR-NNNN` and `iagent:ADR-NNNN`.** Five numbers — 0029, 0031, 0034, 0035, 0037 — now
name a different document in each corpus, and this ADR's Related block handles it by hand with a
sentence explaining why. **That does not survive the tenth.** Both repos' decision-index checkers
should validate a cross-repo reference the way they validate a local one; until they do, the
qualifier is the discipline.

### Note B — PROV-O alignment, noted and NOT designed

The four fields are provenance-and-lifecycle concepts and map onto PROV-O: **`authority` is
`wasAttributedTo`, `reproducibility` is `wasGeneratedBy`, and `sync obligation` is the activity
that moves data across a boundary.**

**Noted here rather than designed**, so that when OpenDDIL's semantic-layer ADR lands these fields
are in its alignment table **by prior declaration rather than by later retrofit** — which is that
side's own intake rule applied to this side's schema. Designing the alignment now would be
guessing at a table that does not exist, which §6 already refused to do for releasability.

### Note C — the subject merge is smaller than it reads

Carried from `openddil:ADR-0042`'s two-corpora finding: *one subject record carrying both attribute
families* invites a new record type. **The merge point already exists — one `sub` from the shared
identity provider, with two attribute families keyed by it.** A join on a key both sides already
carry, not a schema either side has to author.

## Consequences

**We accept:**

- **A declaration per store, and the work of classifying the existing ones.** That work is the
  census's, not this ADR's, and §5 makes it a precondition rather than a migration.
- **Two write interfaces that cannot express a cross-boundary write.** That is the point, and it
  will be experienced as friction by the first caller who wanted one.
- **A reserved field that does nothing yet**, which is a cost paid to avoid guessing a taxonomy.

**We get:**

- **Reproducibility asserted positively**, so an instance producer in the manifest fails at its
  declaration rather than on somebody else's data.
- **A cross-boundary write that is unwritable rather than reviewed.**
- **One place a store says what it is**, which is what makes the census's refusal meaningful.

## Non-goals

- **Not a retention policy.** Retention is a rail row per kind and is named, not designed, here.
- **Not a releasability model** (§6).
- **Not a write-back mechanism** (§3) — that is its own ruled decision.
- **Not a reclassification of any store** (§7).

## Indicators we got this wrong

- **A STORE'S CLASS DISAGREES WITH THE INTERFACE THAT WROTE IT.** The strongest one: §2's
  per-store declaration and §4's interface refusal have come apart, and a write reached a store its
  writer should not have been handed. Everything else here is a design drifting; this is the
  mechanism not holding.
- **A store declares a shape name and nothing declares its four fields.** §2 failed, and `stateful`
  has started meaning things it does not carry.
- **An enforcement point is switched on before the count returns zero in that environment**, and a
  prime looks like it worked.
- **`write-back` appears on a store with no ruling behind it.** §3 failed, and the schema carried
  the scope creep two ADRs refused.
- **The gate grows a hardcoded list of stores**, and stops seeing the ones nobody added.
