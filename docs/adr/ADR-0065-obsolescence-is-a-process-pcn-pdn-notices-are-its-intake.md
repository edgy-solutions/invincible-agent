# ADR-0065 — Obsolescence is a process; PCN/PDN notices are its intake

**Status:** Accepted, with one amendment (the architect, via Chris, 2026-11-07, on #299). The four questions this
record raised are ruled; see "Rulings". This is design only: there is no code and no roll. The number was
provisional in the architect's 2026-11-06 brief and is allocated by this record.
**Date:** 2026-11-07
**Deciders:** architect; the program's logistics owner for the vocabularies, options and thresholds a deployment
supplies; gov for the rails (who may decide, who may approve).
**Related:**
  - iagent: [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — the PCN/PDN worked example: a notice fans
    out per part, most parts end at relevance scoring, and the rest reach one grouped review. This ADR keeps that
    intake as it is.
  - iagent: [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) and
    [ADR-0051](ADR-0051-sustainment-safety-the-mesh-drafts-a-risk-and-refuses-to-accept-it.md) — the data plane and the
    product-structure vocabulary already in `setup/ontologies/product_structure_extension.ttl`.
  - iagent: [ADR-0064](ADR-0064-classification-propagates-through-derivation.md) — every table this process serves
    carries the classification of what it was derived from.
  - iagent: ADR-0066 (provisional, not yet a record) — contracts are data. The BOM contract is its second file.
  - iagent: [ADR-0067](ADR-0067-one-identity-per-thing-decided-in-openddil-adr-0056.md) — the reference ADR for
    openddil ADR-0056, one identity per thing.
  - openddil: `openddil-contracts/decisions/ADR-0056` at `2894f0c`, §8 — "A component reaches its OEM and its program
    through iagent's where-used graph, named by the architect as ADR-0065." This record is that forward citation.
  - standards, cited by concept, never copied: SD-22 and MIL-STD-3018 (DMSMS management), IEC 62402 and EIA-724
    (obsolescence and lifecycle status), S3000L (product structure and applicability), AP242 (the product model),
    EIA-649 (configuration management), S5000F (in-service feedback).

---

## For a program reader

A supplier tells you that a part you designed in is changing or going away. That notice is the start of the work,
not the end. The program needs answers to six questions, in order:

| step | the question | what the program gets |
| --- | --- | --- |
| 1. **Intake** | Which of our parts does this notice touch, and what does the system propose? | One grouped review per notice, with a proposed disposition per part. Parts on no active product end quietly, with a log entry. |
| 2. **Where-used** | Where is each affected part used, in which end items, on which programs, and how many? | An impact table per part: end item, program, quantity per end item, fielded population, stock on hand. |
| 3. **Risk** | Which of those uses matter, and how soon? | A ranked list. A part on a safety-critical path is flagged for the safety lane's check. |
| 4. **Resolution** | What do we do about it: buy ahead, use an alternate, buy from the aftermarket, redesign, or bridge? | A decision on a case, made by someone allowed to make it and approved by someone allowed to approve it. |
| 5. **Sizing** | If we buy ahead, how many? | A last-time-buy quantity with its working: population × quantity per × remaining life, less stock. |
| 6. **Reporting and change** | What has to be recorded and changed? | The decision record, a change artifact when the design changes, and the program's obsolescence report. |

**The first slice is steps 2 and 4: where-used, and the resolution workflow.** Step 1 exists today. Steps 3, 5 and 6
come after the first slice and are described here so the first slice does not have to be undone to make room for them.

Nothing in this process is one customer's shape. The status words, the options, the thresholds, who may decide and who
may approve are all rows a deployment supplies. iagent ships the types, the validators and the runner.

## Context: what exists today

Read on `origin/master` at `3949ade8`, 2026-11-07.

- **Intake exists.**
  - The notice classes are in `setup/ontologies/pcn_extension.ttl`.
  - The disposition rules are a seed decision table in `setup/ontologies/pcn_disposition_rules.ttl`, still marked
    unratified. Its rules propose three dispositions: `archive`, `dispatchLTB` and `dispatchQualification`.
  - The proposer evaluates those rules in `agent_fleet/restate_analyst/policy_evaluator.py`.
  - The grouped review is `mesh:PartObsolescenceReviewBatch` in `setup/ontologies/mesh_system.ttl`, per ADR-0029.
- **Product structure exists, in the design view only.**
  - `setup/ontologies/product_structure_extension.ttl` has `ps:Part` (derived from S3000L's PartAsDesigned) and
    `ps:PartUsage` (parent, child, `ps:quantity`, `ps:referenceDesignator`, `ps:applicability`).
  - Its own comment records the choice: "As-maintained (what is actually installed in serial-numbered units) is a
    genuinely different dataset we do not have and must not pretend to."
  - `ps:Part` carries no CAGE code today.
- **The decide rail exists, empty.** gov's `policy/option_deciders.yaml` (#276) is keyed `<workflow_id>.<option>`,
  ships with no rows, and is checked by `validate_policy`. Approvers stay on their own rail, the `task_grants.yaml`
  audience.
- **SDK shapes are open, not merged.** ca's `iagent-mesh-sdk` PR #2 (v0.9.16, untagged) carries `LifecycleStatus`,
  `LtbDecision` and `ImpactRow`. ca built `ImpactRow` from its own minimal reading, because no field-level text for
  where-used existed. Section 4 below is that text.
- **Not present:**
  - a where-used verb;
  - the `lifecycle_status` registry file;
  - the `obsolescence_resolution` workflow row;
  - any as-built or as-maintained configuration data;
  - any fielded-population or stock data.

## Decision

### 1. Obsolescence is a process with six steps, and a notice is one way in

The six steps are the table above. A notice from a supplier is the intake this record specifies. Other intakes come in
at the same step 1 and leave by the same step 2: a lifecycle feed, a parts-database alert, or an engineer's
declaration. Every intake ends in the same thing: a part with a `lifecycle_status` row, and a proposed disposition.

### 2. Step 1, intake: kept as ADR-0029 built it, plus one write

- The fan-out, relevance scoring, auto-disposition and grouped review stay as ADR-0029 describes them.
- **The disposition writer writes the part's `lifecycle_status` row in the same transaction as the rule match**
  (architect, 2026-11-06, ruling (c) on doc-tools' 11-05 packet). doc-tools declares nothing new.
- A disposition that dispatches work (`dispatchLTB` or `dispatchQualification` in today's seed) is the **trigger** of
  step 4. Intake's dispositions route a part. Resolution's options decide what happens to it. These are two
  vocabularies, and neither is derived from the other.

### 3. Field kinds

Both are registry rows (seed, generic), validated as plain strings against the served registry, the same pattern as
review shapes. Neither is an OpenAPI enum.

- **`lifecycle_status {status, source, as_of, successor?}`**
  - `status` is a value from `policy/registry/lifecycle_status.yaml`. The seed takes IEC 62402 and EIA-724 wording
    (`active`, `not-recommended-for-new-design`, `last-time-buy`, `obsolete`, `unknown`), and a deployment overlay
    extends it.
  - **Status absent means not assessed. Status null means assessed, and none known.** Both readers and writers keep
    the two apart.
  - `source` names the notice, feed or declaration the status came from. `successor` is the replacement part's
    identity, when one is named.
- **`ltb_decision {quantity, by, rationale, approved_by}`** is the action record of a last-time-buy resolution.
  The brief gives these four names and no definitions. They are defined when D is built.

### 4. Step 2, where-used: the verb and its impact table

- **The verb.** Given a part, walk `Part ← used in* ← EndItem ← program`, filtered by applicability, and answer one
  row per end item and program.
- **It takes a declared `configuration` argument** (ruling 2): `as_designed`, `as_built` or `as_maintained`. The
  default is `as_designed`, the EBOM that exists today. A configuration with no data for that end item is **refused
  loudly**, never answered as an empty table. `as_built` and `as_maintained` arrive later, through OpenDDIL's CM
  deltas and the PDM mapping.
- **Every row also states the configuration it was answered from** (ruling 2, the amendment). The argument says what
  was asked, and the column says what answered, so a design-view answer is never read as installed truth.
- **The row is `ImpactRow`** (ruling 4):

  | field | meaning |
  | --- | --- |
  | `end_item` | the end item's identity |
  | `program` | the program the end item is sustained under |
  | `component` | the part the question was asked about, by identity |
  | `qty_per` | the part's rolled-up quantity per end item, through every level |
  | `population` | the fielded count of that end item on that program |
  | `stock` | the part's stock on hand for that program |
  | `configuration` | the configuration the row was answered from |
  | `as_of` | when the data the row was answered from was current (ruling 3) |
  | `data_provenance` | where the row came from: dataset URN, as-of and ticket id, as on every served table. **Unmet** (ruled 2026-11-08): the broker's ticket carries no id and no as-of yet, so a served string carries the URN and `ticket: pending` |

- **Absent is not zero.** `population` and `stock` have no source today. A row with no source for them says so, and
  is never served as 0.
- **Program comes from the sustained-under relation, not from the BOM** (ADR-0056 §8). The product structure says
  what goes into what. Which program sustains an end item is declared per asset, so the program column is a join to
  that declaration.
- **Identity.** Every part, end item and program in a row is named by its identity, per ADR-0056 and ADR-0067. A part
  number with a CAGE code is an alias row of that identity. It is never a second node. This is how the brief's "one
  node, not two" holds: the IPD's Part and the product structure's Part resolve to one identity through their aliases.
- **Classification.** Each row carries the classification its inputs carry (ADR-0064).
- **It is a registered verb with generic nouns.** It is served to cortex as a table, through the mesh.
- **The fixture is a synthetic three-level BOM in this repository**, with a part used at two levels in one end item
  and in two end items on different programs. It needs both cases, because they are where a rolled-up quantity goes
  wrong.

### 5. Step 4, resolution: the `obsolescence_resolution` workflow

- **It runs on the same runner with the same seals as `maintenance_fault`.** It is a workflow row, not code.
- **Trigger:** an intake disposition that dispatches work, or a risk score over a threshold the deployment declares.
- **Options are on the decide step** of the workflow definition (`steps[id=…].options`), per gov's ruling 3 on #276.
  The brief names five: last-time buy, alternate, aftermarket, redesign and bridge. They come from a declaration,
  never from code.
- **Two rails, two acts** (gov's ruling 1 on #276):
  - who may choose an option is `policy/option_deciders.yaml`, keyed `obsolescence_resolution.<option>` (ruling 2);
  - who may approve is the `task_grants.yaml` approver audience.
- **The action record** is an `ltb_decision` for a last-time buy, or a change artifact when the design changes.

### 6. Steps 3, 5 and 6: after the first slice

- **Risk (step 3)** ranks the impact table's rows. Its inputs are the supply horizon from `lifecycle_status`, the
  population and stock from step 2, and a criticality the deployment declares. **saf's share is only the
  safety-critical check on a part**, in S3's pattern. Obsolescence is logistics, not safety.
- **Sizing (step 5)** computes a last-time-buy quantity and shows its working. It needs population, stock and a
  remaining-life figure. Until all three have sources, it does not run.
- **Reporting and change (step 6)** produces the program's obsolescence report and links the change artifact to the
  case. Its format is a deployment's, in the same way canvas templates are.

### 7. The ontology slice and the data contracts

- **The slice extends `product_structure_extension.ttl`** (ADR-0051's file; ruling 1). There is no new file and one
  Part node: `ps:Part`, with the IOF Core alignment added there. `ps:PartUsage` already carries the used-in relation
  with quantity, reference designator and applicability. The slice adds three classes to that file:
  `configuration {as_designed | as_built | as_maintained}`, `lifecycle_status` on a Part, and `ltb_decision`.
  Vocabulary is cited from AP242, S3000L, EIA-649 and S5000F, and never copied.
- **The data contracts** follow ADR-0066. The BOM contract is the second contract file, after fin's EV contract.
  Population and stock contracts come later, each when a source exists.

## Order

A (ADR-0066) → C (the ontology slice) → D (the registry rows) → E (the where-used verb), with this record alongside A.
All of it queues behind work already in flight.

| item | board | lane |
| --- | --- | --- |
| the decide rail, validator only | `01M6QDH5GS5KRZXF05P5BYGJ2V` (review, #276) | gov |
| options on the decide step | `01M6QHKVK50KZ10GJM77T5051F` | 74 |
| E, the where-used verb | `01M6QGKFZQ8VQQ0FT8P18Q98W0` (open) | 74 |
| C, the ontology slice | none yet | Lane 1 |
| D, the registry rows | none yet | Lane 1 |

## Rulings

The draft raised four places where the brief and what is on disk disagreed. The architect ruled all four on
2026-11-07, via Chris, on #299: questions 1, 3 and 4 as the draft recommended, and question 2 with one amendment.

1. **Where the ontology slice lives: extend `product_structure_extension.ttl`.**
   - The brief named a new `setup/ontologies/product_structure.ttl` over IOF Core, with `component_of`. The existing
     file already has `ps:Part` and `ps:PartUsage` over S3000L, and `ps:PartUsage` carries quantity, reference
     designator and applicability, which is `component_of`'s content.
   - **Ruled:** no new file, and one Part node. The `configuration`, `lifecycle_status` and `ltb_decision` classes
     are added to that file (section 7).
2. **What where-used answers from: both an argument and a column** (the amendment).
   - The brief filtered to `as_built` and `as_maintained`, and no as-built or as-maintained data exists. The draft
     recommended answering from the design view, with each row naming its configuration.
   - **Ruled:** `configuration` is an argument of the verb (`as_designed | as_built | as_maintained`, default
     `as_designed`), and a configuration with no data for that end item is refused loudly. It is also a column of
     every impact row (section 4).
3. **`as_of` in `lifecycle_status`.**
   - The brief to Lane 1 said `date`. Section D as quoted to doc-tools on 2026-11-05 said `as_of`, and ca's SDK
     shipped `as_of`.
   - **Ruled:** `as_of`, matching the contracts and ADR-0056.
4. **`ImpactRow`'s fields.**
   - ca's PR #2 shipped `{part_ref, used_by, quantity}`.
   - **Ruled:** `ImpactRow = {end_item, program, component, qty_per, population, stock, configuration, as_of,
     data_provenance}`, with `end_item` an identity (section 4). ca reshapes to it.
   - "Absent is not zero" stands as written.

## What this does not establish

- It builds nothing and rolls nothing.
- It supplies no customer's vocabulary, option list, threshold or criticality scale.
- It does not specify the risk model beyond its inputs, or saf's check beyond its scope.
- It does not specify the change artifact's format or the obsolescence report's format.
- It does not ratify the seed disposition rules in `pcn_disposition_rules.ttl`.
