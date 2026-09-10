---
id:         no-ci-gate-on-the-suite
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    CI runs exactly ONE test file (tests/test_telemetry.py). The 1543-test suite has no CI gate at all — which is why nine members of the borrowed-green class accumulated undetected for months. The workflow exists at .github/workflows/suite-order-independence.yml. It ran TWICE on 2026-08-20 and both failed; nobody read the logs for twenty days. Diagnosed 2026-09-09 — four of five failures were already dead, the fifth (sibling SDK absent on the runner) is fixed. One dispatch away from its first data point.
---

# The 1543-test suite has no CI gate

**Measured 2026-08-17** while wiring the order-independence guard from `suite-signal`:
`.github/workflows/` contains `build-containers.yml` and `release-helm-charts.yml`, and the
only `pytest` invocation in either is

```yaml
python -m pytest tests/test_telemetry.py -q
```

**One file.** The other 165 test files and ~1540 tests are never run by CI.

## Why this is its own item and not a line in suite-signal

Because it is the *reason* suite-signal existed. Nine members of the borrowed-green class —
including **nine security-gate tests** that passed alone and failed in-suite, and a file that
could not pass standalone at all — accumulated for months with `master` red and nothing
reporting it. A guard nobody runs is documentation. Per [[naming-a-class-is-not-a-guard]],
the fix for suite-signal is not the policy doc, it is a run; and there is currently nowhere
for that run to happen.

## The draft, and why it is NOT wired to `push`

`docs/proposals/suite-order-independence.yml.draft` — three jobs:

1. **ordered** — the suite in collection order.
2. **shuffled** — `--random-order --random-order-bucket=module --random-order-seed=$SEED`,
   seed echoed so a failure is reproducible. Finds COUPLING.
3. **standalone** — every test file run by itself, failures annotated per-file. Finds
   PARASITISM. **Six of the nine members needed this one, not the shuffle** — they were
   invisible to any whole-suite run in any order.

It is `workflow_dispatch:` only, deliberately. **It has now executed twice — both red — and the diagnosis is below.**
A never-executed job wired to `push` either burns minutes on every commit or goes red for
environment reasons and trains people to ignore it — the flaky-red trap named in
`tests/security/test_effect_write_gate.py`'s own skip-guard docstring. Run it by hand, twice
green, THEN promote it to a gate.


## It HAS run, and nobody read the runs — diagnosed 2026-09-09

The line above said "never executed" for twenty days. It was wrong within an hour of being
written: two `workflow_dispatch` runs on 2026-08-20, **both failed**, and neither was
diagnosed. So the gate has not been blocked on effort — it has been blocked on **nobody
opening the log**.

    32326870277   2026-08-20T03:03Z   failure   3m56s
    32327820668   2026-08-20T03:19Z   failure   4m21s

Five failures in the second run. Four of them are already dead:

| failure | cause | state |
|---|---|---|
| `test_board_drift` x2 | shallow clone — `closed-by 96f2657` could not resolve | **fixed 49 min later** by `90ccaf9` (`fetch-depth: 0`) |
| `test_every_cited_docs_path_resolves` | `docs/architecture/endpoint-gating-audit.md` absent | **fixed** — the file exists today |
| `test_relative_markdown_links_resolve` | absolute `C:/Users/...` link targets in a tests/ doc | **fixed** — zero such targets today, and `test_no_markdown_link_targets_an_absolute_machine_path` now guards it |
| `test_sdk_is_present_for_this_contract` | the sibling SDK is not checked out on the runner | **was still live — fixed here** |

**The board-drift fix landed at 04:08Z, forty-nine minutes after the second failure, and the
workflow has not been run since.** Two of the five were therefore never real blockers; they
were a first-run environment bug and its immediate repair, with no third run to show it.

### The one that was structural, and why it is cheap

`tests/test_cross_repo_contracts.py` resolves the SDK as `_REPO.parent / "iagent-mesh-sdk"` and
**hard-fails** when it is absent. That is correct and must not be softened — its own docstring
says it: the other eight assertions in that file would vacuously pass against a repo that is not
there, and *skip-shaped failures are how a cross-repo pin quietly stops pinning*. Deselecting it
in CI would buy a green by removing the only thing that knows the contract was checked.

**`edgy-solutions/iagent-mesh-sdk` is PUBLIC**, so this needed no credential and no decision —
the default token clones it. All three jobs now check it out and move it into place, because
`actions/checkout` refuses a `path` outside the workspace and the workspace *is* the repo
directory, one level below where the test looks.

### What is actually left

**One dispatch.** Everything above is reasoned from logs and file history, not from a runner —
so the honest status is *"the known blockers are addressed"*, not *"it will pass"*. The three
open unknowns below (runtime, skip count, `uv sync --locked`) have still never been observed on
a runner, and a first green would answer all three at once.

The local suite at `224fd86` is **1 failed / 3009 passed / 183 skipped**, and the one red is
`test_chart_version_tracks_chart_content`, which clears with the next chart roll — so a runner
red on anything else is new information and worth reading immediately rather than in twenty
days.

**Why this matters more than it looks:** with no gate, an enumeration seal only fires when
someone remembers to run the suite. On 2026-09-09 `e66c063` landed two seals red on master
because the suite was not run — the fifth omission of one of them.

## Known unknowns before it can be a gate

* **Runtime.** Locally the ordered suite is ~6 min, and the standalone sweep is ~30 min at
  166 files x process startup. On a shared runner the third job is the expensive one; it may
  want to be nightly rather than per-PR.
* **Skips.** 167 tests skip locally for missing optional deps. On a clean runner that number
  will differ, and a job that silently skips 300 tests is a green that proves less than it
  appears — [[a-green-check-proves-only-its-scope]].
* **`uv sync --locked`** must reproduce the environment; unverified on a runner.

## Definition of done

The shuffled and standalone jobs have each run green on a GitHub runner at least twice, and
are then promoted from `workflow_dispatch` to `pull_request`. Until that happens the
order-independence guard has no teeth, and `suite-signal`'s result is a one-time cleanup
rather than a maintained property.
