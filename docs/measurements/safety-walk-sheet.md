# Safety walk sheet — Engine S, sustainment safety assessment (ADR-0051, ADR-0056)

**Nine questions, three different answer SHAPES — Q4 and Q5 reuse Q3's, Q6 and Q7 are their
populated twins, Q8 and Q9 are Q1's twins at two other matrix cells.** Three draw a card (Q2, Q6,
Q7), three create a TASK and draw nothing (Q1, Q8, Q9), and three REFUSE by asking for a slot. A
walker who expects nine cards will score six defects that are not there.

| Q | question | verb | what a PASS looks like |
|---|---|---|---|
| 1 | draft a risk assessment for HAZ-1003 | `draft_risk_assessment` | **a task in bob's queue**, not a card |
| 2 | what hazards are unattended | `find_orphaned_hazards` | a `CONTRIBUTION_RANKING` card, 3 rows |
| 3 | risk of deferring this work order | `assess_deferral_risk` | **a refusal** asking for `work_order_id` |
| 4 | what failed on this part | `what_failed_on_this_part` | **a refusal** asking for `part_number` |
| 5 | failure trend for this platform by month | `failure_trend_for_this_platform_by_month` | **a refusal** asking for `platform_id` |
| 6 | what failed on this part PN-8801 | `what_failed_on_this_part` | a `CONTRIBUTION_RANKING` card, 1 row (bob sees one program) |
| 7 | failures per month on this platform PLT-ALPHA | `failure_trend_for_this_platform_by_month` | a `MULTI_SERIES` card, 1 period (bob sees one program) |
| 8 | draft a risk assessment for HAZ-1001 | `draft_risk_assessment` | **a task** for the `risk_acceptance_serious` audience, not a card |
| 9 | draft a risk assessment for HAZ-1005 | `draft_risk_assessment` | **a task** for the `risk_acceptance_low` audience, not a card |

**Every question is one of the engine's own declared `synonyms`**, copied from the verb catalogue
in `agent_fleet/safety_agent/main.py` rather than invented here. The phrasing is the routing
signal; a reworded question tests a different path.

**THIS SHEET IS LOAD-BEARING SOURCE.** `docs/measurements/walk-census.yaml` stores each question
and is checked against the prompts below **in both directions** by
`tests/test_the_walk_census_is_derived_from_the_sheets.py`. Reword a prompt here and the census
fails until it moves with it; add a prompt with no census row and that is equally red. Edit
accordingly.

**Captured from the wire, not from the code**, per the runbook: every payload below came from
`TestClient(app).post("/measure/<verb>", …)` against this engine. `days_open`, and therefore
`contribution` and `share_of_total`, are computed from `date.today()` — **the numbers move daily
and the ORDER does not.** Check the order and the shape; do not check the integers.

- **Fleet revision this sheet assumes:** the roll carrying `lane/74` ≥ `3100a18`.
- **Prerequisites, DEPLOYED not committed:** the safety task kinds and audiences synced into
  Topaz; bob in `safety-engineers`; `safety_risk_matrix.ttl` present in the image; the three
  `rendersAs` bindings primed.

---

## READ THIS BEFORE THE FIRST QUESTION — five ways a CORRECT result looks broken

1. **Q1 draws no card at all, and that is the PASS.** The answer is a row in `human_tasks`, not a
   200 with a payload. An engine that rendered a risk assessment as a finished card would be
   asserting the acceptance had happened. *If you see a card for Q1, that is the defect.*

2. **Q3 refuses, and the refusal is the PASS.** `work_order_id` is spoken-mandatory; the engine
   asks rather than guessing a work order. A verb that answered "the risk of deferring this work
   order" without knowing which one would be inventing the subject.

3. **THE BAR IS NOT THE RANK.** In Q2 the rows are ordered **severity first, then age**, and the
   bar length is **days open**. Those are different quantities, so the bars are deliberately NOT
   monotonic: in the capture below, rank 2 (`HAZ-1003`, severity II) has the **LONGEST** bar, 234
   days, above rank 1 (`HAZ-1001`, severity I) at 189. **A descending ranking with a longer bar in
   second place looks like a sorting bug and is correct.** The legend must read **"days open"** —
   if it does not, the card is misleading and that IS a finding.

