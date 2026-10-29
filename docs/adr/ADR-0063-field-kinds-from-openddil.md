# ADR-0063 — Field kinds from OpenDDIL: FRACAS reports, safety findings, cyber indicators

**Status:** Proposed. This is design only: there is no code and no roll. `lane/01` drafted §1–§4
against `47502b35`. §2's safety half and §5 are `lane/saf`'s. §1's registry rows are
`doc-tools/lane/7f`'s.
**Date:** 2026-10-28
**Deciders:** architect (assigned 2026-10-28); domain owners per section
**Related:**
  - openddil: the three ADRs being drafted (FRACAS failure records, safety states and interlocks,
    logistics cyber detection). Each has a seam: "a <kind> registered through iagent's door".
    This ADR is the receiving half of that seam.
  - iagent: `ADR-0056` (FRACAS Phase 1) and `ADR-0054` §3, which defers the corrective-action
    write-back.
  - iagent: `ADR-0036` (seed/overlay compose), `ADR-0009` (the domain vocabulary), `ADR-0041` (the
    `OBTAINED_VIA` ladder), and `ADR-0034` (decision records).
  - iagent: the ruling of 2026-10-28 that no automated path clears `safety_critical`
    (`tests/safety/test_no_automated_path_clears_safety_critical.py:3-4`).

---

## Findings first — premises that do not hold as written

Each finding was measured on `47502b35` and changes a section below.

| # | premise | what the tree says |
| --- | --- | --- |
| F1 | review_shape is "record / finding / indicator" | `review_shape` is `Optional[Literal["notice", "document"]]` (iagent_mesh `ingest.py:339`). None of the three is admissible. Widening it is a change to ca's SDK. |
| F2 | `arrives_as: json` | `arrives_as` is an open token (`ingest.py:307`, validator `:422-430`), so `json` is admissible. But no overlay sets it, and "event" is already a **`branch`** (`CONTENT_KIND_BRANCHES = ("document", "event")`, `:136`). The existing event kind, `maintenance-fault-event`, uses `branch: event`. |
| F3 | the FRACAS consumer receives events | It is a **read-time connector**. `agent_fleet/safety_agent/failure_source.py` (`FAILURE_SOURCE_CONNECTORS`, `values.yaml:671`) is queried by `what_failed_on_this_part` (`safety_agent/main.py:224`). There is no event sink to land on. |
| F4 | "define the return event" for corrective action | iagent `ADR-0054:177` says the FRACAS phase-2 flip (corrective actions writing back) "is therefore its own decision". `ADR-0056` puts it out of scope. §2 can name the event, but building it pulls Phase 2 forward. |
| F5 | a finding "can set safety_critical by the ruled rule" | The rule is a static part-number list: `safety_critical(mpn, domain)` is `mpn in mpns(domain)`, with `DOMAIN = "SUSTAINMENT"` (`safety_critical.py:36,49`). A finding cannot add a part to it. It can only **trigger** the promotion for a part the rule already names. |
| F6 | OpenDDIL's source class travels "through our OBTAINED_VIA ladder" | `OBTAINED_VIA` (`src/iagent/provenance.py:44-45`) is a **channel** ranking: direct, etl, warehouse, manual-export, user-drop, steward-corrected. observed / declared / derived is a different axis. Carrying it *through* the ladder is the collapse §4 forbids. See §4. |
| F7 | domains per kind | `policy/domains.yaml` has no SAFETY, RELIABILITY or CYBER domain. Adding one requires ADR-0009 first (`domains.yaml:1-5`). Engine S is SUSTAINMENT. |
| F8 | "interlock-rules-as-overlay" and the "false-readiness view" | Neither term appears anywhere in this tree. They are openddil: concepts, and the ADR names them with that prefix and maps them; it does not cite them as ours. |
| F9 | no safety finding exists to land in | Engine S has acceptance and concurrence workflows and task kinds (hazard_link_review, risk_acceptance_*). "Finding" appears only in comments. |
| F10 | the delegate map is policy | `on_behalf_of` is admitted by `_admit_on_behalf_of` (`gateway.py:4787`) against `DELEGATE_ON_BEHALF_OF`. That map is rendered from chart values (`helm/.../configmap.yaml:448`), and no `policy/` file declares it. |

