---
id:         suite-signal
status:     open
owner:      agent
blocked-on: 
closed-by:  
repo:       invincible-agent
summary:    master is not green. Measured census; recommended owner the telemetry agent.
---

# Suite-signal session — restoring `master` to a readable green

_Status is in this packet's YAML header — the single authority (ADR-0040). The prose
status line that stood here was removed when the header landed: two declarations of one
status is the two-homes defect, and a generated board reading the header would have
silently disagreed with a reader trusting the prose._
**Census taken:** 2026-08-07, as a by-product of triaging the transport-auth expand phase.

## Why this session exists

`master` is not green and has not been for the length of the enforcement arc. The cost is not
the red itself — it is that **every comparison either thread runs has to re-adjudicate the same
population by hand** before it can say anything about its own change. The transport-auth
triage paid that tax in full: separating environmental junk from pre-existing reds from an
actual delta took two full suite runs plus two worktrees, to establish that the change under
review had introduced *zero* new failures.

That adjudication is the thing this session retires. Every future comparison gets cheaper the
day it lands.

## Item 0 — the census (measured, not estimated)

Baseline `42a4afa`, clean worktree, full suite: **40 failed / 1071 passed / 138 skipped**.
After the expand phase (`fb82af6`): **39 failed / 1112 passed** — one pre-existing failure
FIXED by the SDK pin, +41 passing from new seals, **zero new failures**.

| count | suite | note |
|------:|-------|------|
| 23 | `tests/routing/test_classify_route.py` | largest single block; likely one root cause |
| 7 | `tests/routing/test_phrasing_independence.py` | adjacent to the above — check whether they share a fixture |
| 3 | `tests/test_endpoint_gating_manifest.py` | **see the flag below — this one is not ordinary debt** |
| 2 | `tests/test_capture_a_entitlement_source_recorded.py` | |
| 2 | `tests/routing/test_adr0019_engine_o_contract_a.py` | |
| 1 | `tests/test_llm_utils.py::test_get_smolagent_model_openai` | |
| 1 | `tests/routing/test_embed_contract.py` | E's `embed_query` is separately known-broken (`LLM_BASE_URL` unset) |
| 1 | `tests/test_mem0_extraction.py::test_memory_extraction` | collection ERROR, not a failure — triage separately |

Treat the counts as a starting map, not a work-list: 23 + 7 in one area suggests a small number
of causes, not 30 defects.

## FLAG — the gating-manifest three are the enforcement arc's own instrument

`test_endpoint_gating_manifest.py` asserts that the manifest describing the fleet's gating
posture matches the fleet's actual routes. **It has been red for the entire arc.** An
enforcement programme whose own map-vs-code check is failing cannot cite that check as
evidence, which is precisely the audit-by-name failure the manifest's 2026-08-07 amendment
exists to catch — occurring in the instrument itself.

These three were read *before* the `core/authz.py` retirement rewrote manifest rows, to test
whether they were asserting against the stale rows. **They were not.** The retirement left them
byte-identical, which is the discriminating result: they are missing declarations, not stale
ones.

### Filed finding: 12 routes present in source, undeclared in the manifest

| service | routes |
|---|---|
| `datahub_wrapper` | `POST /lineage_by_platform` |
| `gateway` (`src/iagent/gateway.py`) | `GET /instances_by_property`, `GET /notices/{notice_id}/provenance`, `GET /reviews/{workflow_id}/batch`, `POST /reviews`, `POST /triage_tasks` |
| `ontology_service` | `POST /instances_by_property`, `POST /operable_subjects`, `POST /policy_rules`, `POST /resolve_instance`, `POST /write_decision_record`, `POST /write_item_state` |

**Deliberately not absorbed into the retirement commit.** Each row needs an
identity / gate / class / justification, and classifying `/write_decision_record`,
`/policy_rules`, `/reviews` and `/triage_tasks` is security judgement about intended posture —
not cleanup to be done in passing by whoever happened to make the suite red. Several are
write endpoints on the decision plane.

Note what the drift means independently of the test: these 12 endpoints exist and the fleet's
own map does not know about them. The manifest's value is exactly its completeness.

