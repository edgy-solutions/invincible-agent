to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-10
re: #336 and #329 merged; the two 0.4.85 pin moves are open as #342 (fin dag-tools v0.13.0) and #343 (SDK v0.9.18 + attestation rows)
supersedes: 2026-11-10-handoff-lane-gov-336-walkers-join-deciders-329-rebased-to-0-4-85.md

## Next step

1. Watch CI on **#342** and **#343**. Merging is not gov's. If one merges first, the other has a one-hunk
   conflict at the end of the 0.4.85 changelog. Both PR bodies tell the merger to keep both bullets. If
   asked to resolve it, check `gh pr view N --json state` first, then merge master in and append.
2. After each merges, remove its worktree. The precondition is the usual one: status clean, `git cherry`
   shows no `+`, and `is-ancestor` holds. Run `git worktree remove --force` in the background.
   - #342: `C:\Users\cnogr\git\wt\gov\fin-dag-tools`, branch `lane/gov-fin-dag-tools-v0-13-0`, head `57ff2030`
   - #343: `C:\Users\cnogr\git\wt\gov\pin-mesh-v0-9-18`, branch `lane/gov-pin-mesh-v0-9-18`, head `d2f82f97`
3. When a later SDK tag carries the ActionRecord corrections or the ImpactRow/DataProvenance reshape, that
   is a new pin PR. Neither is in v0.9.18 (see below).

## The dispatch, verbatim (11-10)

"gov: after #336 merges, merge master into #329 and resolve the changelog hunk; report the new head for
Lane 1. Then two pin moves, each its own PR on the 0.4.85 train:
1. engine-fin's dag-tools pin from v0.10.0 to v0.13.0, so fin can read the ticket through.
2. The SDK pin to v0.9.18 once ca releases it (attestation field, the ActionRecord schema corrections,
   ImpactRow provenance). The pcn/pdn "attestation: self" rows ride that PR."

## Done

- **#336 and #329 merged** before my master-merge pushes, so those pushes (`11419f92`, `6d3e15ef`) landed
  nowhere. Both were no-op merges, so nothing was lost.
  - #336 merged at `622bcb7f` (head `a616770f`).
  - #329 merged at `431d57bc` (head `54c161c0`). That head is the one Lane 1 asked for; there is no newer one.
  - On master: one 0.4.85 heading, 17 pyprojects on v0.9.17 before #343.
  - The worktrees `walker-deciders` and `pin-mesh-v0-9-17` are removed.
- **#342 (fin dag-tools v0.10.0 → v0.13.0):**
  - Changes: fin's pyproject and lock (edgy-dag-tools alone, `d8a23d3e` → `bed53b9c`), the root pyproject's
    note, and a changelog bullet.
  - Tests: `tests/finance` + lock coherence give 874 passed, 13 skipped, 1 xfailed. The xfail is fin's
    step-3 marker; step 3 is fin's own PR.
- **#343 (SDK v0.9.17 → v0.9.18):**
  - Changes: 17 pyprojects, 17 locks (`8d1ee304` → `2f47e9ee`, iagent-mesh alone in each), `meshSdkVersion`
    and its comment, the `option_deciders.yaml` note, and `attestation: self` on pcn and pdn.
  - Tests: 18 files give 1265 passed, 1 skipped, 3 xfailed.
  - The composed overlay registry gives pcn and pdn `self`; a third value is refused.

## Open: v0.9.18 is narrower than the dispatch

- The tag carries only the `attestation` field. The ActionRecord corrections are in no SDK tag or branch.
  The DataProvenance reshape waits on an architect ruling (ca's packet), and lane 74's #337 tripwire stays red.
- `promotion._declared_attestation` still returns `None`, so the pcn/pdn rows are not yet read. Wiring
  it is Lane 1's. Both points are in #343's body and changelog bullet.

## Still open from 11-09

- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is still `blocked` on the architect's call on the four held
  kind rows and the work-instruction card.
- `test_a_finished_run_with_no_leaf_waits_for_a_kind.py` has 2 pre-existing failures, reported to Lane 1.
