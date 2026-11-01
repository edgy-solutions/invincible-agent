# Handoff: lane/gov, 2026-10-31, overnight (#190 green; #196 `can_review` open; board waits on #189)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-31

This replaces `2026-10-31-handoff-lane-gov-181-is-true-pushed-183-leftovers-green-class-of-nine-proposed.md`.
- Its forks 16 and 17 are ruled, below.
- Fork 12 (the relay-form detector), forks 7–8 and the lessons in older handoffs still stand.

## The rulings since (architect via Chris, 2026-10-31, verbatim)

> to: invincible-agent/lane/gov — 16: a non-boolean `check` is a malformed PDP answer, which is the outage class: 503, never a 403 (a 403 asserts policy said no). 17: yes, the nine together in one PR.

> to: invincible-agent/lane/gov — overnight: the nine-site 503 PR (item 17); then `can_review` for the workbench's alignment reviewers and the board's reviewer rows; correct your board items when Lane 1 seeds them.

## State

- **Merged into master** (checked with `is-ancestor` on `origin/master` `16d0b6a6`): #179, #181 and #183.
- **#190** (`lane/gov-check-is-true-class`, head `b1b02e93`) is the PDP-answer class. Item `01M6A9QDN1VFYAPZKDZCZ0GSTJ`.
  - CI green: 19 Docker builds plus Lint.
  - It merges clean with master `16d0b6a6`. On that trial merge the seal (98), the ratchet (24) and saf's seal (8) are green.
  - **The join with saf's #194** (`lane/saf-review-export-outage-seal`, `48e81153`, open) has three strict-xfail nodes that XPASS, which reds the join. Measured by trial merge.
  - Whichever merges second deletes the two `@pytest.mark.xfail(strict=True …)` decorators, at lines 181 and 192 of `tests/routing/test_the_review_export_routes_answer_503_on_an_outage_and_403_on_no_grant.py`.
  - The proposal to lane/01 is #194 first, then gov.
- **#196** (`lane/gov-can-review`, head `ec68fe80`, from master `6bd47267`) is `can_review:<subject>`. New item `01M6AJR52DDXSJPFKQ12WG08J3`.
  - First row: `can_review:alignment` → `[alignment-reviewers]`, a new capability-only group whose sandbox member is bob (FIXTURE).
  - No code. Seal: `tests/security/test_can_review_capability_rail.py` (13 tests). Mutants: set `cr` V1–V7, all named-red.
  - 29 consumer files: 590 passed, plus the SDK environmental red.
  - CI was running at handoff (11 success, 9 pending).
  - **`topaz_sync` for `alignment-reviewers` is owed before the roll** (Chris).
- **#149** is open at `20d62c4b`, unchanged this block.
- **#189 (the board) is still open**, on `lane/01-board` at `59492904`. Gov's items are not yet corrected (see Next).

**Placed** (untracked in master's `sessions/`):
- `2026-10-31-packet-to-architect-gov-190-green-joins-194-by-dropping-two-xfails-can-review-is-196.md`
  - to the architect, cc lane/01, saf and fin;
  - covers the #190 state, the #194 join, #196 and four `can_review` forks.
- `2026-10-31-packet-to-wb-from-gov-can-review-alignment-is-the-capability-your-review-route-asks.md`
  - to `training-consolidation-workbench/lane/wb`, cc ca;
  - the request shape and the 200/403/503 table;
  - `AUTHZ_CLAIM` must equal `USER_ENTITLEMENT_CLAIM`.

## Open forks

12. The relay-form detector for the ratchet (carried over).
18. **"The board's reviewer rows".** Gov read it as wb's reviewer item (`01M6A9QDN1VCGZRXDMMKTFWT1T`). If it means a `can_review:board` row, that is a second row on #196's convention.
19. **Who validates a `can_review:` subject?** There is no registry here. The options: the workbench publishes its subjects, or the gap is accepted.
20. **The production grantee** waits on the training-domain reviewer ruling (`01M6A9QDN16Q03BPSJAPWDSAEP`).
21. **The SDK.** Should it carry `pdp_answer.check_answer` for the workbench (ca, after v0.9.13)?
22. **The fail-closed sites deny on a malformed answer and do not 503.** #190 kept their posture. Converting them is unasked.

## Next (in order)

1. **#194/#190 order.** When lane/01 says #194 is in:
   - merge `origin/master` into #190 in `$S/ct`;
   - delete the two xfail decorators;
   - rerun #194's file, the seal and the ratchet;
   - push.

   If #190 lands first, saf drops the markers instead.
2. **Read #196 CI.** It is based on master, so it is a real build.
3. **When #189 merges, correct these items on master** (from `lane/01-board` `59492904`), then run `scripts/render_board.py` and commit the items plus `board/BOARD.md`:

   | item | correction |
   | --- | --- |
   | `01M6A9QDN1CE5779G5XNRQT183` | #179 merged |
   | `01M6A9QDN1YYD1BC7HTHS9QVPA` | #183 merged; drop "Awaiting ruling on unswept person names" |
   | `01M6A9QDN1VFYAPZKDZCZ0GSTJ` | retitle to the PDP-answer class: pr [#190], status review |
   | `01M6A9QDN1M7B3400G8Y0MWH0Y` | #149, still review |
   | `01M6A9QDN199K1WE2H3QN3ZVQ9` | SDK v0.9.13 follow-ups, still blocked |
   | `01M6A9QDN19S78PQVCA67NZ9RC` | fork 12, the relay-form detector |
   | `01M6AJR52DDXSJPFKQ12WG08J3` | **add**, for #196 (`can_review`), status review |

   - The spare minted id `01M6AJR570CZG8R9WA0JCYX1ZX` is unused.
4. **Later, as ruled:**
   - the walker `chris@example.com` → `dave`, with lane/01;
   - `GRANTED_BY_SEED` when ca ships v0.9.13.

## Scratch (session scratchpad, not durable)

Worktrees:
- `ct` holds #190, with its own venv.
- `gs` holds #196, with its own venv.
- `f181` and `cc` were merged; they can go.
- `rp` holds #149.

Tooling:
- `run1.sh` and `mut3.py` are pinned with `-c pytest_pin.ini --rootdir=.`. The reason: another session's `%TEMP%/pyproject.toml` carries `--cov` addopts, and pytest walks up to it (rc=4). It is not ours, so don't delete it.
- `mut3.py` sets: `ct` C1–C11, `cr` V1–V7.

## Lessons

- **Read the inbox for your own PR's class before you call it ready.** saf's #194 sealed the defects #190 fixes as strict xfails, so the two PRs were each green and their join was red. A trial merge with each open PR in the same class costs one run.
- **A pytest config you did not write can be found by walking up.** Pin the inifile and rootdir in any runner that works from a scratch worktree.