## Line of record — supply chain, 2026-08-08

**No floating dependency anywhere in the repo; every pin tested; every guard proven inhabited.**

`_KNOWN_UNPINNED` is empty. Every git dependency carries an immutable ref (semver tag or full
40-hex SHA); every internal index dependency carries a version specifier; and each guard asserts
its own scope is non-empty, so none of them can retire by having its subjects migrate away.

The supply chain now holds the property the runtime earned this month: **nothing in it can change
without a diff someone chose to merge.** Worth stating because it is a *perishable* property —
one bare requirement string restores the old world, which is exactly what the guards are for.

## Named sub-item — the embed_contract violation

`tests/routing/test_embed_contract.py` is one of the census failures above, and the violation
has a code site: **`agent_fleet/neo4j_expert/service.py:357`**.

**Referenced here rather than filed as its own board line.** It is inside this session's scope,
and a separate line would be two homes for one item — the defect the board exists to prevent.
If it is ever worked independently of the suite sweep, it earns its own packet then; until
then, the board points at this packet and this packet names the site.

## Named sub-item — `test_promise_name_seal` is ORDER-DEPENDENT (found 2026-08-10)

Found while baselining the 11-site mint remediation, which is how it should be found: the
remediation's diff was innocent and the suite still went red, so the run was repeated with the
changes stashed.

**The measurement, both arms identical:**

| run | result |
|---|---|
| `test_promise_name_seal.py` **alone** | **3 passed** |
| same file inside a 27-file batch, **changes applied** | 2 failed, 255 passed |
| same file inside the same batch, **changes stashed (baseline)** | **2 failed, 255 passed** |

Identical with and without the diff, so the failure is pre-existing and the remediation is
exonerated. But the finding is not "a stale failure" — it is that **the verdict depends on what
ran before it.**

Two tests are affected: `test_grouped_awaited_name_equals_resolved_name` and
`test_default_convention_preserved_for_undeclared_steps`.

**The mechanism is `sys.path`, and there is a second symptom confirming it.**
`tests/test_restate_analyst.py` *fails to collect* when run in a small group
(`agent_fleet/restate_analyst/main.py` → `from orchestrator.auth import ...` →
`ModuleNotFoundError: No module named 'orchestrator'`) and collects fine in a large one — because
some other test file inserts `agent_fleet/restate_analyst` onto `sys.path` first. The same
ambient-path coupling explains both.

**Why this outranks its own severity.** A seal whose result depends on collection order is not
sealing — it can go green because of a neighbour and red because of a reorder, and neither carries
information about the promise-name property it exists to protect. That is the same failure class
as `[[seals-must-be-proven-to-bite]]`, one level up: there the question was whether a seal bites,
here it is whether its verdict means anything at all. **Fixing the ordering is not cosmetic
tidying — it is what makes the other 255 results trustworthy.**

Recorded here rather than as its own board line, for the same reason as the `embed_contract`
violation above: it is inside this session's scope.

**THE FIX IS KNOWN AND IS BLOCKED ON FILE OWNERSHIP, NOT ON ANALYSIS (2026-08-12).** The repair is
a `sys.path` insert of `agent_fleet/restate_analyst` — scoped to the importing helper rather than
done at module import, so it cannot mutate `sys.path` for the rest of the session and spread the
same ambient coupling it removes. The working form is already in
`tests/test_workflow_start_disabled.py::_main_module`, which needed exactly this to stop its
behavioural pins skipping.

It is unapplied because `test_promise_name_seal.py` is in another agent's working set. **Written
down so the next reader does not re-derive it** — "diagnosed, fix known, waiting on the file" and
"still being investigated" look identical from a red test, and only one of them should cost
another evening.

## THE CLASS HAS THREE MEMBERS NOW — tests coupled to their neighbours (2026-08-17)

**Filed by Agent A. The consolidation this packet owes is no longer a single stale failure; it
is a named class with three measured instances**, and the third shows the class is more
dangerous than "flaky".