4. **No colour on the Q2 rows, and no direction stated.** `favourable` is deliberately absent:
   every unattended hazard is bad, and the ordering is severity, not sentiment. A card that
   colours rows green/red has invented a direction nobody declared.

5. **Three orphans, not six.** The fixture holds six hazards; three are orphaned, one is
   `not_assessed` and reported SEPARATELY, and two are properly mitigated. *A count of 6 is a
   defect — it means not-assessed hazards were folded into the orphan list, which is the exact
   conflation `find_orphaned_hazards` refuses.*

---

## Q1 — Draft a risk assessment  ⚠ **the answer is a TASK, not a card**

> **"draft a risk assessment for HAZ-1003"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:draftRiskAssessment` → `engine-safety:/measure/draft_risk_assessment`
**Expected disposition:** `task_created`

### What must happen first — and this is where Q1 has failed twice

`HAZ-1003` must RESOLVE. Engine S registers a `mesh:resolveInstance` provider for `safety:Hazard`;
the pre-step must ask **the referent class's provider**, not the domain's default (Engine O, which
holds no hazards). Captured from the provider:

```json
{"class_uri": "http://internal/sustainment/safety#Hazard",
 "instance_id": "HAZ-1003", "label": "Fuel quantity probe seal degrades, allowing vapour ingress to the sense line.",
 "score": 1.0}
```

> **If the answer is `instance not found` and the trail ends at General search → Engine A →
> a DATA_ENGINEERING refusal**, the engine is fine and the SLOT-REFERENT WIRING is the finding.
> That is a routing defect, not a safety one. It has been diagnosed as a safety gap twice.

### The captured payload (`/measure/draft_risk_assessment`, `{"hazard_id": "HAZ-1003"}`)

```json
{
  "refused": false,
  "hazard_id": "HAZ-1003",
  "acceptance_status": "drafted",
  "severity": "II",
  "probability": "D",
  "risk_level": "Medium",
  "acceptance_audience": "risk_acceptance_medium:SUSTAINMENT",
  "orphan_reason": "mitigation owned but never verified in the field",
  "derived_from": ["HAZ-1003", "safety_risk_matrix.ttl", "MIT-2103"],
  "citations": {
    "severity": "hazard HAZ-1003",
    "probability": "hazard HAZ-1003",
    "risk_level": "safety_risk_matrix.ttl",
    "acceptance_audience": "safety_risk_matrix.ttl"
  },
  "note": "DRAFTED. Accepting this risk requires an authority in 'risk_acceptance_medium:SUSTAINMENT'. This engine cannot accept it; the acceptance is a task disposition with a required reason.",
  "review_request": {
    "kind": "risk_acceptance_medium",
    "task_id": "risk-acceptance-HAZ-1003",
    "audience": "risk_acceptance_medium:SUSTAINMENT",
    "title": "Accept Medium risk — HAZ-1003"
  }
}
```

### Checks that distinguish

- `acceptance_status` is **`drafted`**, never `accepted`. This is §7's refusal in one field.
- `risk_level` is **`Medium`**, and `citations.risk_level` is **`safety_risk_matrix.ttl`** — the
  level came from the ratified table, not from the engine's opinion. *Severity II × probability D
  is Medium in MIL-STD-882E Table III; if this reads Low, the matrix in the image is not the
  ratified one.*
- A row appears in `human_tasks` with `kind: risk_acceptance_medium`, **assignee bob**.
- The task's audience is `risk_acceptance_medium:SUSTAINMENT`.

### What a correct result looks like BROKEN

- **A card rendering the assessment** — correct data, wrong outcome. The acceptance is a human
  act; drawing it as a finished artifact is what §7 exists to prevent.
- **A task assigned to alice.** alice holds High and Serious; this is a Medium. A Medium landing
  with the High authority means the matrix resolved the wrong level — read `risk_level` before
  blaming the grant.
- **`acceptance_status: accepted`.** Stop the walk. No verb in this engine may write that value,
  and `tests/safety/test_no_verb_can_accept_a_risk.py` asserts it — a live instance means
  something is writing dispositions the mesh does not know about.

---

## Q2 — Unattended hazards

> **"what hazards are unattended"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:findOrphanedHazards` → `engine-safety:/measure/find_orphaned_hazards`
**Expected archetype:** `CONTRIBUTION_RANKING` · **3 rows**

### The captured payload, trimmed to the fields a walker compares

