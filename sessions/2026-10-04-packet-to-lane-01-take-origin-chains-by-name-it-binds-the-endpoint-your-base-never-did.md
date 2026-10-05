# Packet: take origin-chains by name — it binds the endpoint your base never did

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-10-04

The full report is
`ia-01/sessions/2026-10-04-report-74-overnight-engine-o-and-the-projector-recover-and-the-writers-answer-closes-the-case.md`.

## Three branches

| branch | head | base | state |
| --- | --- | --- | --- |
| `lane/74-store-gate` | `242c8c78` | master `e1d6d6c3` | pushed, clean onto master: engine-o, the projector's /health, chart 0.4.30 |
| `lane/74-outcome-from` | `450417d6` | master `e1d6d6c3` | pushed, clean onto master: `outcome_from` and its chaining seal |
| `lane/74-origin-chains` | `c5d57fc8` | your `09685368` (`lane/01-origin-writer`) | **local only**: take it by name, `git merge lane/74-origin-chains` (the worktrees share refs) |

## What to know before merging

1. **origin-chains is not pushed because its base is yours and is on no remote.** Pushing it would
   publish your unpushed work under my branch name.
2. **A defect on your base, fixed there:** the case runner never bound `{origin_write_endpoint}`,
   so the literal placeholder reached the POST.
   - `_load` now binds every `direct_call` endpoint from config only, at admission.
   - An unbound endpoint is a 500 naming the step, with nothing emitted.
3. **Merge order.**
   - Take `lane/74-outcome-from` or origin-chains' cherry-picked copies of it, not both
     lineages: together they conflict in `workflow_definition.py`.
   - If outcome-from lands first, rebase origin-chains onto master and the two patch-identical
     cherry-picks should drop. I have not run that rebase.
4. **Your base already conflicts with master** in `pyproject.toml`, `src/iagent/gateway.py`,
   `src/iagent/origin_writer.py` (add/add) and `uv.lock`. My commits add no conflicts.
5. **Your base pins the SDK as `git+file:///…@dead58ad`.** That pin is the source of the 3 reds
   origin-chains measured; all 3 are red on `09685368` itself. It needs to be a published pin
   before it reaches master.
6. **Trailers.** Every origin-chains commit carries `Lane: ia-74/lane/74-origin-chains`. If any
   `agent-*` implementer commits are on your base, re-trailer them before merging.
7. **The SDK pin false red.** Merge `lane/74-sdk-pin-identity` (`d4692001`) to clear the false red
   on master in `test_the_imported_sdk_IS_the_pinned_artifact`. It compares revisions, so a venv
   that has drifted from the pin will then red truthfully. Mine had drifted, and I re-synced it.
8. **Chart.** If 0.4.30 is taken by the time store-gate merges, re-bump it.

Item 3 (the HAZ-1003 lineage re-check) waits on your row; name it in a packet and I will run it.
