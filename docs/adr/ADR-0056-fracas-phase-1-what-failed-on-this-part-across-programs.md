# ADR-0056 — FRACAS Phase 1: "what failed on this part, across programs"

**Status:** Proposed — written before review; `lane/saf` drafted this against `2b6fe0f6` and
the first verb is built and sealed, but no cluster has primed it and no domain owner has read
it. Phase 2 (the real connector, live data, OpenDDIL's edge entry) is explicitly out of scope
and is not started.
**Date:** 2026-10-06
**Deciders:** lane/saf (draft); awaiting architect / domain-owner review
**Related:**
  - [`ADR-0007`](ADR-0007-survey-before-mint.md) / `docs/adr/minted-concepts.md` — survey-before-
    mint discipline this ADR's §2 follows for `safety:FailureRecord`.
  - [`ADR-0036`](ADR-0036-config-layering-seed-overlay-composition.md) — the seed/overlay
    `compose()` mechanism `iagent_mesh.systems_of_record` and `src/iagent/origin_resolver.py`
    build on; the existing Origin-resolution and `SystemOfRecordConnector` machinery this ADR's
    §4 finds does not fit FRACAS's one-to-many query shape.
  - `ADR-0051` §5 — CLEARANCE-BOUNDED payloads (citations travel, narrative does not), reused
    here for every `FailureRecord`.
  - `ADR-0039`'s amendment — "an engine computes facts and never chooses what happens next" —
    governs §4's second open question (no per-program filtering inside the verb).
  - `sessions/2026-10-02-packet-to-openddil-systems-of-record-sor-events-a-and-sor-plm-a.md` —
    the placeholder discipline §1 follows: `sor-events-a` stays a placeholder on OpenDDIL's
    explicit request; `relyence` is used by its real name because the packet's own reasoning
    (a customer identity vs. a commercial product name) only asks for the former.

---

## Context

A maintainer's standing question for a fielded part — "has this failed before, and where" — is
currently answered from memory, one program's logbook at a time. FRACAS (Failure Reporting,
Analysis, and Corrective Action System) is the discipline this question belongs to; this repo
has never had a verb for it. Two systems of record are named in the lane-creation work order and
the OpenDDIL packet above:

- **`sor-events-a`** — a placeholder. OpenDDIL's packet asks explicitly that the real customer
  system behind it never be written into a file this broadly shared, and this ADR preserves
  that placeholder verbatim, including in this sentence.
- **Relyence** — a commercial reliability-engineering product, not a customer identity. The
  OpenDDIL packet's own reasoning for `sor-plm-a`'s placeholder was consistency only, not a
  request from OpenDDIL — so this ADR, and the work order that asked for it, use Relyence's
  real name.

Phase 1's scope, set by the work order and kept narrow on purpose: **one read-only verb**, "what
failed on this part across programs," with **no write path**, no live connector, and no edge
entry. Phase 2 — a real `SystemOfRecordConnector`, live data from either system, and OpenDDIL's
own edge — is explicitly deferred and **waits on OpenDDIL's dry run**, per the work order.

## Decision

1. **Reuse `safety:SafetyCriticalItem` as the input class.** It is already declared
   (`setup/ontologies/safety_extension.ttl:128`) as "a part, procedure or inspection whose
   failure or omission opens a hazard," owned by `engine-safety`. No new "Part" class is minted:
   a survey of the vendored sources this repo already carries (`Maintenance.rdf`, `iof_mro.ttl`,
   `product_structure_extension.ttl`) turned up no genuine standards-grounded part-identity class
   (`mro:SparePartInventory` is a different concept — stock on hand, not part identity), and
   inventing or mis-citing one is the exact mistake `safety_extension.ttl`'s own history records
   making once already over `MaintenanceWorkOrderRecord` (see that file's struck-and-corrected
   note). Reusing the already-owned class instead keeps ADR-0007's survey-before-mint discipline
   intact and costs nothing new to declare.