```json
{
  "refused": false,
  "rows": [
    {"rank": 1, "entity_id": "HAZ-1001", "severity": "I",  "days_open": 189,
     "contribution": 189, "share_of_total": 0.3187,
     "orphan_reason": "no mitigation recorded"},
    {"rank": 2, "entity_id": "HAZ-1003", "severity": "II", "days_open": 234,
     "contribution": 234, "share_of_total": 0.3946,
     "orphan_reason": "mitigation owned but never verified in the field"},
    {"rank": 3, "entity_id": "HAZ-1002", "severity": "II", "days_open": 170,
     "contribution": 170, "share_of_total": 0.2867,
     "orphan_reason": "mitigation recorded but no owner"}
  ],
  "value_label": "days open",
  "value_unit": "days",
  "scope_label": "fleet",
  "orphan_count": 3,
  "not_assessed_count": 1
}
```

### Checks that distinguish

- **Exactly 3 rows**, ranked `HAZ-1001`, `HAZ-1003`, `HAZ-1002` **in that order**.
- **All three `orphan_reason` values are different** — "no mitigation recorded", "mitigation
  recorded but no owner", "mitigation owned but never verified in the field". *The third is the
  one that hides: a mitigation that exists and is owned reads as handled in any view that checks
  only for presence. If the card shows three rows with the same reason, the reason is being
  defaulted rather than carried.*
- **The legend reads "days open".** See residual 1.
- `not_assessed_count` is **1** and that hazard is **NOT** among the three rows.

### Which component owns each failure

> **If no card draws at all**, read the HUD's `selection_basis`. `payload-only (output_uri
> matched no capability)` means the `rendersAs` binding did not reach the graph — that is a
> PRIME finding, not an engine one. A named archetype that drew nothing is a CORTEX finding.
> **Both look identical on screen**, which is why this line exists.

> **If the rows draw but carry no `orphan_reason`**, the payload is right and the RENDERER is
> dropping the field — cortex, not engine. The capture above is the evidence.

### What a correct result looks like BROKEN

- **Rank 2's bar longer than rank 1's** — correct, see residual 3.
- **Six rows** — the not-assessed hazard and the two mitigated ones have been folded in.
- **A bar chart of severity** — severity is an ordinal with no length; if the card plots I/II/III
  as magnitudes it has invented a scale.

---

## Q3 — Deferral risk  ⚠ **expect a REFUSAL**

> **"risk of deferring this work order"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:assessDeferralRisk` → `engine-safety:/measure/assess_deferral_risk`
**Expected disposition:** `slot_required` — **this is a PASS**

### The captured refusal

```json
{
  "refused": true,
  "reason": "missing required slot(s)",
  "missing": ["work_order_id"],
  "slots": [{"name": "work_order_id", "kind": "spoken-mandatory", "type": "str", "required": true,
             "referent": "https://spec.industrialontologies.org/ontology/construct/MaintenanceWorkOrderRecord"}]
}
```

### Checks that distinguish

- The refusal **names `work_order_id`** and says it is spoken-mandatory.
- The referent is **`iof-constr:MaintenanceWorkOrderRecord`** — the standard's real class. ⚠ This was `mro:MaintenanceWorkOrder` until 2026-09-19, cited from a file whose header calls itself a DUMMY extract; the upstream IOF ontology declares no such class. A work order is an INFORMATION CONTENT ENTITY describing a process, not the process.
- **The surface ASKS the walker for a work order.** A refusal that renders as generalist prose,
  or as "No content available", is the same defect as a card that will not draw — and it is the
  one a walk is most likely to mislabel, because *nothing drew* is what both look like.

### ⚠ KNOWN RESIDUALS — do not score these red

- **`assessDeferralRisk` IS registered; what fails is its SUBJECT SCOPE.** The engine declares the
  verb (`mesh:assessDeferralRisk`, `agent_fleet/safety_agent/main.py`). The architect ruled on
  2026-10-07 (recorded by lane/gov, read here from its packet, NOT re-measured by lane/saf) that
  the router's subject scan excludes the subject's own domain: the scan spans `SUSTAINMENT` and
  `MESH`, and `MaintenanceWorkOrderRecord` is a `MAINTENANCE` class, so the verb is visible and
  its subject is not. That supersedes this sheet's earlier "`iof_mro` is not in the prime manifest"
  explanation (`iof_mro.ttl` is still not in the prime manifest -- `iof_mro` appears zero times in
  `setup/prime_databases.py` -- but lane/saf's
  hypothesis that this was the cause was not borne out). *If Q3 answers `no_compatible_verbs`, read
  it as the subject-scope exclusion and route it to Lane 1 -- not as the verb being unregistered,
  and not a safety defect.*