| # | instance | coupling |
|---|---|---|
| 1 | the `dagster` stub (`5a2d5c9`) | `_install_stubs` is a **no-op when `dagster` is already in `sys.modules`**, so the stub applied or not depending on which test imported first. Its own comment: *"a stub that works by depending on another test having run is not a stub."* |
| 2 | `test_promise_name_seal` (2026-08-10, above) | passes alone, fails in a 27-file batch, **identically with and without the diff** |
| 3 | `test_da_outcome_distinguishable`'s two dagster tests (2026-08-17) | imported `DependencyDefinition` / `build_op_context` **inside the test bodies**, so they resolved against the stub `tests/routing/` installs from a fixture |

### Why the third one is the argument for consolidating rather than patching

**The `ImportError` was the LUCKY outcome.** Under that stub `job` and `op` are `lambda f: f`,
so no graph object exists at all. Had the fake carried the name, an assertion about the job
graph's *dependency edges* would have run against nothing and **passed** — a test proving the
run-level failure op is ordered after `generate_ui_payload`, green while measuring a stub.

**And the tempting fix was the poison.** The stub's stated rule is *"the stub must cover every
name the module imports"*, which reads as: add `DependencyDefinition` to the fake. That would
have satisfied the import and destroyed the test. The repair was the opposite — **bind the real
package at collection time**, removing the dependence instead of extending the fake.

### The correction this forces on how greenness is reported here

Agent A's earlier full-suite runs (`1344 passed`, `1342 passed`) **included both files and were
green** — only because something in that ordering imported real `dagster` first. So:

> **A green full suite was never evidence that its tests are isolated.** It is evidence that
> they pass *in one arrangement*, and the arrangement is not recorded anywhere.

That is [[a-green-check-proves-only-its-scope]] with a mechanism this packet should name: **the
scope was defined by whatever ran first.** Not by a directory list, not by a path shape — by
collection order, which no one states and nothing pins.

### What the consolidation is for

Not "fix three tests". The three share one cause — **module-level state (`sys.modules`, env,
`sys.path`) mutated by one test and read by another** — and the useful output is a rule plus a
guard, not three patches:

* a **stated policy** on stubbing shared heavy imports (fixture-installed stubs are visible to
  every later test in the process);
* a **run of the suite in a shuffled order** as the seal — the only check whose scope is
  *isolation* rather than *passing*. `pytest -p no:randomly` was needed to reproduce #3
  deterministically, which is itself the tell that ordering is load-bearing and unpinned.

**Owner note:** this packet is `owner: agent` and unclaimed at the consolidation level. Agent B
has now personally documented instances #1 and (with A) the class shape; A documented #2's
re-measurement and #3. Whoever claims it inherits three measured members and does not need to
find a fourth first.

## Method notes this session should encode

Two instrument defects were found the expensive way during the triage. Both are general.

**1. A baseline in a different filesystem state is not a baseline.** It is two measurements with
an uncontrolled variable. A `git worktree` has no untracked files; the main tree had
`agent_fleet/restate_analyst/.venv.wsl`, whose `lib64` symlink Windows cannot stat, crashing
three tree-walking tests with `OSError: [WinError 1920]` before they asserted anything. The
instrument's identity includes the tree state it runs in — the environmental form of the
same-mechanism-pair rule from the replay witnesses.

Note the DIRECTION it fooled us: the artifact appeared to indict the change under review,
because that is what the comparison was framed to find. **An uncontrolled variable does not
distribute its noise randomly; it lands wherever the question was aimed.** Confirmation bias
with a filesystem substrate.

*Repair:* worktree-to-worktree, named-set diffs (`comm` over sorted failure IDs), never
plausibility. Both predictions made in advance about which tests my change had broken were
wrong; the named-set diff was right.

**2. Exit codes are read from the command, never from a pipe's tail.** `pytest … | tail -3 &&
git commit` lets `tail`'s exit 0 mask pytest's failure, and a commit rides on a suite that
never passed. This shape has now bitten twice (also the sentinel-validator harness), which by
house rule makes the fix structural rather than a resolution to be careful:

```sh
pytest … > /tmp/out.txt 2>&1; echo "EXIT=$?"; tail -6 /tmp/out.txt
```

A bad process that happens to produce a good outcome is still a bad process — crediting the
outcome to it is how the process survives to fail when it matters.
