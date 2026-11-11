# Dispatch: manufacturing traceability and test evidence

```
from: the architect, via Chris
date: 2026-11-11
supersedes: the earlier draft "Dispatch 2 — iagent: manufacturing test &
            traceability engine and navigator" (do not act on that draft)
starts: after the 0.4.85 cut (Thursday 11-12 23:00Z); the ADR may be drafted
        from Friday. Nothing here rides 0.4.85.
```

## 0. What this is

A read-only engine and a cortex navigator over manufacturing data: as-built
units, their genealogy, and their test results. It serves three decisions:

1. **Can this unit ship?** Its test evidence, every number cited to its source.
2. **How far does a problem reach?** From any set of units, everything they are
   installed in, up to the end item.
3. **Is the process healthy?** Population views, out-of-family units, yield.

A reference mockup exists. It is illustrative only: use its interaction model
(start from a part number, pick serials, see tests, see a unit against its
population), not its names, styling, data or "flag rework" behaviour.

### Standing rules (every lane)

- **Nothing customer-shaped in shipped code or committed files.** Sources are
  named by row (`pdm`, `mes`, `test_repo`), never by vendor product or internal
  system name. Kinds, verbs' vocabularies, categories, out-of-family rules,
  trackers, export profiles and part-to-program mappings are rows. The sample
  overlay is synthetic (part `PN-1000-A`, serial `SN-0001`, program
  `SAMPLE-PROGRAM-A`).
- **Read-only against every system of record.** Nothing changes status anywhere.
  A review request is an iagent case (ADR-0069 pattern), and the UI says so.
- **Identity from the bearer token only.** A service identity on a person-scoped
  verb is refused 422 `no_person`.
- **Tests are seals:** each behaviour has a case and a control that differ in one
  thing, and each seal is shown to fail when the behaviour is broken.

## 1. The data layer is the finance pattern

The engine reads data exactly the way engine-fin reads `ev_fixture`. Same
mechanism, same code where it already exists, no second design.

1. **Contracts as data (ADR-0066).** Each dataset has a contract file in
   `contracts/` (one file per dataset, e.g. `contracts/mfg_unit.yaml`). A
   contract declares columns with types and roles, the key, `determined_by`
   dependencies (fin #357), classification per column (ADR-0064 dimensions; an
   operator reference is personal data, omitted unless the caller is entitled),
   and the source id used in citations.
2. **Refusals come from the contract, not reader code.** `wrong_type`,
   `duplicate_key`, `not_determined_by`, and a dataset missing a declared column,
   each with a message that names columns, never values. **The contract reader
   from fin #357 is lifted into one shared module** and both engines use it. No
   copy.
3. **Every measure or verb row names its contract** (`contract: <id>`) and is
   checked against it at load. A row reading an undeclared column is refused at
   load, not at query time.
4. **The asset of record is the catalog dataset** under its physical platform
   URN, as `ev_fixture` is. The deployment's platform is a value, not code.
5. **Two gates, as finance has:** an asset grant (reader on the dataset,
   `asset_grants.yaml`, grantor `seed` in the sample) and program membership
   (`program_members.yaml`), with part-to-program mapping as pattern rows.
   Unmapped part = deny. Topaz down or erroring = 503, never empty. The allowed
   scope is pushed into the query before any grouping or counting.
6. **Reads go through the gateway and broker under a ticket.** No raw warehouse
   connection from the engine. Every answer carries data provenance: dataset URN,
   as-of, and the ticket (`ticket_id`, `issued_at`, `as_of`), as fin does after
   dag-tools 0.13.0.
7. **Every row cites its source:** `<source>:<record_id>` with `extracted_at`, so
   any number on screen is traceable to its record and its age.
8. **Sample and refusal fixtures** are materialised by dag-tools for sandbox, as
   the EV fixture and refusal assets are: one clean fixture at realistic volume,
   plus one refusal asset per refusal kind.

### Datasets

The table names are dag-tools' (its `mfg_trace` spec and contract template).
Two files, two jobs: dag-tools' **template** is its published interface (the
columns its derive package reads); invincible-agent's **registered contract**
in `contracts/` is what the engine enforces, a superset of the template (add,
never drop or rename), checked in iagent CI against the template at a pinned
dag-tools sha. Engines read the `_current` views. A test parameter is
identified by `step_path` + `parameter_name` + `units`, never by name alone.

