to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-24
re: your two rulings of 10-24 that followed the PR audit (the merges and the stale rule; who owns a kind's fields)
relay: Chris

This report carries no secret and no infra detail.

# Ten PRs merged: the eight you ruled, the stale rule (#86) and doors-export's passes (#87). 74 has its packet

## 1. Eight merges, via `gh pr merge --merge`

- **The combined check first:** I chained a merge of all eight onto master `24e64a5e` (#85, squash-merged by Chris). They merged cleanly together, not only one at a time.
- **Result:** master is now `3c4a44cb`, and its tree is byte-identical to that chained trial merge (`git diff` is empty). Every head is an ancestor of master.

| PR | merge commit | CI on the PR |
| --- | --- | --- |
| #84 | `9419b218` | 20 of 20 pass |
| #83 | `6dafe3b1` | 20 of 20 pass |
| #77 | `1f638cdc` | **none ran** (see below) |
| #78 | `0fab69a3` | **none ran** (see below) |
| #80 | `1a7e0f94` | 20 of 20 pass |
| #79 | `f706e049` | 20 of 20 pass |
| #74 | `4e3a0f65` | 20 of 20 pass |
| #32 | `3c4a44cb` | 20 of 20 pass |

**#77 and #78 merged with no CI of their own.**
- They had been based on `lane/01-197`, and retargeting a PR to master does not trigger `build-containers.yml`.
- What they did have was their own tests on the trial merge: 9 passed and 19 passed. You ruled them for today, so I merged them.
- Master's push run is their first build.

**#44 stays open for review,** as you ruled.

## 2. The stale rule: #86, merged at `2b4897b3` (CI 20 of 20)

- **The rule:** stale = max(90 min after creation, the holder's declared `expected_end`). 90 minutes is the floor.
- **A missing or unparseable end** leaves the floor alone in force, and the script says so. An empty end is caught before `date -d ""` would read it as midnight.
- **Tests:** 18, 5 of them new. Three mutants each turned their named test red: never extending, `min` in place of `max`, and dropping the empty-end check.
- **The runbook** states the rule.
- **One limit I did not fix.** A holder cannot extend its own lock: acquiring it again is a no-op, and a test seals that. `upgrade-sandbox` declares only its helm timeout, so after a full 100-minute helm wait, the gates run past the declared end. A `renew` verb would close this. It is yours to rule on.

## 3. Who owns a kind's fields: #87, merged at `1d615bc5` (CI 21 of 21, including the real `drift` job)

- **The row:** doors-export's `passes` now mirror doc-tools main, `identity.identity_from_doors_text` then `doors.requirements_rows` (#100). The row's header states your ownership split.
- **The pin moves in the same commit**, to doc-tools main's head `8a47f601`.
  - doc-tools/lane/7f's packet measured that the row change alone fails the gate: the gate reads the pin, and v0.2.1 declares one pass.
  - `8a47f601` is **not a release**, and the ref file says so. It also says that any `passes` change carries its pin bump.
- **Measured locally,** replaying the workflow's steps against doc-tools at `8a47f601`:
  - Before the change, the passes check fails on doors-export alone.
  - After it, 7 passed and 0 skipped, and the broken-on-purpose control still fails on passes, naming doors-export.
  - The four in-repo files that read the overlay all pass.
- **The drift test's direction:** that file is doc-tools', and 7f is changing it.
- **One thing to know about the platform side.** It reads `passes` in exactly one place, `_same_passes` (spec 204's re-class vs re-run), and executes none of them. So the mirror decides something even though nothing runs it. doors-export is not a leaf, so that decision is unaffected today.

**7f's point, which I think deserves a ruling.**
- A cross-repo seal pinned to a frozen peer stays green on a divergence that already exists. Before #87 the gate was green while the two registries disagreed, because the pin predated #100.
- The pin rule I wrote, "bump with a release pairing", lets the pin's age grow unmeasured.
- **Options:**
  - (a) Bump the pin on a schedule.
  - (b) A second, non-blocking job against doc-tools `main` that reports drift without failing.
  - (c) Leave it.
- I recommend (b).

## 4. #16 and #17: lane 74 has the packet

- The packet is `sessions/2026-10-24-packet-to-lane-74-prs-16-and-17-update-to-master-or-close-by-10-31.md`, placed in the master tree.
- **For each PR it says:**
  - what fails on master, and why;
  - how to update without a force-push: merge master into the branch;
  - the deadline, **2026-10-31**, when whichever is still open closes.
- Both PRs carry a comment with the deadline.

## Not reviewed

- I did not run any full suite.
- I did not read the eight merged PRs' code beyond what the audit needed.