- **Work-order resolution is Engine E's, by ruling.** Engine S abstains on `WO-3001` deliberately.
  If a named work order does not resolve, that is the referent wiring again, not this engine
  claiming a class it was told not to claim.

### If the slot IS supplied — the follow-on, for when the class primes

Post `{"work_order_id": "WO-3001"}` and the captured answer is:

```json
{"refused": false, "work_order_id": "WO-3001", "part_number": "PN-8801", "deferred": true,
 "safety_critical": true, "critical_items_checked": 2, "csi_id": "CSI-5001",
 "reopens_hazard_id": "HAZ-1001", "severity": "I", "probability": "D", "assessment": "drafted"}
```

`critical_items_checked: 2` is the load-bearing field: **an empty answer and a completed check are
different facts**, so a not-critical verdict must say how many items it was checked against. A
card that shows "not safety critical" with no count is not distinguishable from one that checked
nothing.

---

## Q4 — What failed on this part  ⚠ **expect a REFUSAL, same shape as Q3**

> **"what failed on this part"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:whatFailedOnThisPart` → `engine-safety:/measure/what_failed_on_this_part`
**Expected disposition:** `slot_required` — **this is a PASS**

ADR-0056 Phase 1's own verb. THIS SECTION IS THE REFUSAL BRANCH; the populated branch is **Q6**,
which is a census row of its own now that `safety:FailureRecordSet` is a declared `CONTRIBUTION_RANKING`
binding (it was refusal-only until 2026-10-08, when no `rendersAs`/`ROW_KEY` archetype existed for it).

### The captured refusal

```json
{
  "refused": true,
  "reason": "missing required slot(s)",
  "missing": ["part_number"],
  "slots": [{"name": "part_number", "kind": "spoken-mandatory", "type": "str", "required": true,
             "referent": "http://internal/sustainment/safety#SafetyCriticalItem"}]
}
```

### Checks that distinguish

- The refusal **names `part_number`** and says it is spoken-mandatory.
- The referent is **`safety:SafetyCriticalItem`** — the already-owned class ADR-0056 §Decision-1
  reuses rather than minting a new "Part" concept. If this ever reads as a bare string with no
  referent, `agent_fleet/safety_agent/slots.py`'s `_REFERENT_KIND` lost its `part_number` entry.
- **The surface ASKS the walker for a part number.** A refusal that renders as generalist prose,
  or as "No content available", is the same defect named in Q3 — *nothing drew* is what both a
  missing refusal and a missing card look like from the wire.

### If the slot IS supplied — the follow-on, which Q6 walks as a census row

Post `{"part_number": "PN-8801"}` AS A MEMBER OF BOTH PROGRAMS (alice) and the captured answer
correlates across two programs and two systems of record (ADR-0056's whole reason to exist). The
`rows`/`value_*`/`scope_label` keys that make it a card are shown under Q6; this block is the
flat record list that sits beside them:

```json
{"refused": false, "part_number": "PN-8801", "critical_items_checked": 2, "failure_count": 2,
 "platforms": ["PLT-ALPHA", "PLT-BRAVO"],
 "systems_of_record_cited": ["relyence", "sor-events-a"],
 "failures": [
   {"record_id": "FR-6001", "platform": "PLT-ALPHA", "system_of_record": "sor-events-a",
    "failure_mode": "Chafed wiring loom shorted the primary bus.", "observed_on": "2026-03-14",
    "citation": "sor-events-a:EVT-55101"},
   {"record_id": "FR-6002", "platform": "PLT-BRAVO", "system_of_record": "relyence",
    "failure_mode": "Wiring harness chafe — FMEA failure mode WH-12.",
    "observed_on": "2026-08-11", "citation": "relyence:FM-7734"}],
 "note": "2 failure(s) for PN-8801 across 2 program(s) and 2 system(s) of record.",
 "output_uri": "http://internal/sustainment/safety#FailureRecordSet"}
