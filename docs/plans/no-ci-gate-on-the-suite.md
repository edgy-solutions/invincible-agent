---
id:         no-ci-gate-on-the-suite
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    CI runs exactly ONE test file (tests/test_telemetry.py). The 1543-test suite has no CI gate at all — which is why nine members of the borrowed-green class accumulated undetected for months. A workflow_dispatch-only draft exists at docs/proposals/suite-order-independence.yml.draft; it has never run on a GitHub runner.
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

It is `workflow_dispatch:` only, deliberately. **It has never executed on a GitHub runner.**
A never-executed job wired to `push` either burns minutes on every commit or goes red for
environment reasons and trains people to ignore it — the flaky-red trap named in
`tests/security/test_effect_write_gate.py`'s own skip-guard docstring. Run it by hand, twice
green, THEN promote it to a gate.

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
