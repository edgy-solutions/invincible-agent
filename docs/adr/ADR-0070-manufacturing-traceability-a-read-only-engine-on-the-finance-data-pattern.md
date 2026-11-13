# ADR-0070 — Manufacturing traceability: a read-only engine on the finance data pattern

**Status:** Proposed (Lane 1, 2026-11-13). This is design only: there is no code and no roll. It
answers the architect's mfg-trace dispatch of 2026-11-11 (`sessions/2026-11-11-dispatch-mfg-trace.md`,
#359), and it allocates the number 0070. 0066 is reserved for "contracts are data" (ADR-0065:18),
0068 is the edge-tier draft and 0069 is the accepted export template.
**Date:** 2026-11-13
**Deciders:**
- the architect, for the verbs, the disclosure rule and the open questions in section 10;
- gov, for the rails, the census and the personal-data handling of the operator column;
- the program's manufacturing owner, for the vocabularies, rules and part-to-program rows a deployment
  supplies.

**Related:**
- iagent: ADR-0066 (provisional, not yet a record). Contracts are data, and this record adds the
  third to tenth contract files.
- iagent: [ADR-0064](ADR-0064-classification-propagates-through-derivation.md). Per-column
  classification; the operator reference is personal data.
- iagent: [ADR-0065](ADR-0065-obsolescence-is-a-process-pcn-pdn-notices-are-its-intake.md). The
  `ps:configuration` axis. Its `as_built` value has no source yet, and this record supplies the first one.
- iagent: [ADR-0056](ADR-0056-fracas-phase-1-what-failed-on-this-part-across-programs.md). The
  precedent for a read-only, part-scoped `mesh:` verb.
- iagent: ADR-0069. The one export-profile mechanism; the certificate rides it in phase 2.
- dag-tools: the `mfg_trace` spec and its contract template
  `examples/mfg_trace/contracts/mfg_trace.yaml`, at a pinned tag.

---

## For a program reader

**What it is.** It is a read-only view over the units a program has built. It shows what each unit is
made of, where it is installed, and how it tested. It answers three questions:

1. **Can this unit ship?** It shows the unit's test evidence, measured against limits. Every number
   links back to the record it came from and says how old that record is.
2. **How far does a problem reach?** Start from any set of units, for example a lot with a bad
   capacitor. It lists every assembly and end item those units are installed in, up to the top, with
   a count at each level.
3. **Is the process healthy?** It shows one measurement across a part's whole population over a date
   range. The units you picked are highlighted, the limits are drawn, and out-of-family points are
   flagged, each flag naming the rule that fired. Yield and capability statistics come with it.

**How a person uses it.** Search a part number, then open its register of built units and filter it.
Select some units and look at their tests. Then open a measurement across the population, click a
point to get back to its unit, and follow the unit up to its end item.

**What it never does.**
- It writes nothing to any system of record and changes no status anywhere.
- A review request on a unit is a case in this platform, and the screen says so (phase 2).
- It shows no operator or other personal data unless the viewer is entitled to it.
- It never draws a curve that was not loaded.
- It never shows a unit the viewer may not see. Section 4 says what the viewer is told instead.

**Why it is safe to extend.** It reads data exactly the way the finance engine already does: the same
contract files, the same refusals, the same two gates and the same provenance. A second test-data
source is a contract, a row and an adapter. No verb changes.

---

## 1. The data layer is the finance pattern, with no second design

The engine reads its datasets the way engine-fin reads `ev_fixture` (#357, released in 0.4.88).

1. **One contract file per dataset** in `contracts/`, for example `contracts/mfg_serial_unit.yaml`.
   A contract declares:
   - columns, each with a type and a role;
   - the key;
   - `determined_by` dependencies;
   - classification per column (ADR-0064 dimensions);
   - the source id used in citations.
2. **Refusals come from the contract, not from reader code.** The four refusals are `wrong_type`,
   `duplicate_key`, `not_determined_by` and `missing_column`. Each message names columns, never
   values.
3. **One shared reader.** fin lifts #357's reader into `agent_fleet/utils/dataset_contracts.py`, as a
   pure move. engine-fin and this engine both import that one module, and a copy in either one is red.
   fin's packet of 11-11 has the seals.
   - The order was ruled on 11-11: fin does the lift, then dag-tools tags PR B. Then fin's PR adds
     `timestamp`, `date` and `array<string>` and moves the CI pin to the template, in one change.
   - Lane 1 does nothing on the reader or the pin.
   - `array<string>` is one token; there is no general `array<T>`.
4. **Every verb row names its contract** (`contract: <id>`) and is checked against it at load. A row
   that reads an undeclared column is refused at load, never at query time.
5. **The asset of record is the catalog dataset** under its physical platform URN, as `ev_fixture`'s
   is. The platform is a value in the deployment, not code.
6. **Two gates, as for finance:**
   - an asset grant (reader on the dataset, `asset_grants.yaml`, grantor `seed` in the sample);
   - program membership (`program_members.yaml`), with part-to-program mapping as pattern rows.

   An unmapped part is denied. If Topaz is down or erroring, the answer is 503, never empty. The
   allowed scope is pushed into the query before any grouping or counting.
7. **Reads go through the gateway and broker, under a ticket.** The engine has no raw warehouse
   connection. Every answer carries data provenance: the dataset URN, the as-of, and the ticket
   (`ticket_id`, `issued_at`, `as_of`).
8. **Every row cites its source** as `<source>:<record_id>`, with `extracted_at`. Source ids are rows
   (`pdm`, `mes`, `test_repo`). Vendor names stay in dag-tools' adapters and raw tables.

**Registered contract versus template.**
- dag-tools' template is its published interface. The registered contract in `contracts/` is what
  the engine enforces.
- The registered contract is a superset of the template: columns may be added, but never dropped or
  renamed, and no type or grain may change.
- iagent CI checks it against the template at a pinned dag-tools tag. That check reads the template's
  multi-document stream. The engine's loader keeps reading one file per dataset (fin's question 2,
  confirmed here).

