# Handoff: lane/gov, 2026-11-02 (#190 and #196 merged; #199 corrects the board; the sandbox member is asked)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-02

This replaces `2026-10-31-handoff-lane-gov-190-green-196-can-review-open-board-waits-on-189.md`.
- Its forks 18–21 are ruled, below. Fork 17 shipped as #190.
- Forks 12 and 22, forks 7–8 and the lessons in older handoffs still stand.

## The ruling since (architect via Chris, 2026-11-02, verbatim)

> to: invincible-agent/lane/gov — reviewer rows = wb's item, correct; validate_policy takes review subjects from a registry list so a misspelt key fails; production reviewers wait on the training-domain ruling; yes, the SDK carries the strict reader (ca). #194 then #190, dropping the two xfails.

## State

- **#190 and #194 are merged.** lane/01 ran the train, dropped the two xfails and moved #190's changelog entry itself (`cc76a911`). `origin/master` had them at `01d70102`, and has since moved to `6d3ff024` (#191). Item `01M6A9QDN1VFYAPZKDZCZ0GSTJ`.
- **#196 is merged** at `c788fd50` by lane/01's train (`lane/gov-can-review`; gov's last head `86a6f815`, lane/01's merge-up `cf77ca28`). It is `can_review:<subject>` plus the registry. It is under 0.4.75, not yet cut, so it is not live. Item `01M6AJR52DDXSJPFKQ12WG08J3`.
  - New: `policy/review_subjects.yaml`, and `validate_policy` refuses a `can_review:<S>` whose S is not in it.
  - The registry is a product file: read from beside the validator, not in `DATA_FILES`. A new data file would fail the seed of every deployment whose repo lacks it. The seed job's image (cortex-bff) is built from the whole repo, so the file arrives without a chart change, and the seal pins that chain.
  - The limit, stated in the PR: a deployment can't register its own subject. There is no such case, so there is no overlay.
  - Seal: `tests/security/test_can_review_capability_rail.py`, 27 tests. Mutants: set `cr` V1–V16, all named-red; run on the tree before the master merge.
  - Consumers (67 files) at `86a6f815`: 1523 passed, 60 skipped, 4 xfailed, 3 failed. All three also fail on plain master `3e4e0162`. Log: `t_cr_consumers3.log`; control: `t_cr_ctl.log`.
  - CI on `cf77ca28`: 20 pass, 3 skipping. The seal rerun on master `c788fd50`: 27 passed.
  - **`topaz_sync` for `alignment-reviewers` is owed before the roll** (Chris). The item is `blocked` on it.
- **#199** (`lane/gov-board-1102`, open) corrects gov's board items and adds `01M6AJR52DDXSJPFKQ12WG08J3`, `01M6AJR570CZG8R9WA0JCYX1ZX`, `01M6EX5BSQNCWZXBBCFAM8PNCV` and `01M6EYWM7JPW40G3PQATTYXAQR`. The can_review item already says merged and blocked. `render_board.py --check` passed on it. If it conflicts later on `board/BOARD.md`, re-render; don't hand-merge.
- **#149** is open at `20d62c4b`, unchanged this block. Item `01M6A9QDN1M7B3400G8Y0MWH0Y`.
- **No `can_call` image defect from #179.** Checked: `docs/api/mcp.openapi.json` is in the seed job's image for the same reason the registry is.

**A master red, not gov's:** `test_s3_the_catalogue_is_the_reviewed_list` (saf's seal), red at `3e4e0162` and `6d3ff024`. `NOTICE_FIELDS` holds `item_kind` and `review_shape`; the seal's reviewed list doesn't. Filed for saf as `01M6EYWM7JPW40G3PQATTYXAQR`. The attribution to lane/01's review-shapes commits comes from a string search, not a bisect. Gov did not edit it.

**Placed** (untracked in master's `sessions/`; copies committed here):
- `2026-11-02-packet-to-architect-gov-review-registry-built-on-196-the-sandbox-member-and-one-new-master-red.md`: to the architect, cc lane/01, saf and wb.
- `2026-11-02-packet-to-wb-from-gov-reviewer-rows-are-yours-the-role-is-ruled-production-reviewers-wait.md`: to wb, cc the architect and ca.
- `2026-11-02-packet-to-ca-from-gov-the-sdk-carries-the-strict-pdp-reader-ruled.md`: to `iagent-mesh-sdk/lane/ca-0.9.13`, cc the architect and wb.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
22. **The fail-closed sites deny on a malformed answer and do not 503.** #190 kept their posture. Converting them is unasked; the packet says so again.
23. **The sandbox member: bob or alice?** wb reports the architect named alice. Nothing addressed to gov does, so #196 grants bob. Asked in the packet. If alice, it is one line in `policy/users.yaml`, in a follow-up PR, cheapest before Chris's sync. Item `01M6AJR52DDXSJPFKQ12WG08J3`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| the sandbox member | architect | `01M6AJR52DDXSJPFKQ12WG08J3` |
| `topaz_sync`, then the roll carrying 0.4.75 | Chris | `01M6AJR52DDXSJPFKQ12WG08J3` |
| #199 merge | lane/01 | `01M6EYWM7JPW40G3PQATTYXAQR` and the other items it carries |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| `GRANTED_BY_SEED` in v0.9.13 | ca | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |

wb's NetworkPolicy question is lane/01's to answer. Gov told wb and the architect that and took no action. wb's reviewer rows are wb's item, `01M6A9QDN1VCGZRXDMMKTFWT1T`; its body is wb's to correct.

## Next (in order)

1. Read the architect's answer on the sandbox member. If alice, change `policy/users.yaml` in a follow-up PR and rerun the seal.
2. Read #199's PR state before writing anything about it.
3. When #199 merges, update gov's items for whatever has moved since, and regenerate the render.
4. **Later, as ruled:**
   - the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`);
   - `GRANTED_BY_SEED` when ca ships v0.9.13 (`01M6A9QDN199K1WE2H3QN3ZVQ9`).

## Scratch (session scratchpad, not durable)

Worktrees:
- `gs` holds #196, with its own venv.
- `bd` holds #199, with no venv; use `gs`'s Python.
- `rp` holds #149.
- `ct`, `f181` and `cc` were merged; they can go.

Tooling:
- `mut3.py` and the multi-file runner are pinned with `-c pytest_pin.ini --rootdir=.`. Another session's `%TEMP%/pyproject.toml` carries `--cov` addopts, and pytest walks up to it. It is not ours, so don't delete it.
- The old hook in ia-gov gives an empty `--expected`. Derive the trailer from master's `.githooks/lanes`, and assert it starts `Lane: `.

## Lessons

- **Read a PR's state before writing about it.** lane/01 ran the 11-02 train while I built the registry. My packets and board text said #190 still had to drop its xfails, and I had to correct them; one packet to lane/01 was moot and I deleted it. #191 and then #196 itself merged while the architect packet was being written. Re-read PR state as the last step before placing a packet.
- **Run the control before you name a red.** All three consumer reds looked possibly mine until the same run on plain master showed them. One had no owner on the board, so the control also found a new item.
