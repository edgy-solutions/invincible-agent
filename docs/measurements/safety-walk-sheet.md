# Safety walk sheet — Engine S, sustainment safety assessment (ADR-0051)

**Three questions, three different answer SHAPES.** That is the point of the set rather than an
accident of coverage: one draws a card, one creates a TASK and draws nothing, and one REFUSES by
asking for a slot. A walker who expects three cards will score two defects that are not there.

| Q | question | verb | what a PASS looks like |
|---|---|---|---|
| 1 | draft a risk assessment for HAZ-1003 | `draft_risk_assessment` | **a task in bob's queue**, not a card |
| 2 | what hazards are unattended | `find_orphaned_hazards` | a `CONTRIBUTION_RANKING` card, 3 rows |
| 3 | risk of deferring this work order | `assess_deferral_risk` | **a refusal** asking for `work_order_id` |

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

- **`assessDeferralRisk` may not be registered at all.** Contract D refused it 422,
  `missing: mro:MaintenanceWorkOrder`, because `agent_fleet/ontology_service/iof_mro.ttl` is on
  disk and **not in the prime manifest** (`iof_mro` appears zero times in
  `setup/prime_databases.py`). Naming the IOF class in the engine was necessary and NOT
  sufficient. *If Q3 answers "unknown verb" or routes elsewhere entirely, this is why, and it is
  the eo lane's manifest row — not a safety defect.*
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

## What each failure shape MEANS — so a red is attributable

| symptom | owner | why |
|---|---|---|
| `instance not found` for HAZ-1003 | routing / slot-referent wiring | the provider is registered and not consulted |
| blank card, HUD says `payload-only` | prime | the `rendersAs` binding never reached the graph |
| named archetype, nothing drawn | cortex-ui | the binding resolved and the component did not render |
| `unknown verb` for Q3 | eo lane | `iof_mro.ttl` absent from the prime manifest |
| refusal renders as prose | cortex-ui | a designed refusal lost its shape on the way to the screen |
| a 5xx anywhere | **stop** | this engine returns `200` with `refused: true`; a 5xx is discarded unread by the supervisor and means something upstream of the engine |

## Reporting

Score each question **drawn / task_created / slot_required / red**, and for a red name the owner
from the table above rather than "safety broke". Record the fleet revision and sha — a sheet
assuming a rev that has rolled is measuring something else.