## 2. Datasets and keys

The keys are the template's, as settled by the architect on 11-11. The engine reads the `_current`
views. A test parameter is grouped by `step_path` + `parameter_name` + `units`. That tuple is never a
row key, because a looping test repeats it within one result.

| dataset | key | holds | phase |
|---|---|---|---|
| `dim_part` | `part_number, revision` | part master: description, category, serialized, excluded | 1 |
| `serial_unit` | `part_number, serial_number` | one row per built unit: build dates, derived status, first-pass flag | 1 |
| `as_built_edge` | `parent_pn, parent_serial, child_pn, child_serial, valid_from` | installation links with `valid_from` / `valid_to`, `interval_origin` (`source` or `observed`) and `valid_to_precision_s` | 1 |
| `as_built_closure` | `scope, ancestor_pn, ancestor_serial, descendant_pn, descendant_serial` | the closure, once per scope (current, as built) | 1 |
| `test_result` | `result_id` | one test run on a unit: station, outcome, attempt sequence, latest and first flags | 1 |
| `test_measurement` | `result_id, step_id, parameter_index` | measured value, units, limits and status | 1 |
| `test_catalog` | `part_number, program_name, step_path, parameter_name, units` | the distinct tests and parameters, with counts | 1 |
| `ingest_run` | `source_system, run_id` | one row per load | 1 |
| `ingest_status` | `source_system` | `last_success_at`, `last_attempt_at`, `last_error_class` | 1 |
| `bom_edge`, `bom_closure` | per the template | the design structure | 3 |

**Installation links are validity-shaped.** One table serves as-built now, and as-maintained later,
when install and remove events append to it.
- `valid_to_precision_s` is accepted. An observed removal is only as precise as the load interval,
  and the row says so.
- Derived fields (status, first pass, latest attempt) are computed upstream and declared in the
  contract. The engine never re-derives them.

**`determined_by`, ratified as dag-tools proposed:**
- on `test_measurement`: `part_number`, `serial_number` and `program_name` are determined by
  `result_id`;
- on `serial_unit`: `revision` is determined by `part_number` + `serial_number`.