```

`critical_items_checked: 2` is the same load-bearing field Q3's follow-on carries, for the same
reason: a part this verb has never seen fail and a part it cannot identify at all must not read
as the same answer.

---

## Q5 — Failure trend for this platform by month  ⚠ **expect a REFUSAL, same shape as Q3 and Q4**

> **"failure trend for this platform by month"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:failureTrendForThisPlatformByMonth` → `engine-safety:/measure/failure_trend_for_this_platform_by_month`
**Expected disposition:** `slot_required` — **this is a PASS**

ADR-0056 Phase 1's second verb. THIS SECTION IS THE REFUSAL BRANCH; the populated branch is **Q7**,
a census row of its own now that `safety:FailureTrend` is a declared `MULTI_SERIES` binding.

### The captured refusal

```json
{
  "refused": true,
  "reason": "missing required slot(s)",
  "missing": ["platform_id"],
  "slots": [{"name": "platform_id", "kind": "spoken-mandatory", "type": "str", "required": true,
             "referent": "http://internal/sustainment/safety#Platform"}]
}
```

### Checks that distinguish

- The refusal **names `platform_id`** and says it is spoken-mandatory.
- The referent is **`safety:Platform`**, a class minted for this verb (ADR-0056 amendment); its
  members are `PLT-ALPHA`, `PLT-BRAVO`, `PLT-CHARLIE`, derived from the fixtures. A bare string with
  no referent means `slots.py`'s `_REFERENT_KIND` lost its `platform_id` entry.
- **The surface ASKS the walker for a platform.** Prose or "No content available" is the same
  defect named in Q3.

### If the slot IS supplied — the follow-on, which Q7 walks as a census row

The caller must be a PERSON. A `svc:` principal or no caller is refused **HTTP 422**
`{"error": "no_person", ...}`; Topaz down is **503** `authorization_unavailable`; a person with no
membership of the platform's program gets the empty series, not a refusal. For a member, post
`{"platform_id": "PLT-ALPHA"}`:

```json
{"refused": false, "platform_id": "PLT-ALPHA", "failure_count": 1,
 "bucket": "observed_on, calendar month (YYYY-MM), no timezone; empty months included",
 "months": [{"month": "2026-03", "failure_count": 1, "failure_record_ids": ["FR-6001"],
             "citations": ["sor-events-a:EVT-55101"]}],
 "undated": {"count": 0, "citations": []},
 "systems_of_record_cited": ["sor-events-a"]}
```

Months are counted on `observed_on` as written (no timezone); empty months between the first and
last visible month appear with `failure_count: 0`.

---

## Q6 — What failed on this part, WITH the part named  ⚠ **expect a CARD, one row**

> **"what failed on this part PN-8801"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT` (a member of `SANDBOX_PROGRAM_ALPHA` only)
**Verb:** `mesh:whatFailedOnThisPart` → `engine-safety:/measure/what_failed_on_this_part`
**Expected disposition:** `drawn` — a `CONTRIBUTION_RANKING` card

The populated twin of Q4. The card ranks **failure modes** by how many times each was recorded across
what the caller may view; the bar is that count, so order and magnitude are the SAME quantity (unlike
Q2). **Bob sees one row, not two:** PN-8801 failed on `PLT-ALPHA` (his program) and on `PLT-BRAVO`
(not his), and the per-record program filter drops the second *before* counting. Two rows, or a
`failure_count` of 2, is the filter not running and is a **finding**.

### The captured payload, as bob (`{"part_number": "PN-8801"}`), trimmed to what a walker compares

```json
{"refused": false,
 "rows": [{"rank": 1, "entity_id": "Chafed wiring loom shorted the primary bus.",
           "entity_name": "Chafed wiring loom shorted the primary bus.",
           "contribution": 1, "share_of_total": 1.0, "platforms": ["PLT-ALPHA"],
           "record_ids": ["FR-6001"], "citations": ["sor-events-a:EVT-55101"]}],
 "value_label": "failures", "value_unit": "failures", "scope_label": "PN-8801",
 "failure_count": 1, "systems_of_record_cited": ["sor-events-a"]}