| dataset | key | what it holds | consumed in |
|---|---|---|---|
| `dim_part` | part_number, revision | part master: description, category, serialized, excluded | phase 1 |
| `serial_unit` | part_number, serial_number | one row per built unit: build dates, derived status, first-pass flag | phase 1 |
| `as_built_edge` | parent (pn, sn), child (pn, sn), valid_from | installation links with `valid_from`/`valid_to` and the origin of each (source event or snapshot comparison); `is_as_built` and `is_current` are derived views | phase 1 |
| `as_built_closure` | ancestor, descendant | closure over current and as-built links | phase 1 |
| `test_result` | result_id | one test run on a unit: station, outcome, attempt sequence, latest/first flags | phase 1 |
| `test_measurement` | result_id, step_path, parameter | measured value, units, limits, status; ordered for part + parameter + time | phase 1 |
| `test_catalog` | part_number, step_path, parameter | distinct tests and parameters with counts and units | phase 1 |
| `ingest_status` | source | last successful load per source | phase 1 |
| `bom_edge`, `bom_closure` | per dag-tools' contract | design structure | built now, consumed after the phase 1 verbs |

**Installation links are validity-shaped** so that one table serves as-built
now and as-maintained later: maintenance install/remove events append to the
same links. Derived fields (status, first-pass, latest attempt) are computed
upstream by dag-tools and declared in the contract; the engine does not
re-derive them. Contract types include `timestamp` (UTC) and `date`.

**Source names.** dag-tools adapters may be named for the API they speak.
Everything above the adapter (contracts, citations, engine, UI) uses source ids
from rows (`pdm`, `mes`, `test_repo`).

## 2. Lanes

### dag-tools owner — the producer

- Materialise the datasets above per the approved `mfg-trace` spec, through
  `DltPipelineComponent` (source kind by `source_config.type`). Your template
  stays your published interface; iagent checks its registered contract
  against it at a pinned sha.
- Test steps are loaded for all terminal results (`all_terminal`), so the
  population views include passing measurements.
- `as_built_edge` carries validity: source removal history where the source has
  it, otherwise changes observed between loads recorded as validity periods from
  the first load on, each marked with its origin.
- Publish each to the catalog under its physical platform URN, with lineage to
  its source.
- The sandbox fixture: synthetic, realistic volume (enough units and
  measurements to measure latency honestly), including one removal and
  replacement so as-built and current differ, and one unit installed in a parent
  the sample viewer cannot see. Plus one refusal asset per refusal kind.
- The contracts are owned by invincible-agent. If a contract asks for something
  the sources cannot supply, packet Lane 1; do not change the contract on your
  side.

### invincible-agent Lane 1 — ADR, contracts, registration

- **ADR at the next free number, Proposed**, written for a program reader first:
  the three decisions, the finance data pattern, verbs, authorization,
  provenance, what is not done (no writes to systems of record, no personal data
  by default), phases.