**Sample fixture inputs, ratified as dag-tools proposed:**
- `PN-1000-*` and `PN-1100-*` map to `SAMPLE-PROGRAM-A` (the viewer's parts; end item `PN-1000-A`).
- `PN-9000-*` maps to `SAMPLE-PROGRAM-B`. A `PN-1100` unit is installed in a `PN-9000-A` unit, so the
  viewer meets a parent they cannot see.
- The fixture has one removal and replacement, so as-built and current differ.
- There is one refusal asset per refusal kind. All four plant on `test_measurement`, each with exactly
  one defect.

## 3. Verbs, transport, envelope and declarations

**Phase 1 verbs.**
- All are read-only and person-scoped. A service identity is refused with 422 `no_person`.
- All are filtered per record, cite every row, and carry data provenance.
- Verb names are one fleet namespace (`mesh:<verb>`, as ADR-0056's `mesh:whatFailedOnThisPart`).
  The dispatch's `search` is therefore `mesh:mfgSearch`.

| verb | serves | reads |
|---|---|---|
| `mesh:mfgSearch` | part number, serial, description, test name; grouped by kind | `dim_part`, `serial_unit`, `test_catalog` |
| `mesh:asBuiltRegister` | units of a part, with filters, paging and a `rollup` (counts by status for the filtered set) | `serial_unit`, `as_built_edge` |
| `mesh:unitGenealogy` | one unit's chain up to its end item and its children down; current or as built | `as_built_edge`, `as_built_closure` |
| `mesh:containment` | for a **set** of units, every assembly and end item containing them, with counts per level | `as_built_closure` |
| `mesh:testsForUnits` | the selected units' results and measurements, latest attempt by default | `test_result`, `test_measurement` |
| `mesh:testCatalog` | the distinct tests and parameters for a part, with counts | `test_catalog` |
| `mesh:measurementSeries` | one parameter across the part's population over a date range (default 7 days); selected units highlighted, limits stepped where they changed, out-of-family flags | `test_measurement`, `test_result` |
| `mesh:measurementStats` | n, mean, median, standard deviation, min, max, % out of limits; Cp/Cpk and Pp/Ppk when both limits are numeric; each suppressed statistic named, with the reason | `test_measurement` |
| `mesh:sourceFreshness` | the last load per source, for the footer | `ingest_status` |

**Out-of-family is declared, not coded.**
- Rule rows give the run rules, the window and the minimum population, per part scope.
- The sample's rules are a point beyond 3 sigma of its population, and a run of points on one side of
  the mean.
- A flag names the rule that fired.

**Transport (cortex question 1).**
- There is one BFF route shape: `POST /mfg/{verb}`, a thin relay on the precedent of
  `/finance/measure/{fn}`.
- It forwards the real caller's bearer and authz_id, and the engine decides visibility. The BFF adds
  no scoping of its own.
- It is typed in the OpenAPI, so the request and response seals and the transport guard bind.
- It gets one gating-manifest entry, class `delegates`.
- The canvas pipeline is not used: it cannot page, and it cannot meet a 300 ms register page.

**One envelope for all nine verbs (cortex question 2).** One envelope means one reader in cortex.

```
{ rows: [...],                # each row: its fields + citation {source, record_id, extracted_at}
  next: <opaque cursor|null>, # passed back verbatim
  rollup: {...} | null,       # register and tests only
  reason: null | no_data | not_visible | excluded_part | source_stale,
  withheld: {...} | null,     # section 4
  suppressed: [{statistic, reason}],   # stats only
  downsampled: {from_n, to_n} | null,  # series only
  provenance: {dataset_urn, as_of, ticket_id, issued_at} }
```

- Empty is not an error. It is a 200 with a `reason` code.
- A contract refusal is a refusal, never a 200.
- If the SDK has no typed paged answer of this shape, ca adds it, with the TS mirror (the dispatch's
  "only if needed" item; cortex says it is needed).

**Served declarations (cortex question 3).** Under "config names the case" (10-30), cortex holds none
of these as constants. `GET /mfg/declarations` serves them from rows:
- the kinds (for grouping search);
- the unit statuses and their labels;
- the out-of-family rule names;
- the empty-reason codes;
- the test categories.

**The entry row (cortex question 4).**
- The navigator is offered by a served row, gated on the capability `mesh:mfgNavigate`, never on a
  group (11-07).
- Its shape is the existing served menu row's. The capability name is the only new thing.

**Requirements carried from the dispatch.**
- **Paging everywhere**, on the contract's ordering paths.
- **Server-side downsampling above `max_points`.** It always keeps the highlighted, out-of-limit and
  out-of-family points.
- **Short-TTL caching.** The cache key includes the caller's program set and asset grants as well as
  the arguments, and a seal shows that one caller's rows never reach another.
- **p95 budgets on the scaled fixture:**
  - register page, 300 ms;
  - tests for 10 units, 500 ms;
  - 7-day series, 800 ms;
  - search, 200 ms;
  - containment for 10 units, 500 ms.

  perf measures them on sandbox. CI asserts correctness, not timing.
- **Curve or waveform tests without loaded data** show "curve data not loaded" with the result's
  citation.

## 4. Authorization and genealogy disclosure

**Ruled by the architect on 11-11.** A node whose children include units the viewer cannot see
carries **`children_withheld: true`**, with no identity and no count.

How the verbs apply it:
- **`mesh:unitGenealogy`.**
  - Downward: a visible node with one or more invisible children carries `children_withheld: true`.
    The invisible children are absent, and so is everything below them.
  - Upward: the chain stops at the last visible ancestor, which carries `parent_withheld: true`.
    This is the same rule applied to the other direction; see question 10.3.
- **`mesh:containment`.**
  - A level's count counts visible units only.
  - A level that lost any unit to visibility carries `children_withheld: true`, with no count of
    what was withheld.
  - The envelope's `withheld` names the levels that did.
- **`mesh:asBuiltRegister`.** A unit row whose parent is invisible shows no parent link, and carries
  `parent_withheld: true`.
- **What is never done.** A withheld unit is never redacted to a placeholder row, never counted, and
  never named in a message.

Cortex shows a flag as text ("some installed units are not shown to you"). A silently short tree is
therefore never on screen, and nothing about the hidden unit leaks.

## 5. Provenance and as-of

- Every answer's `provenance` comes from the broker ticket, as fin's does after dag-tools 0.13.0.
- **Known gap.** `AS_OF_READERS` ships empty for ClickHouse. Until dag-tools adds a ClickHouse as-of
  reader, every answer carries `as_of_unavailable`. That is honest, and it is not a refusal.
- The as-of reader is dag-tools' change, proposed to the architect in its 11-11 packet.

## 6. The ontology mapping

The verbs map to the `product_structure` slice. A later graph projection (phase 3) then changes the
read path, not the verbs.

- **One `ps:Part` node per part number + revision.** It is the same node PDM's where-used already
  uses (ADR-0067: one identity per thing). `dim_part` never mints a second Part.
- **A serial unit is new.** The ontology has no class for it today. This record proposes `ps:SerialUnit`:
  - a material artifact, with `ps:builtTo` a `ps:Part`;
  - IOF's `prescribes`, read the other way;
  - its identity is `part_number` + `serial_number`.
- **An installation link is unit-level.** Its part-level projection is a `ps:PartUsage` with
  `ps:configuration ps:as_built` (or `ps:as_maintained` once removals come from maintenance events).
- **ADR-0065's as-built refusal stays.** Its where-used verb keeps refusing `as_built` until the phase 3
  projection lands. This engine answers unit-level questions; it does not answer that verb.
- **The ontology edit is its own PR** in phase 3. This record names the classes, so that phase 1's
  verb rows can carry them as output classes from the start.

## 7. Names

- **The engine** is `engine-mt` (manufacturing traceability), and its package is
  `agent_fleet/mfg_trace_agent/`.
- **Its lane is a new one**, `invincible-agent/lane/mt`, with the hooks row `ia-mt lane/mt lane/mt-*`.
  It is none of the busy lanes.
- **Registries.** An ADR does not allocate a component name. The name becomes real when the lane's
  first PR adds it to:
  - the four name registries;
  - the runbook;
  - `.githooks/lanes`.

  This record reserves the name only. No other row or file uses `engine-mt` or `mfg_trace_agent`
  today (checked at `d4e50dac`).

## 8. Rows Lane 1 lands, per verb

Lane 1 adds these rows in the engine lane's first PR, not before: a row for a verb that does not exist
is a dead row.
- A `policy/capability_grants.yaml` row for each verb, plus `mesh:mfgNavigate`. The sample grants go
  to the sample program's group, with grantor `seed`.
- **Census rows** (gov's rulings register and the walk census).
- **One gating-manifest entry** for `POST /mfg/{verb}`, and one for `GET /mfg/declarations`.
- **The registered contracts** in `contracts/`, validated by `validate_policy`. They wait for fin's types
  PR, which carries the CI pin.

## 9. What is not done, and the phases

**Not done, in any phase:**
- no writes to a system of record;
- no personal data by default;
- no vendor or system name above the adapter;
- no fabricated curve.

**Phase 1 (this record):**
- the nine verbs;
- the transport, the envelope and the declarations;
- the registered contracts;
- the sample fixture and its refusal assets;
- cortex's register, tests, graph and containment views;
- the acceptance walk (dispatch section 4), on the sample overlay and then a deployment.

**Phase 2:**
- the test certificate as an export profile on ADR-0069's mechanism (`accepts`, `grain`, version);
  the operator is shown only where entitled;
- trackers (yield, units built, units in test) as measure-verb rows;
- review requests on selected units as an ADR-0069 case for the role the overlay names, with no
  write-back.

**Phase 3:**
- the BOM datasets and panel;
- curve data;
- a second test-data source;
- the projection into the product-structure graph, so that obsolescence where-used and containment
  share one walk.

## 10. Questions for a ruling

1. **Is `scope` mandatory in the shared reader?** fin's packet of 11-11 asks this. `ingest_status`
   and `test_measurement` have no single column for the scope to be pushed into; the part arrives by
   join. **Proposed: (b).** `scope` becomes optional in the shared reader, and engine-fin's load check
   still requires it. fin's behaviour is unchanged, and this engine declares its scope join in the
   verb row.
2. **The verb names.** Proposed: `mesh:` plus the dispatch's names, with `search` renamed to
   `mesh:mfgSearch`.
3. **The upward half of disclosure.** The ruling names children. Proposed: a chain stopped at an
   invisible parent carries `parent_withheld: true` under the same rule (no identity, no count), and
   the register's parent link does the same.
4. **The operator column.** Proposed: it is omitted from every phase 1 answer. In phase 2 it appears
   only to a caller entitled on its ADR-0064 dimension. gov confirms the handling against the
   dimensions rail.
5. **The engine and lane names** in section 7.
