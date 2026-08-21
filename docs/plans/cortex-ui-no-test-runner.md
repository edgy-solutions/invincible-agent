---
id:         cortex-ui-no-test-runner
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       cortex-ui
summary:    cortex-ui has NO test runner at all — no vitest, no jest, no `test` script, zero test files. Found 2026-08-20 while building the presentation contract slice. This is why ten hand-copied capability contracts could drift with nothing pinning them: the drift was not missed, it was UNOBSERVABLE. Sibling of no-ci-gate-on-the-suite, one repo over.
---

# cortex-ui has no test runner

**Measured 2026-08-20**, looking for somewhere to put a seal binding `ChartWidget`'s contract
to its component. `package.json` has no `test` script; `devDependencies` and `dependencies`
contain no `vitest`, `jest`, or `@testing-library/react`; and a recursive search for
`*.test.ts` / `*.test.tsx` under `src/` returns nothing.

## Why this is a board item and not a preference

**It is the mechanism behind the drift finding, not a separate wish.** The presentation
enumeration found ten `expected_fields` lists byte-identical between
`cortex-ui/src/registry/frontendCapabilities.ts` and
`agent_fleet/presentation_agent/capabilities.py`, with **no test pinning them equal** — and
the reason no test pinned them is that on the cortex-ui side there is nowhere for a test to
live. The two-masters defect was not overlooked by careful people; it was **unobservable from
one of its two homes.**

That makes this the sibling of [[no-ci-gate-on-the-suite]]: debt accumulating silently
because no instrument existed to see it. Same shape, one repo over. In `invincible-agent` the
suite existed and nothing ran it; here the runner does not exist at all, which is the more
complete version of the same absence.

## Why slice 1 did not solve it, and why that is adequate for now

`ff6d6e3` binds the contract to the component **structurally rather than by test**:

* `normalizeChartData` IMPORTS `CHART_ROW_REQUIREMENTS` — the component cannot enforce a
  threshold the contract does not declare.
* `expected_fields` is COMPUTED as `Object.keys(contract.fields)` — the name list is a
  projection of the contract, not a second source.

Both are enforced by `tsc`, which is a real gate (`tsc --noEmit` exit 0 is checked). So the
guarantee is type-enforced rather than test-enforced, and for THESE two properties that is
sufficient — a projection cannot silently drift from the thing it projects.

**What it does not cover** is behaviour: that `normalizeChartData` still returns
`kind: "single"` for one-categorical-plus-one-numeric, that the eight refusal reasons still
fire on the inputs they name, that a contract change produces the registration payload
someone expects. Those want a runner.

## Definition of done

A runner installed, a `test` script present, and the **contract bindings as its first
subjects** — the derived-vs-legacy assembly and the refusal vocabulary are the highest-value
first tests because they are the properties the whole presentation ruling rests on.

## Known unknowns before choosing

* **Which runner.** vitest is the default for a Vite project and needs no separate transform
  config; jest would need one. Not ruled here.
* **CI.** A runner nothing executes is [[no-ci-gate-on-the-suite]] repeated in a second repo.
  Whatever lands should be wired to run, and that decision belongs with the CI-gate item
  rather than being made twice.
* **Scope creep risk.** The temptation on installing a runner is to backfill tests broadly.
  The contract bindings are the ones with a live argument behind them; everything else is
  ordinary coverage and should be prioritised as such.