Side note, not a premise: `ADR-0035:94` says `snowflake` where `provenance.py` says `warehouse`.

---

## §1 — Three kinds, registered where kinds live

The platform owns `kind`, `domain`, `arrives_as` and `review_shape`; 7f writes the rows. The rows
are overlay files under `policy/overlays/<deployment>/content_kinds/`, the same place as
`maintenance-fault-event.yaml`. They use the SDK model `ContentKindRegistration` (iagent_mesh
`ingest.py:194`).

| kind | branch | arrives_as | review_shape | domain | identity_field | seeds_workflow |
| --- | --- | --- | --- | --- | --- | --- |
| `fracas_report` | event | `json` | `record` (F1) | SUSTAINMENT (§3) | `event_id` | none (§2) |
| `safety_finding` | event | `json` | `finding` (F1) | SUSTAINMENT (§3) | `event_id` | saf's Engine S definition (§2) |
| `cyber_indicator` | event | `json` | `indicator` (F1) | §3, open | `event_id` | none |

**Decisions.**
1. **`branch: event` carries "not a document".** `arrives_as: json` is the payload's encoding. It
   is admissible today (F2), and it keeps both facts, so a later JSON *document* is not mistaken
   for an event.
2. **`review_shape` widens by three.** The proposal is
   `Literal["notice", "document", "record", "finding", "indicator"]`. That is ca's SDK
   (iagent_mesh), and it arrives as a minor version. Until it lands, the three rows are refused at
   compose, which is the correct failure. The alternative is to reuse `notice` for all three.
   That is rejected: the reviewer's card would be the same for a failure, a hazard and an
   indicator.
3. **The door is `POST /ingest/events`** (`gateway.py:12137`, `IngestEventRequest` at `:12103`).
   Each event carries `on_behalf_of`, admitted by `_admit_on_behalf_of`. OpenDDIL's broker
   identity must be in the delegate map (F10). That is a values change per deployment, not a
   policy row, and §3 proposes moving it onto the rail.
4. **The episode key** is a trigger's `episode: list[str]`, hashed by `episode_key`
   (`case_routing.py:81,233-238`). For all three kinds it is
   `[openddil_episode_id, openddil_asset_id]`, plus `fault_code` for fracas_report. These are
   OpenDDIL's own ids, carried verbatim. The asset id has the DIS form seen on the 1010 walks
   (`dis:<site>:<app>:<entity>`).
5. **The event is the record, not a pointer to one.** `identity_field: event_id`, as for
   `maintenance-fault-event`, so a resend is the same row.

7f fills the extractor-side columns of each row: passes, outputs, the label. The table above is
the platform half and nothing more.

---

## §2 — Where each lands

**`fracas_report` → engine-safety's failure source, not a new sink (F3).**
- The event is admitted, stored as a `safety:FailureRecord` row in the store a new
  `FAILURE_SOURCE_CONNECTORS` entry reads (name proposed: `openddil-events`), and is then
  answered by the existing verbs. `what_failed_on_this_part` stays read-time and unchanged.
- The card is `KNOWLEDGE_DOCUMENT` per #94's seal (`tests/safety/test_fracas_cards_conform.py:116`).
- Rejected: a sink inside the verb. `what_failed_on_this_part` is a read verb, and making it write changes its
  contract.

**The return event: named here, not built (F4).**
- `fracas_corrective_action` is an outbound event from the case that disposes a failure. It
  carries:
  - `on_behalf_of`, the approver;
  - the episode key from §1.4;
  - `failure_event_id`, the fracas_report's `event_id`;
  - `action`, the disposing verb;
  - `mod_record_ref`, the maintenance action record;
  - the §4 provenance block.
- **Ruling needed.** Building it is ADR-0054:177's "own decision". Until that decision is made,
  the name and shape are reserved and nothing emits.

