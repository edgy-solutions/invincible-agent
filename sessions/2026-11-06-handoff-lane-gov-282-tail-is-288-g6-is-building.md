# Handoff: lane/gov, 2026-11-06 (#282 merged, tail rides #288; G6 is building; G5 next)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-06

This supersedes `2026-11-06-handoff-lane-gov-276-merged-282-is-the-dimensions-ruling.md`. Its "Carried over" rows still stand except where this file changes them.

## The rulings since (via Chris, verbatim)

On #282's three readings (architect):

> "(1) one hierarchical dimension at most — yes, as ADR-0055 has it (one classification, many categories). (2) No: rows keep `ratified_by: owner` (house rule for every shipped row); `owner` on a dimension is who decides what its values mean — both fields, different questions. (3) File name fine. SDK fields: ca adds `options` on WorkflowDefinition steps and `level`/`max_level` on AssetContract in v0.9.16; packet to ca from you. The 15 moved items are assigned, not pending — start in board priority order: G6 (/me/entitlements carries capabilities and authz_id, with Lane 1's new item), then G5, then the rest. Lane 1 regenerates docs/BOARD.md."

Restated (Chris): "gov: G6 (/me/entitlements capabilities + authz_id field, with Lane 1), then G5 (RefusalEnvelope on MCP routes). #282's SDK asks to ca (options on steps; level/max_level on contracts)."

## State

| what | where | state |
| --- | --- | --- |
| #282 dimensions | merged `9a2ffc5d`, at head `5c8d57a1` | Two commits pushed after the merge missed it. |
| #288 tail | `lane/gov-282-tail`, head `79035e2b` | These are the can_decide item set to done and the `ratified_by` rework, cherry-picked onto `b71a6aa2`, plus the dimensions item listing #288. 160 passed; validator 0; board check 0. Open, for Lane 1 to merge. |
| G6 `01M6A9QDN15JXEWSZYYQ6VV6TG` | `lane/gov-me-entitlements-capabilities`, claim `d3688532` | Claimed. The implementer is building from the scratchpad spec `g6_spec.md` in worktree `scratchpad/dm`. Not yet committed. |
| G5 `01M6A9QDN17N491MVEMJR0NY52` | n/a | Next. "Declare the 401/403 RefusalEnvelope on every MCP-tagged route." |
| the rest of the 15 | board, lane `invincible-agent/lane/gov` | In board priority order after G5. |

## G6: what is being built

- `capabilities` on `GET /me/entitlements`: every `capability:<key>` object the Topaz directory serves on which the caller holds `can_invoke`, sorted. It is read from the server, never from `policy/capability_grants.yaml`.
- An unreadable directory or a failed check is the same two 503 arms as `droppable_kinds`; it is never a partial list. A blank `authz_id` gives `[]` with no call.
- It is an ingest-v1 minor bump (1.6.0 → 1.7.0), with a CHANGELOG entry and both OpenAPI documents regenerated. cortex-ui's generated `Entitlements` follows; packet cortex-ui once it is merged.
- Cortex already records the 10-30 ruling (`src/lib/reviewExport.ts`): "the signal is a `capabilities` list on `GET /me/entitlements`, Topaz-derived, carrying `ingest:exportBatch` and `can_export:<profile>`."
- `authz_id` has been served since 10-21. "With Lane 1" is Lane 1's #286 (`540416a0`, merged `2cc05912`): the live walk reads `authz_id` from `/me/entitlements` as a readiness step.
- After the implementer: run the seal, mutate (held filter dropped, file as source, a partial list on failure, an email-keyed subject, the sort dropped), open the PR, set the item to review, and packet cortex-ui.

## Packets placed (untracked, master tree `sessions/`)

- To `iagent-mesh-sdk/lane/ca`, cc architect: v0.9.16 `options` on steps and `level`/`max_level` on AssetContract.
- To `dag-tools/seat/owner`, cc architect: the levels file is now `classification/dimensions.yaml`. It was refreshed with `ratified_by` and the #282 merge.
- To architect, cc lane/01: G6's readings, and that Lane 1's half is #286.
- To architect (earlier): dimensions built, and the two SDK fields. Its readings are now ruled.

## Watch

- `tests/test_board_drift.py` is red on master (`docs/BOARD.md` vs `docs/plans/*` headers). It is Lane 1's to regenerate (ruled). The test rewrites `docs/BOARD.md` with CRLF when it runs, so `rm` and `git checkout` the file after a run.
- `origin/master` moves under a worktree because other lanes fetch the shared refs. Diff with `origin/master...HEAD` (three dots), and `merge-tree` before a push.
- A cherry-picked or rebased commit keeps its old `Lane:` trailer. Re-derive with `.githooks/pre-push --expected` per branch.
- The ADR-0055 phrase "one classification, many categories" may be openddil's ADR-0055 (see the 11-06 openddil packet in master `sessions/`), not iagent's archetypes ADR. #282's body quotes it and does not cite it.
