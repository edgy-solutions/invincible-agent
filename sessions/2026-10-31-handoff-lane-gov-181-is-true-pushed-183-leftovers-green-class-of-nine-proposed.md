# Handoff: lane/gov, 2026-10-31, night (third ruling applied: #181 `is True`, #183 leftovers)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-31

This replaces `2026-10-31-handoff-lane-gov-179-green-walkers-exempt-183-grantor-sweep-open.md`.
- Its forks 14 and 15 are ruled, below.
- Fork 12 (the relay-form detector), forks 7–8 and the lessons in older handoffs still stand.

## The third ruling (architect via Chris, 2026-10-31, verbatim)

> to: invincible-agent/lane/gov — #179, #183 merge when green. Leftovers: `ratified_by: cnogradi` → `ratified_by: owner` (a seat, not a person); the five comments cite "architect ruling <date>"; the walker `chris@example.com` → a synthetic name (dave) in a later PR with Lane 1; `seed` becomes a constant in the SDK (ca, v0.9.13: GRANTED_BY_SEED). Apply saf's `is True` fix on #181 before merge.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov-can-call-mcp-surface` | `83697532` | #179 → master | **Green**, CLEAN. Merge (lane/01), then Chris syncs `mcp-callers`, then the roll. |
| `lane/gov-grantor-is-seed` | `77b25526` | #183 → master | **Green**: 22 pass, 3 skipped, CLEAN. It carries the leftovers. The PR body is updated. No sync is owed. |
| `fin/recipient-readers-rail` | `b42f2456` | #181 (fin's) | Gov's `is True` commit is on top of fin's `2a3385f0`. CI was finishing at handoff (18 pass, 3 pending). |
| `lane/gov-repository-paths-rail` | `20d62c4b` | #149 → master | Green, CLEAN. |
| `lane/gov` | this commit | none | carries the handoff |

**#183's second commit, `77b25526`:**
- `trust_table.yaml` now says `ratified_by: owner`.
- **Six** citations now say "architect ruling <date>". The census missed `users.yaml:211`, so it is six, not the five ruled.
- The seal adds `test_every_shipped_ratifier_is_the_owner_seat`. R1 is named-red.

**#181:**
- `recipient_readers.py:38` now reads `return r.json().get("check") is True`.
- `b42f2456` also adds saf's seal, `tests/test_recipient_check_must_be_a_true_boolean.py`. Unfixed it is 3 red; fixed, 8 green.
- The commit carries the trailer `Lane: ia-gov/lane/gov`, never fin's. It was pushed as a fast-forward with `HEAD:fin/recipient-readers-rail`.
- fin was told to pull.
- Still fin's before #181 merges: saf's P6 (picker outage 503 / no-readers 403) and the template-door outage seal.

**Master reds found, both fin's tests, neither in the suite-signal census:**
- `test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark`: the ruled 10-30 `plan:` row now ships.
- `test_both_export_routes_shape_through_the_ONE_helper`: `_export_plan_answers` is a third caller.

Both are red on master `258c89ad` and on fin's `2a3385f0` unfixed.

**Placed** (untracked in master's `sessions/`; a copy is here): `2026-10-31-packet-to-architect-gov-181-is-true-applied-183-leftovers-landed-two-master-reds.md`, to the architect, cc fin, saf and lane/01.

## Open forks

12. The relay-form detector for the ratchet (carried over).
16. **Non-boolean `check`: False (403) or raise (503)?**
    - Gov took False, the minimal form saf offered.
    - The 10-31 rule "outage → 503" may want a raise. That would be one line, and the seal accepts either.
17. **The class.** Nine more `bool(r.json().get("check"))` sites are on master. The site list is in the packet.
    - The proposal is a gov PR with one seal that finds Topaz-check readers **by form**, under the 7-body matrix.
    - Its control: the finder sees all 10.
    - It waits on fork 16, so that all ten get the same answer.

## Next (in order)

1. **Read CI on #181 at `b42f2456`.** If it is red, read the failing check. fin's two master reds are pytest-only, and CI runs no pytest gate.
2. **When the architect answers forks 16 and 17:** branch from `origin/master` as `lane/gov-check-is-true-class`.
   - If #181 has merged, `recipient_readers` is already fixed, and the class covers the other nine.
   - Run the mutants per site.
3. **After #179 and #183 merge:** confirm with `is-ancestor` on `origin/master`. The sync and roll are Chris's and lane/01's.
4. **Later, as ruled:**
   - The walker `chris@example.com` → `dave`, with lane/01.
   - `GRANTED_BY_SEED` when ca ships v0.9.13. The seal then imports it, and `SEED` goes.

## Scratch (session scratchpad, not durable)

Worktrees:
- `cc` holds #179.
- `gs` holds #183 and has its own venv.
- `f181` holds `lane/gov-181-check-is-true`, the same commit as `fin/recipient-readers-rail` at `b42f2456`, and has its own venv.
- `rp` holds #149.

`mut3.py` sets:
- `cc2`: K1–K13;
- `wk`: W1–W4;
- `gs`: G1–G4;
- `gs2`: R1.

## Lessons

- **A ruled number is a census claim too.** "The five comments" was six. Grep the subject before you trust the count.
- **A failure in a consumer suite is not yours until the unfixed run says so.** Revert the one line, rerun, then check the master base. Both of today's reds pre-dated the fix.
- **A remote ref may not move on `git fetch origin <branch>` here.** Use `git ls-remote origin refs/heads/<branch>` for a tip you are about to fast-forward.