**`safety_finding` → Engine S. saf's half is below.** Two constraints from this side:
- A finding may **trigger** the `safety_critical = true` promotion. It sets it only where the rule
  already names the part (F5), and it never clears it (ruled 2026-10-28; the census at
  `test_no_automated_path_clears_safety_critical.py:66-67` covers any new write path by its form).
- A finding has no task kind yet (F9). saf names it and its workflow.

**`safety_finding` — saf's half (ruled 2026-10-28: no workflow takes a finding, so a new one is
added).**
- **What it is.** A cited occurrence against a `Hazard`, so evidence for the safety pass and not a
  risk assessment. Severity, probability and acceptance stay iagent's and stay a human act
  (`docs/adr/ADR-0051-sustainment-safety-the-mesh-drafts-a-risk-and-refuses-to-accept-it.md`).
  It arrives with `on_behalf_of` = "" (the service itself): `openddil:openddil-contracts/decisions/ADR-0052-safety-states-and-release-interlocks.md:151-175`.
  Alignment is MIL-STD-882 by concept name (§6).
- **Registration.** `safety_finding` is a **registry seed row** (7f; the platform owns kinds), not
  an overlay row. It is an event-branch row whose `seeds_workflow` is **`safety_finding_review`**
  (`ContentKindRegistration`: `branch: event` requires `seeds_workflow` and `identity_field`,
  forbids `passes` and `outputs`). The row's spelling (hyphen or underscore) and domain are 7f's
  and Lane 1's. The workflow id does not depend on them: workflow ids in the tree are
  underscored (`maintenance_fault`, `safety_acceptance_direct`) whatever the kind's spelling.
- **Workflow `safety_finding_review`.** New: `policy/workflows/safety_finding_review.yaml`, one
  `human_await` step modelled on `policy/workflows/safety_acceptance_direct.yaml`, whose header
  says it is authored and runs only once the event row selects it. `safety_acceptance_direct`
  is **not** revived. `domain_stages: [received, review_pending, disposed]`; `subject_ref` is the
  hazard id; `completion: single, any_of`.
- **Task kind `safety_finding_review`** (new overlay row, `policy/overlays/sample/task_kinds/`),
  archetype `APPROVAL_TASK`, badge `FINDING`. Outcomes:
  - `confirmed` (the ruled "accept"; not spelled `accepted`, which in
    `risk_acceptance_*` means residual risk accepted and must keep meaning only that);
  - `dismissed`, reason-required;
  - `new_hazard` (the "open hazard" outcome; the verb name and its reason requirement already
    exist on `hazard_link_review`). It opens the hazard for the human's later draft; the task
    drafts no level.
  There is no risk-level verb, so the task cannot accept risk.
- **Audience.** A role-and-domain string, `safety_finding_review:SUSTAINMENT`: the safety
  steward, SUSTAINMENT. It follows the `<audience>:<scope>` keys of `policy/task_grants.yaml`
  (compare `hazard_link_review:SUSTAINMENT`, `:306`). It is a new grant row, so: merge, Chris runs topaz_sync, then roll.
- **Requester.** A service raising a task with `on_behalf_of` is ruled admissible; Lane 1 confirms
  `register_task` (`src/iagent/human_tasks.py:407`) accepts it and adds the test (a §5 prerequisite).
- **The state on the card.** `review_pending` while the task is open; `disposed` once closed. The
  card is `KNOWLEDGE_DOCUMENT`, as the other safety cards. The finding's observed / declared /
  derived class is shown from the §4 block and is never folded into a rung.
- **Idempotence.** The case key is derived from the episode `(/asset_id, /hazard, /opened_at)`
  (`openddil:...ADR-0052...md`), so a repeat of one episode lands on the same case and opens no
  second task. Where that key sits on the ledger entry is Lane 1's (Q4).
- **Refusals, named.** `unknown_hazard` and `hazard_closed` (`agent_fleet/safety_agent/measures.py:266,371`)
  create no task. A finding with no resolvable part is `no_asset_part_join` (new).
