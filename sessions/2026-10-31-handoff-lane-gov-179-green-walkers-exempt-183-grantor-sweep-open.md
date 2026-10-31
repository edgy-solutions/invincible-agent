# Handoff: lane/gov, 2026-10-31, late (#179 green with both rulings; #183 opens the grantor sweep)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-31

This replaces `2026-10-31-handoff-lane-gov-179-rulings-applied-grantor-sweep-queued.md`.
- Its two departures are closed by the ruling below.
- Fork 13 has become #183.
- Fork 12 (the relay-form detector), forks 7–8 and the lessons in older files still stand.

## The second ruling (architect via Chris, 2026-10-31, verbatim)

> to: invincible-agent/lane/gov — M3 reading: routes tagged `mcp` only — correct. mcp-callers: exempt capability-only groups from the walker test rather than widen membership; alice and bob only. The granted_by sweep: yes, next PR. #179 and #181 merge when green; Chris runs the sync between merge and roll.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov-can-call-mcp-surface` | `83697532` | #179 → master | **Green**, CLEAN, merges clean with master `258c89ad`. Both rulings applied. **Merge now (lane/01), then Chris syncs `mcp-callers`, then the roll.** |
| `lane/gov-grantor-is-seed` | `a0fda3eb` | #183 → master | 71 rows → `granted_by: seed`, plus the repo seal `test_a_shipped_grantor_is_the_seed.py`. G1–G4 named-red. CI was running at handoff. |
| `lane/gov-repository-paths-rail` | `20d62c4b` | #149 → master | Green, CLEAN. |
| `lane/gov` | this commit | none | carries the handoff |

**#149, #179 and #183 all add `## 0.4.74 — not yet cut`.** Whichever merges later folds its entry under that heading.

**#179's second commit, `83697532`:**
- `mcp-callers` holds alice and bob only. The walkers lose both capability-only groups.
- The walker seal in `tests/test_oidc_broker_chart.py` exempts capability-only groups. A group is capability-only when it is empty in `groups.yaml` and granted by some `capability_grants` row; the set is derived, never listed.
- The count control stays 11.
- W1–W4 are named-red.
- On the merge with `258c89ad`: `can_call` 24, `oidc_broker_chart` 44 and `mcp_chart` 15 passed.

**#183, the grantor seal:**
- It is a **repo test, not a `validate_policy` row**.
- `validate_policy` runs on the deployed policy, where a deployment's rows, and the runtime reader grant written by `write_grant_and_sync`, name their approver.
- `granted_by` is never written to Topaz, so no sync is owed.

**Placed** (untracked in master's `sessions/`; copy here): `2026-10-31-packet-to-architect-gov-179-second-ruling-applied-walkers-exempt-capability-only-groups.md`, to the architect, cc lane/01.

## Open forks

12. The relay-form detector for the ratchet (carried over).
14. **Person-naming left unswept by #183.** These are the architect's to rule:
    - `trust_table.yaml` `ratified_by: cnogradi` (a ratifier, not a grantor);
    - five "Chris's ruling" comment citations;
    - the fixture user `chris@example.com`;
    - 20 synthetic `"cnogradi"` values in the sync-mechanism tests.
15. **The token `seed` is restated in #183's test** (the four tests, test 4). The ruling is its only source.

## Next (in order)

1. **Read CI on #183.** If it is red, read the failing check before anything else.
2. **When the architect answers fork 14,** follow up on `lane/gov-grantor-is-seed` (or a new branch if #183 has merged).
3. **After #179 merges:** confirm with `is-ancestor` on `origin/master`. The sync and roll are Chris's and lane/01's.
4. **When v0.9.13 ships (fork 7):** as in the earlier handoffs.

## Scratch (session scratchpad, not durable)

Worktrees:
- `cc` holds #179.
- `gs` holds #183 and has its own venv.
- `rp` holds #149.

`mut3.py` carries these sets:
- `cc2`: K1–K13;
- `wk`: W1–W4;
- `gs`: G1–G4.

## Lessons

- **Git Bash heredocs collapse `\\n`, even inside `<<'EOF'`.** This happened twice this session. To build a backslash in an inline script, use `chr(92)`, or keep the script in a file that no shell has touched.
- **A rule that binds what ships is not a rule for the validator, which also runs on what is deployed.** Before you choose where a seal lives, ask which population each candidate runs on.
- **A derived population needs a control that it did not shrink.** Without that control, a parametrize over a derived list goes quietly short (G3).
