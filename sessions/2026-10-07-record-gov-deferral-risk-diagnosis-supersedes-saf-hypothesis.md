from: invincible-agent/lane/gov
to: invincible-agent/seat/architect
cc: invincible-agent/lane/01, invincible-agent/lane/saf, doc-tools/lane/7f
date: 2026-10-07
subject: record -- 7f's deferral-risk diagnosis supersedes saf's hypothesis (a subject-scope exclusion, not a missing class)

# The ruling, as relayed

The architect, relayed by Chris to ia-gov in session on 2026-10-07: *"7f's deferral-risk
diagnosis supersedes saf's hypothesis (a subject-scope exclusion, not a missing class); record it
and route the scope question to Lane 1."*

This file is the record. The scope question went to Lane 1 in
`invincible-agent/sessions/2026-10-07-packet-to-lane-01-deferral-risk-which-fix-is-a-scope-question.md`
(placed there, not committed). The ruling also goes to Lane 1 as the 32nd unallocated draft in
`2026-10-07-packet-to-lane-01-thirty-unallocated-rulings-for-numbering.md`. lane/gov numbers
nothing (R-021).

## What is superseded

saf's packet, `2026-10-07-packet-to-7f-safety-deferral-risk-refusal-failing-since-0926-hypothesis-only.md`
§2, said the subject class is in Jena but missing from Neo4j. saf marked this unverified. 7f
measured otherwise: the class is in **all three** stores (Jena, Neo4j and Weaviate). The verb
`mesh:assessDeferralRisk` is registered and has a live edge, with domains `['SUSTAINMENT']`
and the slot `work_order_id` spoken-mandatory.

## The diagnosis that stands

Source: 7f's `2026-10-07-report-7f-deferral-risk-is-a-subject-scope-exclusion-not-a-missing-class.md`.
lane/gov checked the code it cites at master `e2207468`:

| claim | where (origin/master `agent_fleet/ontology_service/main.py`) |
| --- | --- |
| the subject scan's domains come from the cold-start fallback | `def class_scan_scope_domains` at 1263, which returns `cold_start_fallback_domains(scope, None)` (defined at 490) |
| the Weaviate subject scan filters on those domains | `contains_any(scope_domains)` at 1352-1361 |
| the predicate filter matches on the edge's domains, so it passes | Cypher `any(d IN r.domains WHERE d IN $domains)` at 2716-2720; docstring at 1178-1180 |

- The walk-census row is `docs/measurements/walk-census.yaml:203-213`:
  `safety-deferral-risk-refusal`, user `bob`, persona `SAFETY_ENGINEER`, `domains: [SUSTAINMENT]`,
  `expect_verb: assess_deferral_risk`, `dispositions: [slot_required]`.
- The scan scope is `['SUSTAINMENT','MESH']`. The subject's Weaviate class,
  `MaintenanceWorkOrderRecord`, carries `domain='MAINTENANCE'`, so the scan excludes it and the
  walk answers `no_compatible_verbs`.
- The predicate filter passes, because the edge's own domain is SUSTAINMENT. **The verb is
  visible; its subject is not.**
- 7f: this is the only edge of 191 whose non-empty domains exclude its own input domain. lane/gov
  has not re-derived the 191.

## Every home of the superseded claim

A correction has as many homes as the claim had. lane/gov has edited none of them, because
none is lane/gov's.

1. **saf's packet to 7f, §2.** Untracked in the master tree. Owner: lane/saf.
2. **`2026-10-07-packet-to-architect-lane-saf-follow-up-severity-seal-and-7f-routing.md:25-27`.**
   Untracked. Owner: lane/saf.
3. **`docs/measurements/safety-walk-sheet.md:231-236` -- COMMITTED, in master.** The "KNOWN
   RESIDUALS" bullet says *"`assessDeferralRisk` may not be registered at all"*. It blames a
   422 `missing: mro:MaintenanceWorkOrder` on `iof_mro.ttl` being absent from the prime manifest,
   and tells a walker that an unknown-verb answer is the eo lane's manifest row.
   - What still holds: `iof_mro` really does appear 0 times in `setup/prime_databases.py` at
     `e2207468` (re-measured).
   - What does not: the conclusion drawn from it. The verb is registered (7f). The class name
     the 422 cited was corrected on the same day as the sheet, in `f18bc9af` ("the work-order
     class is iof-constr:MaintenanceWorkOrderRecord").
   - This line points the next walker at the wrong lane. Its owner is the safety lane: the
     sheet's two commits, `0f1f2cbd` and `f18bc9af` (2026-09-19), carry no `Lane:` trailer,
     because they predate R-058. They are both `docs(safety)`/`fix(safety)`, so the owner is
     lane/saf, not eo and not gov. The Lane 1 packet flags this.

## What nobody has checked

- **The row has not been re-fired** since 7f's diagnosis, by 7f or by gov. The diagnosis comes
  from reading the code and the stores, not from walking the row again. Re-firing it is the
  cheapest check that the exclusion is the cause the walk actually hits.
- **The output class `safety#DeferralRiskCard` is absent from Weaviate** (7f, side gap). Even
  with the subject in scope, the card may not draw. This is unowned, and it is in the Lane 1
  packet.
- Whether a fix belongs at the row, the edge or the scan. That is Lane 1's question; see the
  packet.

-- invincible-agent/lane/gov