- **`safety_critical`.** Agreed with F5: a finding may only trigger the promotion for a part the
  rule already names, written as a literal `= true` under a condition (the #128 seal), and never
  `false`. The first slice (§5) sets nothing.

**`cyber_indicator` → audience `cyber_watch` and a card.**
- Audiences are `task_grants.yaml` rows keyed `<audience>:<scope>`, with `grant_to_groups`
  (compare `maint_tier_ack:ORG`, `:436`). `cyber_watch:<tier>` follows that form.
- A new group means: merge, then Chris runs topaz_sync, then roll (the standing order).
- The card is `KNOWLEDGE_DOCUMENT`, showing the indicator, its provenance (§4) and the STIX id as
  a citation. There is no new archetype.
- Outbound STIX is openddil:'s. We store what arrives and show it; we never re-serialise it.

---

## §3 — Domains and audiences per kind, on the policy rail

| kind | domain | audience | deployment overlay carries |
| --- | --- | --- | --- |
| fracas_report | SUSTAINMENT (existing; Engine S's `DOMAIN`) | the FRACAS card's existing readers | the connector entry, the tiers |
| safety_finding | SUSTAINMENT | saf's task kind's audience | the interlock rules (below) |
| cyber_indicator | **new: `CYBER_DEFENSE`**, ADR-0009 first (F7) | `cyber_watch:<tier>` | the indicator-to-asset scope |

- **The overlay per deployment** is ADR-0036's seed/overlay `compose()`. Deployment rows live
  under `policy/overlays/<deployment>/`, and `openddil-lab` is the first.
- **The match, by name.** openddil:'s *interlock-rules-as-overlay* is iagent:'s ADR-0036 overlay:
  a deployment's own rules composed over a shared seed, refused at compose when unreadable.
  Neither side restates the other's mechanism (F8).
- **The delegate map joins the rail.** `DELEGATE_ON_BEHALF_OF` moves from chart values to a
  `policy/` file with a grantor row, so the broker that may speak for whom is reviewed like
  any other grant (F10). The chart keeps rendering it. Only the source moves.
- **CYBER_DEFENSE is the only new domain.** The alternative is ENTERPRISE, which is rejected: its
  cells grant document reads unrelated to indicators, so every ENTERPRISE holder would see them.

---

## §4 — Provenance: OpenDDIL's source class, kept unmerged

- **The axis is new, beside the ladder, not on it (F6).** `OBTAINED_VIA` answers *how the value
  reached us*. OpenDDIL's class answers *what kind of knowing it is*: observed (a sensor or a
  hand on the asset), declared (a record says so), or derived (computed from others). A value can
  be `direct` + `derived`, or `user-drop` + `observed`. Either axis read off the other loses the
  case openddil:'s false-readiness view exists to show: a *declared* ready state with no
  *observed* one behind it.
- **Decision.**
  - The provenance block gains `source_class: observed | declared | derived`. It is required on
    every field of the three kinds and is optional elsewhere.
  - It is validated as its own key, next to the block's required keys (`provenance.py:58,153`).
  - It is never inferred from `obtained_via`, and the ladder never ranks it.
  - Two values for one field with different classes are **both kept**, and neither supersedes
    the other.
- **Owners.** `provenance.py` mirrors `iagent_mesh.provenance` at v0.9.10, so the field lands in
  ca's SDK first and is mirrored here, the same path as `steward-corrected`.
- **Rejected:**
  - adding three rungs to `OBTAINED_VIA` (that is the collapse);
  - a per-kind payload field (each kind would spell it its own way, and the card could not read
    it uniformly).

---

## §5 — First demo-able slice

A `safety_finding` for asset 1010 arrives and lands as a `safety_finding_review` task in the
state `review_pending`.

- **1010** is an OpenDDIL lab asset id (`openddil:...ADR-0052...md:223-225`;
  `openddil:...ADR-0053...md:232`), not a port or a build. That OpenDDIL slice sends nothing to
  iagent (`...ADR-0052...md:236`), so the demo hand-posts the finding, and says so.
- **The predicate.** "Deferred past interval" has no source here: `WorkOrder`
  (`agent_fleet/safety_agent/entities.py:110`) and `Hazard` (`:82`) carry no interval or due date,
  and `assess_deferral_risk` (`measures.py:217`) joins WorkOrder × CSI × hazard. What OpenDDIL
  can send is `service_due_unreleased` (due, no open work). The slice carries whatever the
  finding says; it computes no deferral (Q2).

| piece | days | note |
| --- | --- | --- |
| seed-row check (the `safety_finding` event row selects the workflow) | 0.5 | the row is 7f's |
| **workflow `safety_finding_review`** (definition, header, stages, seed wiring, its own tests) | **2.0** | **new by ruling; was not in the first estimate** |
| landing (hazard resolution, named refusals, case key from the episode) | 1.0 | hand-seeded asset-to-hazard fixture |
| task kind + grant row (`safety_finding_review:SUSTAINMENT`) | 1.5 | topaz_sync before the roll |
| card and state (`review_pending`) | 1.0 | cortex-ui draws it |
| tests (refusals, idempotence, no `false`, no risk verb) | 1.5 | |
| **total** | **7.5** | **2.5 days over the 5.0 first estimate (+50%)** |

The overrun is the workflow (+2.0) and the heavier test set (+0.5). The estimate excludes the
OpenDDIL sender, the interval source and any write to `safety_critical`. The likeliest further
overrun is the seed-row wiring, because doc-tools cannot yet project an event row.

**Prerequisites** from §1–§4 and other lanes:
- `safety_finding` as a **registry seed row** (7f; the platform owns kinds). This corrects the
  earlier "7f's overlay row".
- doc-tools: event rows projectable (`ContentKindEntry` has no `branch` or `refresh`).
- Lane 1, ruling 3: `register_task` accepts a service with `on_behalf_of`, with its test.
- The broker in the delegate map (F10).
- OpenDDIL emits one precomputed episode key (7f's change 3); else the row cannot be finished.
- ca's `review_shape` widening and `source_class`, if the card needs them (F1).
- A part on the `safety_critical` list (F5), for any later promotion; the slice itself needs none.

## §6 — Alignment by concept name

Cited, not restated:
- **MIL-HDBK-2155** (FRACAS): fracas_report, fracas_corrective_action.
- **MIL-STD-882** (system safety): safety_finding, safety_critical.
- **NIST SP 800-82**, **MITRE ATT&CK for ICS** and **STIX**: cyber_indicator, cyber_watch.

## Open questions for the architect

1. F1: is the SDK widening of `review_shape` approved, so ca can be asked?
2. F4: is building `fracas_corrective_action` in scope now, or only reserving its name?
3. F7: is CYBER_DEFENSE approved, and is the ADR-0009 amendment `lane/01`'s?
4. F10: is moving the delegate map onto the policy rail approved? It changes who reviews a
   broker grant.
5. (saf, Q1; agrees with F5) Is a finding only ever a trigger for a part the rule already names?
   Recommend yes: the rule stays a static list, and a finding that would add a part is a separate
   rule change, not made here.
6. (saf, Q2) Which predicate does the slice carry: `service_due_unreleased` (what OpenDDIL can
   send) or "deferred past interval" (what the order says)? Neither side computes the latter.
   Recommend the first, and ask OpenDDIL for an interval only if the second is wanted.
7. (saf, Q3 resolved) Audience of a service-origin task: answered by rulings 1 and 3, a
   role-and-domain string and `on_behalf_of` on `register_task`. Left only to confirm that the
   safety steward group needs the new grant row and topaz_sync before the roll.
8. (saf, Q4, owner Lane 1) Where does the episode key live on the ledger entry? I found no
   field. Recommend a named field on the case, not the task payload.
9. (saf, Q5, §4) Does the source class travel as its own per-entry field beside `obtained_via`,
   never mapped to a rung? Recommend yes (F6).
10. (saf, Q6, owner Lane 1) Who owns the asset_id to part (mpn) to WorkOrder join? Without it a
    finding reaches neither `assess_deferral_risk` nor the promotion. Recommend a read-time lookup
    owned by Engine S's source, not stored on the finding.