2. **Mint `safety:FailureRecord` and `safety:FailureRecordSet`.** A `FailureRecord` is one dated,
   cited occurrence a system of record filed — distinct from `s3kl:FailureMode` (a taxonomy of
   causes, already cited by `safety:hasCause`) in the same way `safety:RiskAssessment` is distinct
   from the matrix it reads. `FailureRecordSet` is the verb's `output_uri`, following the engine's
   existing `<Thing>Set` convention for a multi-row response (`safety:OrphanedHazardSet`'s sibling),
   `rdfs:subClassOf mesh:Response` to inherit the grounding-pool exclusion (ADR-0046). Both classes
   are declared in `setup/ontologies/safety_extension.ttl`, which is already in the prime manifest,
   so no manifest row is needed for them to be primed.

3. **Register one verb, `mesh:whatFailedOnThisPart`,** function `what_failed_on_this_part` in
   `agent_fleet/safety_agent/measures.py`, registered in `agent_fleet/safety_agent/main.py`'s
   `VERBS` table following the exact pattern its two siblings (`assessDeferralRisk`,
   `draftRiskAssessment`) already use: a module-level fixture, a REFUSE/empty-set/populated
   three-way branch, and a description that states what the verb is NOT (it resolves no risk
   level, opens no acceptance, writes to no system of record).

4. **The refusal shape mirrors `assessDeferralRisk`'s, for the same reason.** A part number not
   on the critical items list REFUSES, naming how many items it was checked against — the same
   shape as an unknown work order, and for the same reason: answering "no failures" for a part
   this verb cannot identify would be indistinguishable from a part it correctly identified and
   found clean. A *known* critical item with zero recorded failures returns an explicit empty
   `failures` list instead — the check ran and found nothing, a different fact from the check
   never running.

5. **Every record cites its own system of record and an evidence reference into it; none carries
   a narrative beyond the failure mode the source itself recorded** (ADR-0051 §5's
   CLEARANCE-BOUNDED discipline, applied here).

6. **Phase 1 is a fixture only — no real connector is wired.** `what_failed_on_this_part` reads
   `agent_fleet/safety_agent/entities.py`'s `FAILURE_RECORDS` tuple directly. It does not call
   `iagent_mesh.systems_of_record`'s `match_system_of_record` or any `SystemOfRecordConnector`,
   for the reason in §4 below. This is a decision, not an oversight, and is why Phase 2 is a
   separate ADR-worthy increment rather than a follow-on PR to this one.

## Consequences

- The fleet gains one new, narrowly-scoped, read-only verb with a real seal
  (`tests/safety/test_fracas_phase1_what_failed_on_this_part.py`), costing two new TTL classes
  and no new infrastructure.
- FRACAS's cross-program correlation is demonstrated — PN-8801 fails on two platforms, cited
  from two different systems of record, in one answer — but **only against this engine's own
  fixture**. Nothing here proves the real `sor-events-a` or Relyence integration will fit the
  same shape; §4 names the specific protocol mismatch that would have to be resolved first.
- No write path exists to seal against (confirmed by this ADR's own AST-level test), so the
  risk this ADR is most careful about — a verb that quietly starts mutating a system of record
  it was only asked to read — is checked by construction, not by a promise.

## Alternatives considered

- **Mint a new `safety:Part` class instead of reusing `SafetyCriticalItem`.** Rejected: no
  standard this repo vendors defines one, and ADR-0007's discipline exists precisely to refuse
  an invented-but-cited class. `SafetyCriticalItem` already identifies exactly the population
  FRACAS Phase 1 answers over (parts whose failure matters enough to track).
- **Wire the real `SystemOfRecordConnector` protocol now, even with fake data behind it.**
  Rejected for Phase 1: that protocol's `lookup(value) -> dict | None` returns at most one record
  per value, which does not fit "every failure, across every program" — a one-to-many query. Doing
  this properly needs either a new connector shape or a different composition, and deciding that
  silently, inside an unrelated verb's first PR, is exactly the kind of invented answer this
  codebase's own culture asks to be raised instead (ADR-0051 §5's own "raised... for the architect"
  precedent). Named as an open question below instead.
- **Filter the output by the caller's own program/platform before returning it.** Rejected for
  Phase 1, and named as the second open question: the only existing mechanism for this
  (`src/iagent/origin.py`'s `can_consume` / `origin_visible`) is scoped to ingested-artifact
  visibility, not to filtering a live engine verb's multi-row response, and inventing a new
  mechanism here would be deciding entitlement policy inside a safety engine — exactly what
  ADR-0039's amendment says an engine must not do.

## Open questions — named for the architect / domain owner, not decided here

1. **The connector-protocol mismatch.** `iagent_mesh.systems_of_record.SystemOfRecordConnector`
   (via `src/iagent/origin_resolver.py`) exposes one method, `lookup(value: str) -> dict[str, str]
   | None` — at most one record per lookup. FRACAS Phase 2's real query — "every failure record
   for this part, across every program, from `sor-events-a` AND Relyence" — is one-to-many and
   does not fit that shape. Phase 2 needs either a new query-shaped protocol alongside the
   existing lookup one, or a different composition (e.g., one `lookup` call per known program,
   fanned out by the caller) — a design choice this ADR deliberately leaves to whoever scopes
   Phase 2, informed by OpenDDIL's dry run.
2. **Per-program filtering of the verb's own output.** `what_failed_on_this_part` returns every
   record it holds, tagged with its platform and citation, performing no filtering of its own. If
   a caller may see a part's hazard history but not every program that part has flown on, that
   gate belongs somewhere with an entitlement model behind it — not invented silently inside this
   verb. Named, not answered, per ADR-0039's "an engine computes facts and never chooses what
   happens next."

## Indicators for revisiting

- OpenDDIL's dry run against a real `sor-events-a` export or Relyence extract lands: Phase 2
  starts, and open question 1 above gets an actual decision instead of a placeholder.
- A second FRACAS verb is requested (a write path, a trend, a corrective-action link): this ADR
  is amended rather than re-litigated, the same way `ADR-0051` was.
- A caller legitimately needs program-scoped visibility before Phase 2's connector lands: open
  question 2 stops being deferrable and this ADR gets its first real ruling.