- **Rule genealogy disclosure in the ADR.** A unit the viewer cannot see is
  withheld, consistent with the task ruling. Whether the viewer is told that the
  tree is incomplete (without the hidden unit's identity) is your proposal; I
  rule it.
- The registered contracts in `contracts/`, a superset of dag-tools' template,
  validated by `validate_policy`, with a CI check against the template at a
  pinned dag-tools sha. The reader accepts the template's multi-document form
  and gains `timestamp`, `date` and `array<string>` in the same change as
  dag-tools.
- Name the engine's lane (a new lane, not one of the busy ones) and the engine.
- Capability rows, census rows and gating-manifest entries for each verb.
- Map the verbs to the `product_structure` ontology slice (Part, `component_of`,
  Configuration as_built), so a later graph projection changes the read path,
  not the verbs. One Part node per part number, not two.

### fin — the shared contract reader

After #357 merges (post-cut): lift the contract reader, its load check and its
refusals into one shared module. engine-fin moves onto it with no change in
behaviour (its seals pass unchanged). Then the new engine imports it.

### The new engine lane — the engine

All verbs read-only, person-scoped, filtered per record, every row cited, every
answer carrying data provenance.

**Phase 1 verbs** (names follow the fleet's verb naming):

| verb | serves |
|---|---|
| `search` | part number, serial, description, test name; grouped by kind |
| `asBuiltRegister` | units of a part, with filters and a `rollup` (counts by status for the filtered set), paged |
| `unitGenealogy` | one unit's chain up to its end item and its children down; current or as-built |
| `containment` | for a **set** of units: every assembly and end item containing them, up to the top, with counts per level |
| `testsForUnits` | the selected units' results and measurements, latest attempt by default |
| `testCatalog` | distinct tests and parameters for a part, with counts (backs "select all 28V ripple results") |
| `measurementSeries` | one parameter across the part's whole population over a date range (default 7 days), selected units highlighted, limits (stepped if they changed), out-of-family flags |
| `measurementStats` | n, mean, median, std dev, min, max, % out of limits, Cp/Cpk and Pp/Ppk when both limits are numeric; says which statistic is suppressed and why |
| `sourceFreshness` | last load per source, for the UI footer |

**Out-of-family** is declared, not coded: rule rows (which run rules, window,
minimum population) per part scope, applied in `measurementSeries` and shown as
a flag on the register. A flag names the rule that fired. Default sample rules:
a point beyond 3 sigma of its population, and a run of points on one side of
the mean.

**Requirements**

- Speed is the users' first requirement. Pagination everywhere, the contract's
  ordering paths, server-side downsampling above `max_points` that always keeps
  highlighted, out-of-limit and out-of-family points. Short-TTL caching keyed by
  the caller's program set and asset grants as well as the arguments; a cache
  never serves one caller's rows to a caller with different entitlements.
- Latency budgets (p95 on the scaled fixture): register page 300 ms, tests for
  10 units 500 ms, 7-day series 800 ms, search 200 ms, containment for 10 units
  500 ms. The perf lane measures them on sandbox; CI asserts correctness, not
  timing.
- Empty is not an error: 200 with a reason code (`no_data`, `not_visible`,
  `excluded_part`, `source_stale`).
- Test-data sources are pluggable by row, per part scope. Phase 1 has one.
  Adding a second is a contract, a row and an adapter, with no verb change.
- Curve or waveform tests without loaded data show "curve data not loaded" with
  the result's citation, never a fabricated curve.

**Seals:** per verb, the two gates (with and without grant; with and without
membership; unmapped part; Topaz down 503; Topaz error is not empty; service
identity 422), citation and provenance on every row, each empty reason. Current
versus as-built after the synthetic replacement. Containment through a unit the
viewer cannot see follows the ADR's ruling. Stats against hand-computed
fixtures, including suppression. Downsampling keeps the required points. Cache
isolation between two callers. Each contract refusal reaches the verb as a
refusal, not a 200.

### cortex — the navigator

Built from served declarations (verbs, categories, rules, profiles), with the
fleet's cards and design system.

- **Header:** search (Ctrl/Cmd+K, keyboard navigable, grouped by kind),
  source freshness from `sourceFreshness` (never a fake "live" badge).
- **Start from a part number.** No BOM needed in phase 1.
- **Register:** units with status, build date, parent link, child expander;
  current/as-built toggle; filters; the roll-up for what is in the list; an
  out-of-family badge naming its rule; multi-select.
- **Tests:** per selected unit, measured against limits with units and a
  citation; select by checkbox or by test name across all selected units;
  quick stats for the selection; roll-ups by filter.
- **Graph view:** one chart per parameter, population over the date range,
  selected units highlighted and labelled, limits drawn, out-of-limit and
  out-of-family points marked, synchronized scroll and zoom (toggle), hover
  shows serial, value, time and citation, click returns to the unit.
- **Containment:** from a selection, "where are these installed", as a list up
  to the end item.
- Skeletons and kept content while loading, prefetch on expand, debounced input.
  Every number reaches its citation and age. Keyboard operation throughout;
  status by text, not colour alone. Capture seals for each view.

### gov

Census and rulings-register rows for the verbs; confirm the personal-data
handling of the operator column against the dimensions rail.

### ca — only if needed

If the SDK lacks a typed paged answer with `rollup`, `reason`, citations and
data provenance, add it with the TS mirror. Otherwise nothing.

## 3. Later phases (record in the ADR; not this dispatch)

- **Phase 2:** the certificate as an export profile on the one export-profile
  mechanism (`accepts`, `grain`, version), operator shown only where entitled;
  trackers (yield, units built, units in test) as measure-verb rows the user
  chooses from; review requests on selected units as an ADR-0069 case for the
  role the overlay names, no write-back.
- **Phase 3:** design structure (BOM) datasets and panel; curve data; a second
  test-data source; projection into the product-structure graph, so obsolescence
  where-used and containment share one walk.

## 4. Acceptance walk (sample overlay, then a deployment)

1. Search a part number; its register loads within budget; filter to failed;
   the roll-up changes.
2. Select three units; their tests show; select all results of one test name;
   quick stats show.
3. Open the graph: the population over 7 days, the three highlighted, limits
   drawn, an out-of-family unit marked with its rule; widen to 30 days; scroll
   two charts together.
4. Click a highlighted point back to its unit; its chain shows; go to its parent.
5. Toggle as-built and current on the replaced unit; the child differs.
6. Containment for the three units lists their assemblies and end items.
7. As a viewer without the program: `not_visible`. Without the asset grant:
   refused. Topaz stopped: 503. A refusal asset: the contract's refusal, named.
