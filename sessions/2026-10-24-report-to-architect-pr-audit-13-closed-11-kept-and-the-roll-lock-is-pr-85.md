to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-24
re: the PR audit (24 open PRs) and the roll lock, both directives of 2026-10-24
relay: Chris

This report carries no secret and no infra detail.

# PR audit: 13 closed, 11 kept. The roll lock is PR #85, open

## 1. The audit table

**Method**
- **"On master"** means `git merge-base --is-ancestor <head> origin/master` at `2705c335`.
- **The merge sha** is the merge whose second parent first brought the head in. That is the oldest merge M on the ancestry path where the head is not reachable from M^1.
- **The roll** is the first roll whose rolled sha contains that merge. I checked each one against the roll before it too, and the earlier roll does not contain it.
- **Unlanded PRs:** no PR is landed by patch-id (`git cherry`: no `-` lines). For each one I either trial-merged it onto `2705c335`, or read what later work did with its subject.

| PR | branch | verdict | merge sha / superseded by | roll it shipped in | action |
| --- | --- | --- | --- | --- | --- |
| #39 | lane/gov-resolve-instance | on master | `bfbbebc8` (into rev 187) | roll 187: helm 189, chart 0.4.43, image `49aa5e28` | closed |
| #45 | lane/gov-enumerate-gate | on master | `d70315a5` (with #47, into 188b) | roll 188b: helm 192, 0.4.46, `76af7b83` | closed |
| #47 | lane/gov-caller-census | on master | `b0dfbd67` (into 188b) | roll 188b: helm 192, 0.4.46, `76af7b83` | closed |
| #54 | lane/gov-narrow-except | on master | `e2878e7f` (into lane/01-rev189) | roll 189: helm 193, 0.4.49, `86b74d1a` | closed |
| #62 | lane/74-shared-resolve-helpers | on master | `b071d5b0` (into 192) | roll 192: helm 197, 0.4.52, `b89d4c95` | closed |
| #63 | lane/74-binds-identifier | on master | `38f37b28` (into 192) | roll 192: helm 197, 0.4.52, `b89d4c95` | closed |
| #69 | fin/export-refused-entries-in-documents | on master | `fef8e587` | roll 194: helm 199, 0.4.54, `8a57437a` | closed |
| #71 | fin/export-no-answers-is-a-400 | on master | `d7e90ce3` | roll 195: helm 200, 0.4.55, `c2b1110f` | closed |
| #72 | fin/export-unentitled-prose-is-constant | on master | `6bea919e` | roll 195: helm 200, 0.4.55, `c2b1110f` | closed |
| #30 | lane/01-prep-next (draft) | superseded | master pins SDK v0.9.10 (`177eaf85`) and is at chart 0.4.67. Its #16 and #17 stay open on their own PRs | – | closed |
| #33 | lane/01-supervisor-person | superseded | `9f4e9395` and `e6ef4bce` (your 10-17 rulings #4 and #1): both verbs are in the caller-identity set, and the ceiling is 5 | – | closed |
| #25 | lane/01-delegate-read | superseded | the 10-16 rulings for 190: `e883347e` (artifact ids on the status row) and `092f3547` (a delegate is barred from `/cases`) | – | closed |
| #75 | lane/saf-sheet-draft-is-card-and-task | superseded | carried whole by #80 | – | closed |
| #84 | lane/01-oci-labels | kept | clean onto master. 83 passed, 5 skipped | – | noted |
| #83 | lane/ca-resolve-instance-adoption | kept | clean onto master. 52 passed. The three engines pin v0.9.10, which exports the class | – | noted |
| #44 | lane/01-user-token-specialists | kept | clean onto master. 53 passed. More needed than when it was opened (see §2) | – | noted |
| #77 | lane/gov-action-route-seal | kept | clean onto master. 9 passed. It waits on gov's Q17 | – | **retargeted to master**, noted |
| #78 | lane/gov-q14-unconfigured-topaz | kept | clean onto master. 19 passed. It adds the unset-URL case, which #73 does not cover | – | **retargeted to master**, noted |
| #17 | lane/74-mpn-sources | kept, **needs its owner** | clean onto master, but **its seal fails 3 of 5 tests there** | – | noted |
| #16 | lane/74-required-slot | kept, **needs its owner** | one placement conflict, and **its seal fails 9 of 29 tests there** | – | noted |
| #80 | lane/saf-sheet-interim-states | kept | docs only, clean. Master has none of its row texts | – | noted |
| #79 | lane/saf-walk-live-938d7639-digest | kept | docs only, clean | – | noted |
| #74 | lane/saf-walk-194-digest | kept | docs only, clean | – | noted |
| #32 | lane/gov | kept | gov's live sessions branch (last commit 10-21). Docs only, clean | – | noted |

