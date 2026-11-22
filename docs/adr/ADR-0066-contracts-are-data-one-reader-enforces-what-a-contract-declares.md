# ADR-0066 — Contracts are data: one reader enforces what a contract declares

**Status:** Proposed (fin, 2026-11-15). This is a draft for Lane 1's review, and the architect
rules on it. It records decisions already ruled between 2026-11-10 and 2026-11-16 and the code
that carries them; it adds no new rule. Sections 3 and 4 describe PRs that are still open
(#426 and #409), and each section says so; section 6 (#393) and the template repin (#488, section 9)
are merged. It fills the number ADR-0065 reserved at its lines 18,
178 and 183, which `contracts/ev_fixture.yaml`'s header and `agent_fleet/utils/dataset_contracts.py`'s
docstring cite as "provisional".
**Date:** 2026-11-15
**Deciders:**
- the architect, for the rulings this record collects (2026-11-10, 11-11, 11-14, 11-15, 11-16);
- Lane 1, the reviewer, who registers each contract file;
- gov, for the personal-data handling (section 6) against the dimensions rail.

**Related:**
- iagent: [ADR-0064](ADR-0064-classification-propagates-through-derivation.md). Per-column
  classification; a contract marks a column personal, and the level is the deployment's.
- iagent: [ADR-0065](ADR-0065-obsolescence-is-a-process-pcn-pdn-notices-are-its-intake.md). It
  reserved this number.
- iagent: [ADR-0070](ADR-0070-manufacturing-traceability-a-read-only-engine-on-the-finance-data-pattern.md).
  The second engine on this pattern. Its §1 adds eight contract files and the
  registered-contract-versus-template rule (section 9); its §10 rulings 1 and 4 are sections 5 and 6.
- dag-tools: `dag_tools/contract_mapping/contract.py`, the producer's reader, and the
  `mfg_trace` template. dag-tools cites this record as "ADR-0066 item 1".
- iagent-mesh-sdk: `iagent_mesh/asset_contract.py`, a mirror (section 10).

## For a reviewer

- **The decision.** What a governed read accepts from an asset is written once, as a YAML file in
  `contracts/`, and read by name. The deployment chooses the file. One module,
  `agent_fleet/utils/dataset_contracts.py`, parses every contract and raises every generic
  refusal. Engines add their roles, never a second copy of the rules.
- **Already true on master:** sections 1, 2, 3 (five of its seven rules), 5, 6, 7 and the
  `inputs.dataset.contract` half of 8. Section 6 landed with #393.
- **True once the open PRs merge:** section 4 for the `FIN_DATASET_URN` read (#409), and section 3's
  two remaining rules (#426, which carries #409).
- **Not built:** the superset check against dag-tools' template at a pinned tag (section 9).
- **Ruled 2026-11-16, in flight:** the shared reader raises `null_value` (a column declared
  `nullable: false`) and `non_finite` (a `numeric` or `float` column) for every contract, and
  engine-fin's two retire into them (sections 3 and 4; #426). The template copy is repinned to
  dag-tools v0.17.0 (#488, merged; #428, the v0.16.1 repin, closed unmerged). Lane 1 registers the
  `mfg_trace` contract after #426 (section 9).
- **The questions for the architect** are in section 11. Questions 2 and 4 are ruled.

## 1. A contract is a file of data

- **Location.** A contract lives in `contracts/` in this repo. The image copies the directory
  (`.github/docker/Dockerfile.agent`: `COPY contracts/ /app/contracts/`), and
  `tests/finance/test_a_dataset_contract_loads.py` seals that line.
- **Directory resolution** (`contract_dir()`), in order:
  1. `DATASET_CONTRACT_DIR`, if set;
  2. the first `contracts/` found walking up from the module;
  3. `/app/contracts`.
- **Naming.** A contract id is `<set>` or `<set>.<table>`, matching `[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)?`.
  An id that looks like a path is refused.
- **One file per set.**
  - A contract `<set>` is the only document in `<set>.yaml`.
  - A contract `<set>.<table>` is one document among the set's documents in `<set>.yaml`. This
    is the multi-document form dag-tools' template is written in.
  - A file of several documents may not hold a bare `<set>` id. An id is unique within its file,
    and each id must match its file's stem.
- **Read by name.** `load_contract(id)` opens `<set>.yaml` and no other file. A contract written
  in another shape, for another reader, is never parsed here.
- **One parser.** `load_contracts(path)` is the only parser of the format in iagent. The engines
  and the template check both use it
  (`tests/test_the_contract_reader_reads_the_multi_document_form.py`).
- **A file is a sample or a deployment's own.** `contracts/ev_fixture.yaml` is `status: sample`,
  dag-tools' synthetic earned-value fixture. A deployment's contract is its own file, and engine
  code names no contract (section 8).

## 2. What a contract declares

**The keys the reader parses** (`_parse`):

| key | meaning |
| --- | --- |
| `contract_id` | the id, matching the file (section 1) |
| `columns[].name`, `.type` | each column once; a type is one of `string`, `numeric`, `integer`, `float`, `boolean`, `timestamp`, `date`, `array<string>` |
| `columns[].required` | a bool; a required column must be present in every read |
| `columns[].nullable` | a bool, true by default; `false` refuses a null in the column on every read (section 3; #426) |
| `grain` | the key: the columns one row is unique on |
| `scope` | the column a read filters to one value of, or `none` (section 5) |
| `dependencies[]` | `{by, determines}`: one value of `by` carries one value of each `determines` column |
| `rules` | a map of rule id to message (section 3) |
| `columns[].personal_data` | a bool, false by default (section 6; #393) |

`array<string>` is one token. There is no general `array<T>`.

**Refused at load,** so that a bad contract never reaches a read:
- a type outside the set, a column declared twice, or a non-bool `required` or `nullable`
  (`nullable` from #426);
- no `scope` key;
- `scope: none` beside a column named `none`;
- a grain, scope or dependency that names an undeclared column;
- a dependency that determines nothing but its own `by`;
- a grain column, scope or `by` that is not required;
- a `rules` value that is not a map.

**Carried, not read by iagent code.** These include `version`, `status`, `ratified_by`,
`dataset` (`urn`, `producer`, `storage`, `banner`), `period`, `vocabulary`, `status_period`,
`limits`, `cadence`, `tags`, `unit`, `produced_since`, `description`,
`constant_within` and `additive_over`. They document the asset for a reader and a reviewer. A
carried key enforces nothing: a review that relies on one must say that nothing checks it.

## 3. The reader enforces; rules live once

- **The contract declares, the reader enforces** (ruled 2026-11-10). The reader holds the generic
  rules and names no column of any contract.
- **The seven generic refusals** (`RULES`), each raised as `ContractViolation(rule, message)`:

  | id | refuses |
  | --- | --- |
  | `missing_column` | a required column, or a column the reading row names, is absent |
  | `wrong_type` | a column is not of its declared type |
  | `personal_data` | a reading row names a `personal_data` column the reading engine did not release (section 6; #393) |
  | `null_value` | a column declared `nullable: false` carries a null (#426) |
  | `non_finite` | a column declared `numeric` or `float` carries a NaN or an infinity (#426) |
  | `duplicate_key` | more than one row for one grain tuple |
  | `not_determined_by` | one value of a dependency's `by` carries two values of a column it determines |

  A message names columns, never values. `null_value` and `non_finite` were engine-fin's, raised
  only over the columns a read used; ruled 2026-11-16, the reader raises them over every declared
  column, and engine-fin's two retire into them (#426). On master until #426 merges, the reader
  raises the other five (`agent_fleet/utils/dataset_contracts.py`, `RULES`).
- **They apply to every contract** (ruled #378, 2026-11-14). A contract's `rules` block carries
  messages for them, and for an engine's own rules. Leaving a rule out of the block disables
  nothing.
- **A block cannot add a rule.** `unknown_rules(contract, also)` lists the ids in the block that
  neither the reader, the engine (`also`) nor the producer raises. An engine refuses a contract
  at its join when that list is not empty, because a rule that nothing raises would read as
  enforced.
- **Producer-checked rules** (`PRODUCER_CHECKED`: `interval_overlap`, `orphan_reference`; ruled
  #383). dag-tools checks them before it publishes. A block may name them, and no reader raises
  them. `duplicate_key` is the one name for a key violation.
- **No engine keeps a copy.** `tests/test_one_dataset_contract_reader.py` seals that engine-fin
  and the next engine import this one module.

## 4. Every read is held to the whole contract

- **Ruled 2026-11-10.** A read selects every column the contract declares that the asset carries
  (`check_contract_schema`). It then holds the rows to the contract's key and dependencies
  (`check_contract_rows`). It is not held only to the columns the engine happens to use.
- **Dataset-row reads:** true on master. A dataset measure row names its contract, and
  `read_dataset_rows` holds every read of the row's asset to it.
- **The `FIN_DATASET_URN` read:** true once #409 merges. Until then it holds its own constants,
  and `tests/finance/test_the_ev_contract_agrees_with_the_reader.py` keeps them in agreement with
  `ev_fixture`. #409 retires four engine-fin ids in favour of the shared ones:
  `duplicate_work_package_period` becomes `duplicate_key`; `program_name_not_unique`,
  `program_bac_not_unique` and `work_package_in_two_accounts` become `not_determined_by`.
- **A null is the contract's to declare** (ruled 2026-11-16; #426). `required` is presence;
  `nullable: false` is the value. A null in a column declared `nullable: false` refuses
  `null_value` on every read, whether or not the read uses the column, and a NaN or infinity in a
  `numeric` or `float` column refuses `non_finite` the same way. A column declared nullable (the
  default) may be null. Since the engine computes on every column it reads, an engine holds its
  roles to `nullable: false` at load: engine-fin's `_join_contract` refuses a dataset row naming a
  nullable column, and `contract_problems` a contract whose role columns are nullable.
  `contracts/ev_fixture.yaml` declares all 13 columns `nullable: false`. Until #426 merges, the
  reader ignores `nullable` and engine-fin checks nulls in the columns a read uses.

## 5. Scope is never optional

- **Ruled 2026-11-14** (ADR-0070 §10, ruling 1). Every contract declares its scope column. A
  contract with no single scope column says `scope: none`, and the reader refuses a missing key.
- **Under `scope: none`** no value filter applies. The read is decided on the asset grant alone.
- **Which values a caller may read** is the deployment's mapping, a row (for example
  `program_members.yaml`), never the contract's.
- **An engine whose reads need a scope refuses `scope: none` at its join,** as engine-fin does.
  An engine whose scope arrives by join declares that join in its verb row (ADR-0070 §10).

## 6. A personal column is withheld by default

On master since #393 merged on 2026-11-20 (ruled 2026-11-14, ADR-0070 §10 ruling 4).

- **A contract records a fact, not a level.** `personal_data: true` says a column identifies a
  person. The classification level, and who may see the column, are the deployment's. They are
  applied through its ADR-0064 dimensions on gov's rail and are never written in a contract.
- **Nothing every read needs may be personal.** A personal column may not be required, in the
  grain, the scope, or a dependency (`by` or `determines`). The broker may project it away, and a
  column every read needs cannot be withheld.
- **Withheld from the selection** unless the reading engine releases it
  (`check_contract_schema(..., released=)`). A row that names a withheld column is refused
  `personal_data`, one of the five ids in `RULES` on master (seven once #426 adds `null_value` and
  `non_finite`; section 3). A withheld column is still type-checked, because a dtype
  is schema metadata, not a value.
- **Phase 1 releases nothing.** No call under `agent_fleet/` passes a release, and a census seals
  that. Deciding a release from the caller's holds on the column's dimension is phase 2.

## 7. Roles are the engine's

- **The reader knows no roles.** A role is what an engine builds from a column: a level, a scope,
  a period, a status, a value.
- **An engine holds a contract to its roles at its join,** using the reader's load-time helpers
  `undeclared` and `not_of`:
  - engine-fin's dataset rows: `measure_verbs._join_contract`;
  - engine-fin's `FIN_DATASET_URN` read: `asset_inputs.contract_problems` (#409). It requires the
    nine role columns declared, required and typed; scope `program_id`; a grain within
    (`work_package`, `period`); and its three dependencies.
- **An engine's own refusal rules stay in the engine**, registered beside the reader's and passed
  to `unknown_rules` as `also`. engine-fin's, once #409 retires four of them and #426 two more,
  are `other_program_rows`, `period_outside_calendar` and `varies_within_path`.

## 8. The deployment names the contract

Config names the case (ruled 2026-10-30). No engine code names a contract id.

- **A dataset measure row** names its contract as `inputs.dataset.contract: <id>`, and the loader
  joins the two at load. An unknown contract, or one that does not carry the row's roles, is
  refused at load, never at query time. The sample and sandbox overlays under
  `policy/overlays/*/measure_verbs/` name `ev_fixture`.
- **The `FIN_DATASET_URN` read** names its contract as `FIN_DATASET_CONTRACT` (ruled 2026-11-15,
  #409). Boot refuses the URN without it, a contract that will not load, and one that lacks
  engine-fin's roles. `values-sandbox.yaml` sets `ev_fixture`. A work deployment needs its own
  contract file and the env before that image rolls there. The contract and the env are
  documented in `docs/contracts/finance-overlays.md` §5a.
- **A contract that stops loading under a running engine** is a 503 `asset_unavailable`, the same
  answer as a failed scan. The cause goes to the log.

## 9. Registered contract versus template

From ADR-0070 §1, restated here as the rule for every contract a producer publishes a template for.

- **The template is the producer's published interface.** The registered contract in `contracts/`
  is what the engine enforces.
- **The registered contract is a superset of the template.** Columns may be added. None may be
  dropped or renamed, and no type or grain may change.
- **iagent CI checks it against the template at a pinned producer tag,** with the one parser
  (section 1).
- **Not built yet.** On master the template is a copy, `tests/fixtures/dag_tools_mfg_trace/mfg_trace.yaml`,
  that the multi-document seal reads. No check pins a dag-tools tag, and no check compares a
  registered contract to its template. The check arrives with the first registered
  `mfg_trace` contract.
- **The superset covers the rules block too** (ruled 2026-11-16, with Lane 1). The registered
  `mfg_trace` contract declares `null_value`, `wrong_type` and `non_finite` in the PR that
  registers it, so it stays a superset of the template.
- **The order** (ruled 2026-11-16, second ruling; the pin moved on since). First the shared reader
  raises `null_value` and `non_finite` (#426). Then Lane 1 registers the `mfg_trace` contract:
  every table in the template, declaring the refusals the template declares, stacked on #426. The
  template copy's repin is done: #488 (merged 2026-11-20) pins it to dag-tools v0.17.0
  (`pyproject.toml`'s `edgy-dag-tools==0.17.0`). #428, the v0.16.1 repin, closed unmerged.
- **What the copy on master holds.** `tests/fixtures/dag_tools_mfg_trace/mfg_trace.yaml` is
  dag-tools v0.17.0 at `a85c5f99`, which the seal's docstring records as unchanged since v0.16.1.
  Loaded through master's shared reader (before #426), it gives:
  - 12 documents, including `conf_test_repo_result` and `conf_test_repo_step_parameter`;
  - `duplicate_key` in every document, and `key_not_unique` in none;
  - `unknown_rules` listing `non_finite` and `null_value` on `conf_test_repo_result`, and
    `null_value` on `conf_test_repo_step_parameter`.

  The tripwire in `tests/test_the_contract_reader_reads_the_multi_document_form.py` pins that
  union, `{null_value, non_finite}`, and that `duplicate_key` is named and `key_not_unique` is
  not. `wrong_type` is already one of the reader's five. dag-tools' plan emits the other two as
  producer-side tests (`not_null` → `null_value`, `non_finite` → `non_finite`), with the same ids
  engine-fin raises. Question 4 in section 11 asked which reader raises them for a registered
  contract; it is ruled (a), the shared reader (#426). When #426 merges, `unknown_rules` over the
  template is empty and the tripwire goes red by design: #426 flips it to the empty set.

## 10. Three readers of one format

| reader | role | what it checks |
| --- | --- | --- |
| `agent_fleet/utils/dataset_contracts.py` (iagent) | **authoritative** for every governed read | all of sections 2–6 |
| `dag_tools/contract_mapping/contract.py` (dag-tools) | the producer's tolerant reader (`extra="ignore"`) | the columns its derive package reads; it ignores the read-side keys |
| `iagent_mesh/asset_contract.py` (SDK) | a mirror for engines built on the SDK | `missing_column` and `wrong_type` only |

- **When they disagree, the iagent reader decides,** because it is the one that refuses a governed
  read. A contract the producer's reader accepts and the iagent reader refuses is not registered.
- **The producer-checked rules** (`interval_overlap`, `orphan_reference`) are dag-tools' to check
  before it publishes. This record does not say where in dag-tools that check lives.
- **A follow-up for the SDK's owner.** The SDK module's docstring says `ev_fixture` "names eleven
  refusals… uniqueness". Since #378 and #409 the contract carries messages only, and uniqueness is
  `duplicate_key` in the shared reader. The docstring should say what the mirror checks and point
  here.

## 11. Open questions, for the architect

1. **Should the SDK mirror converge or retire?** It checks two of the four rules. The options are
   (a) to vendor the iagent reader's checks into the SDK, so one engine's contract behaves the
   same on either side, or (b) to keep it schema-only and say so in its docstring. fin proposes
   (b) until an SDK engine reads a governed dataset.
2. **Who enforces `nullable`?** **Ruled 2026-11-16: the shared reader**, as fin proposed. It
   raises a generic `null_value` for a column declared `nullable: false`, in its own PR (#426),
   and engine-fin's `null_value` retires into it, the way the four ids did in #409 (section 4).
3. **Where does the superset check live?** In iagent CI against a pinned tag, as ADR-0070 §1
   says, or as a load-time refusal when a registered contract names its template. fin proposes CI
   only: a running engine should not depend on another repo.
4. **Who raises `null_value` and `non_finite` for a registered contract?** The 11-16 ruling has the
   registered `mfg_trace` contract declare them. A block cannot add a rule (section 3), so unless
   something raises them, `unknown_rules` lists them and an engine's join refuses the contract.
   There are three ways out:
   - **(a)** The shared reader raises both generically: `null_value` on a column declared
     `nullable: false`, and `non_finite` on a `numeric` or `float` column. They join `RULES`, and
     engine-fin's two retire into them, as four ids did in #409. This is question 2, widened.
   - **(b)** Add them to `PRODUCER_CHECKED`. This breaks the seal that no reader raises a
     producer-checked rule, because engine-fin raises both. It would also leave the read
     unenforced.
   - **(c)** The engine that reads these documents passes them as its own (`also`). No such engine
     exists yet.

   **Ruled 2026-11-16: (a)**, "for every contract", in its own PR before the repin (#426).

## Consequences

- **A new dataset is a file and a row,** not code. The second engine (engine-mt) adds eight
  contract files and no reader.
- **A rule changes in one place.** A refusal rule added to the reader binds every contract; an
  engine's rule binds that engine. A contract can never switch a rule off.
- **The 502 `rule` an answer carries is a shared id,** so a probe or a dashboard matches one
  vocabulary across engines.
- **The cost is a load-time gate.** A contract that drifts from an engine's roles refuses at boot
  or at the row's load, not on the first query. Operators see it earlier, and a work deployment
  must ship its contract file before the image that reads it.
- **The citations in ADR-0065 and the two file headers** still say "provisional". They are left as
  they are in this PR and are updated once this record is accepted.
