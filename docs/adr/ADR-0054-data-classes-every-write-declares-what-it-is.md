# ADR-0054 — Data classes: every write declares what it is

> **A session-scoped accumulator never wears the noun of a durable record.**
> — OpenDDIL ADR-0035, class 4

That sentence is this ADR's whole subject, moved from the rendering layer to the storage layer. A
value's **noun must match its class**, and today the mesh has no place to write the class down.

**Status:** Proposed — decision recorded 2026-09-16. **Declaration and enforcement points only; no
store is reclassified by this ADR**, and the population it governs is **provisional** (see §7).
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

**Every write in the mesh carries a declared class of four fields:**

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

- **A store declares a shape name and nothing declares its four fields.** §2 failed, and `stateful`
  has started meaning things it does not carry.
- **An enforcement point is switched on before the count returns zero in that environment**, and a
  prime looks like it worked.
- **`write-back` appears on a store with no ruling behind it.** §3 failed, and the schema carried
  the scope creep two ADRs refused.
- **The gate grows a hardcoded list of stores**, and stops seeing the ones nobody added.