```

### Checks that distinguish

- **The card is a ranking, not "No content available".** That fallback is what the success path
  drew before the binding existed. If it returns, the `PRESENTATION_CAPABILITIES` row for
  `safety:FailureRecordSet` is not primed, or cortex-ui has not bound the class (see below).
- **One row, one citation:** `sor-events-a:EVT-55101`. No `relyence:` citation — that record is on
  `PLT-BRAVO`.
- **The legend reads "failures".** There is no colour on the row and no direction stated.
- **A single row draws a single full bar (share 1.0).** That is correct for one failure mode.

### ⚠ What this row does NOT establish — read before scoring

- **cortex-ui does not bind `safety:FailureRecordSet` yet.** Until it does, the backend advertises a
  row the frontend has never heard of (the mirror seal carries it as a *staged* gap). The walk can
  still score `drawn` only if the payload-only path chooses the archetype; a `knowledge-document`
  card here is the missing frontend binding, not an engine defect. Owner: cortex-ts.
- **Whether the utterance's `PN-8801` fills `part_number` is a ROUTING question this engine cannot
  answer.** Q1 does the same with `HAZ-1003` and works; the part referent resolves against
  `safety:SafetyCriticalItem`. If the walk answers `slot_required` instead, that is the instance
  resolver not consulting the class, and is Lane 1's, not this verb's. Not walked live by this lane.

---

## Q7 — Failures per month on this platform, WITH the platform named  ⚠ **expect a CARD, one period**

> **"failures per month on this platform PLT-ALPHA"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT` (a member of `SANDBOX_PROGRAM_ALPHA` only)
**Verb:** `mesh:failureTrendForThisPlatformByMonth` → `engine-safety:/measure/failure_trend_for_this_platform_by_month`
**Expected disposition:** `drawn` — a `MULTI_SERIES` card

The populated twin of Q5: failures counted by calendar month of `observed_on`, one declared series
(`failure_count`, unit "failures"), empty months zero-filled between the first and last visible
month. The fixture holds one visible record for PLT-ALPHA, so the card is **one period**; a line
with one point is correct here, not a rendering fault.

### The captured payload, as bob (`{"platform_id": "PLT-ALPHA"}`), trimmed

```json
{"refused": false,
 "rows": [{"period": "2026-03", "failure_count": 1, "failure_record_ids": ["FR-6001"],
           "citations": ["sor-events-a:EVT-55101"]}],
 "series": [{"key": "failure_count", "label": "Failures", "unit": "failures"}],
 "value_label": "Failures per month", "scope_label": "PLT-ALPHA", "failure_count": 1}
```

### Checks that distinguish

- **A series card, not "No content available".** Same reading as Q6.
- **Exactly one declared series, one period `2026-03`, value 1.**
- **No `reference`, no `verdict`.** The trend states no target; a card showing one has invented it.
- The unit is the noun **"failures"** — a count, not a currency. A `$` anywhere is a finding.

### ⚠ What this row does NOT establish

Same two caveats as Q6: cortex-ui does not bind `safety:FailureTrend` yet (a `knowledge-document`
card is the missing binding), and whether the utterance's `PLT-ALPHA` fills `platform_id` is the
instance resolver's question (`safety:Platform` members: `PLT-ALPHA`, `PLT-BRAVO`, `PLT-CHARLIE`).

---

## Q8 — Draft a risk assessment at the worst severity row  ⚠ **a TASK, and Severity I is NOT High**

