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