## 2. Where this departs from the brief

- **#45 is on master, not open work.** Its head `9393ff08` came in with #47's merge into 188b. I closed it.
- **Your single-use vault reference is #44.**
  - #44 is still wanted, and more so than when it was opened. Master's vault is still one-shot per run (`identity_vault.py:197,220`). Master now has five caller-identity verbs, so a second such subtask in one fan-out gets `already_redeemed` (`dynamic_supervisor.py:1682`).
  - The record says it is wanted (`sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md:165`). I found no ruling of yours on it.
- **I did not rebase anything.**
  - A rebase of a pushed branch needs a force-push, which is forbidden here. Nine of the eleven kept branches belong to other lanes (ca, gov, 74, saf).
  - What I measured instead: each kept PR's merge onto `2705c335`, built locally and never pushed, with its own tests run on that merge, one file at a time. A `gh pr merge` produces the same tree.
- **#16 and #17 are wanted, but not landable as they stand.** Each seal was written against a master that has since moved:
  - **#17:** `read_notice_parts` now returns no `sources` for its fixture (a TypeError at the test's line 48). The fix itself is still absent: `_project_sources` passes no `mpn`/`notice_id` (`gateway.py:5854`).
  - **#16:** master's `fill_slots` now refuses a call that has no caller (#59), and its arms send none. Its one conflict is placement only: master's `_bound_value` and its `_is_empty_slot_value` both follow `_decode_declarations`, so keep both.
  - Both are lane 74's to update. I have not touched those branches.

## 3. The roll lock: PR #85 (`3030a44d` and `939caa90`), open, not merged

- **What it does.** `scripts/roll-lock.sh` takes `acquire [--minutes N]`, `check`, `release` or `show`. It manages `sandbox/roll-lock` with the keys `{lane, started, expected_end}`.
- **Its rules:**
  - It refuses (exit 3) while another lane holds a lock younger than 90 minutes.
  - A lock 90 minutes old or more is taken over, and the takeover says so loudly.
  - Only the holding lane can release the lock.
  - `kubectl create` is the atomic step.
  - An unreadable lock refuses (exit 4).
  - Age is read from the server's `creationTimestamp`.
  - The lane is `<repo>/<branch>`, derived from git.
  - It follows `HELM_KUBECONTEXT`.
  - It is self-contained, so doc-tools and the workbench can copy it.
- **Where the scripts take it:**
  - `upgrade-sandbox.sh` acquires the lock after its own guards and right before `helm upgrade`, for its helm timeout. A `--dry-run` only shows the lock.
  - `roll-litany.sh` acquires it for 30 minutes. If the same lane already holds it, that is a no-op.
  - The roller releases it once the gates pass.
- **The runbook.** `rolling-a-service.md` gains the section "Take the roll lock first", with the why (rev 216).
- **Seal: `tests/test_roll_lock.py`, 13 tests.**
  - Nine of them run the script against a stub kubectl, through Git for Windows' bash named by its path. That bash runs from a Python subprocess; the older timeout seal recorded that the default bash could not, so it sealed statically.
  - Five mutants each turned their named test red: the age comparison inverted, the read failing open, release of any lane, the holder's own lock refused, and the stale bound at 120.
  - The upgrade-sandbox seals still pass (12 and 5), and so does corpus drift (16).
- **Live:** `show` against the sandbox reads `free`.

**One question for you: the 90-minute bound is shorter than a legitimate roll.**
- `upgrade-sandbox.sh` defaults to a 100-minute helm timeout, and its guard refuses anything under 75. So a prime that runs past 90 minutes leaves its lock takeable while helm is still running.
- A long prime is the exact case the lock exists for (rev 216).
- **Options:**
  - (a) Stale is `max(90 min, expected_end)`.
  - (b) Raise the bound to the helm timeout plus the gates.
  - (c) Keep 90 as ruled.
- I built (c), and I recommend (a): it keeps 90 as the floor and lets the holder's own declared end extend it.
- **#85 waits on your word, or Chris's, to merge.** 7f and wb copy the script from master, so it should merge before their next roll.

## Not reviewed

- I did not read the kept PRs' code beyond what each verdict needed.
- I did not run any full suite.
- I did not check CI on #77 and #78. Retargeting them to master makes `build-containers.yml` run for them for the first time.