> **"draft a risk assessment for HAZ-1001"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:draftRiskAssessment` → `engine-safety:/measure/draft_risk_assessment`
**Expected disposition:** `task_requested` — **NOT YET WALKED LIVE** (waits on a Lane 1 roll; the
captured payload below is the engine's own, from `TestClient`, not a cluster).

**Why this hazard.** Q1 is Medium (II x D, bob's audience). HAZ-1001 is severity I (Catastrophic),
probability D, and the ratified matrix resolves that cell to **Serious**, not High
(`setup/ontologies/safety_risk_matrix.ttl`, the `I`/`D` cell). It is the cell a walker will
"correct" to High on instinct, and it is the one where the audience flips from bob's tier to the
senior authority's: `risk_acceptance_serious:SUSTAINMENT`, granted to alice and deliberately not
to bob (`policy/task_grants.yaml`). It also has NO mitigation at all, so the assessment carries
`orphan_reason: "no mitigation recorded"` and an empty `mitigations` list.

```json
{
  "refused": false, "hazard_id": "HAZ-1001", "acceptance_status": "drafted",
  "severity": "I", "probability": "D", "risk_level": "Serious",
  "acceptance_audience": "risk_acceptance_serious:SUSTAINMENT",
  "mitigations": [], "orphan_reason": "no mitigation recorded",
  "derived_from": ["HAZ-1001", "safety_risk_matrix.ttl"],
  "citations": {"risk_level": "safety_risk_matrix.ttl", "acceptance_audience": "safety_risk_matrix.ttl"},
  "review_request": {"kind": "risk_acceptance_serious", "task_id": "risk-acceptance-HAZ-1001",
                     "audience": "risk_acceptance_serious:SUSTAINMENT",
                     "title": "Accept Serious risk — HAZ-1001"}
}
```

### Checks that distinguish

- `risk_level` is **`Serious`**. If it reads High, the matrix in the image is not the ratified one.
- A row appears in `human_tasks` with `kind: risk_acceptance_serious`, **NOT assigned to bob**:
  bob drafts and cannot accept a Serious risk. The audience is `risk_acceptance_serious:SUSTAINMENT`.
- `acceptance_status` is `drafted`, never `accepted`.

### What a correct result looks like BROKEN

- **A card.** Same as Q1: the acceptance is a human act.
- **A task in bob's queue as the acceptor.** That is the audience of Medium and Low.

---

## Q9 — Draft a risk assessment at the lowest cell  ⚠ **a TASK for bob's own tier, on a CLOSED hazard**

> **"draft a risk assessment for HAZ-1005"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`
**Verb:** `mesh:draftRiskAssessment` → `engine-safety:/measure/draft_risk_assessment`
**Expected disposition:** `task_requested` — **NOT YET WALKED LIVE** (waits on a Lane 1 roll).

**Why this hazard.** It is the only fixture hazard in the Low cell (IV x E), so the only one that
reaches `risk_acceptance_low:SUSTAINMENT`, the audience Q1 and Q8 do not. It is also `closed`
with an owned, field-verified mitigation (MIT-2105): the verb does not gate on status, so it still
drafts a task. That is what the engine does today; whether it should is an open question for the
architect, and this row records the behaviour rather than endorsing it.

```json
{
  "refused": false, "hazard_id": "HAZ-1005", "acceptance_status": "drafted",
  "severity": "IV", "probability": "E", "risk_level": "Low",
  "acceptance_audience": "risk_acceptance_low:SUSTAINMENT",
  "orphan_reason": null,
  "derived_from": ["HAZ-1005", "safety_risk_matrix.ttl", "MIT-2105"],
  "review_request": {"kind": "risk_acceptance_low", "task_id": "risk-acceptance-HAZ-1005",
                     "audience": "risk_acceptance_low:SUSTAINMENT",
                     "title": "Accept Low risk — HAZ-1005"}
}
```

### Checks that distinguish

- `risk_level` is **`Low`**, `orphan_reason` is **null** (an owned, verified mitigation).
- The task is `risk_acceptance_low`, audience `risk_acceptance_low:SUSTAINMENT` (bob holds it).
- `acceptance_status` is `drafted`.

### What a correct result looks like BROKEN

- **A Medium or Serious level for IV x E.** The image's matrix is not the ratified one.
- **A card.** As Q1.

---

## What each failure shape MEANS — so a red is attributable

| symptom | owner | why |
|---|---|---|
| `instance not found` for HAZ-1003 | routing / slot-referent wiring | the provider is registered and not consulted |
| blank card, HUD says `payload-only` | prime | the `rendersAs` binding never reached the graph |
| named archetype, nothing drawn | cortex-ui | the binding resolved and the component did not render |
| `no_compatible_verbs` for Q3 | Lane 1 (routing scope; architect ruling 2026-10-07) | the verb is registered; the subject scan excludes the subject's MAINTENANCE domain |
| refusal renders as prose | cortex-ui | a designed refusal lost its shape on the way to the screen |
| a 5xx anywhere | **stop** | this engine returns `200` with `refused: true`; a 5xx is discarded unread by the supervisor and means something upstream of the engine |

## Reporting

Score each question **drawn / task_created / slot_required / red**, and for a red name the owner
from the table above rather than "safety broke". Record the fleet revision and sha — a sheet
assuming a rev that has rolled is measuring something else.
