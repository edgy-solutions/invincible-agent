# Handoff: lane/gov, 2026-10-31 (#179 has the M1–M3 rulings applied and is merge-ready; the grantor sweep is queued)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-31

This replaces `2026-10-30-handoff-lane-gov-149-rebased-0473-audit-clean-can-call-pr-179.md`.
- Forks 9–11 there are closed by the ruling below. Fork 12 (the relay-form detector) is still open.
- Forks 7–8 and all lessons from the older files still stand.

## The ruling (architect via Chris, 2026-10-31, verbatim)

> to: invincible-agent/lane/gov — M1: yes, azp identifies the door client. M2: `can_call:<tag>` rows to a new group `mcp-callers` (sandbox: alice, bob); the user's own persona×domain still gates the route beneath. M3: yes — a door-client token may reach only tagged routes; everything else 403 app-wide. #179 then merges. os.pathsep for the overlay env: confirmed to ca.

**Applied on #179.**

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-can-call-mcp-surface` | `cd794f91` | #179 → master | Rebased onto `ad4dff59` (#176). `DoorGuard` is an app-wide ASGI guard, innermost. Rows `can_call:{ingest-export,ingest-v1,mcp}` go to `mcp-callers` with `granted_by: seed`. 17 suites green, K1–K13 named-red. Merge-ready per the ruling. Backup: `backup/gov-179-pre-0474-rebase` (`d6874676`). |
| `lane/gov-repository-paths-rail` | `20d62c4b` | #149 → master | CI green on `20d62c4b`. Merge-ready. Whichever of #149 and #179 merges second folds its CHANGELOG entry under the shared `## 0.4.74 — not yet cut` heading. |

**Placed (untracked in master's `sessions/`; copied here):** `2026-10-31-packet-to-architect-gov-m1-m3-applied-on-179-ready-to-merge.md`, to the architect, cc lane/01.

## Two departures, both flagged in the packet

1. **"Tagged routes" was read as routes carrying `MCP_TAG`.** If the architect meant any tagged route, the change is one condition in `_decide`.
2. **`mcp-callers` has four sandbox members, not two.** erin and chris are added because lane/01's walker seal (`tests/test_oidc_broker_chart.py`) mirrors alice's groups.
   - That seal was **red on master**, measured at `41230a7e`: 2 failed. Gov's own 10-28 `alert-processors` grant caused it.
   - #179 repairs it: the walkers hold both groups, and the count is 13.

## Open forks

12. The relay-form detector for the ratchet (carried over).
13. **The grantor sweep** (fin's packet `2026-10-31-packet-to-gov-from-fin-shipped-rows-still-name-a-person-as-grantor.md`, in master's `sessions/`). The rule, ruled 10-31 on #176: a shipped row's grantor is `seed`, never a person, and Chris is not named in policy. The work:
    - 21 rows in `capability_grants.yaml`, plus the other `policy/*.yaml` files that carry `granted_by`;
    - the fixture at `test_can_export_capability_rail.py:43`;
    - optionally, a validator row that holds it by construction: a shipped grantor must be `seed`, while an overlay names its own approver.
    - **Also ask:** does "Chris is not named in policy" reach the fixture user `chris@example.com` in `users.yaml`? It is lane/01's walker.

## Next (in order)

1. **Read CI on #179.** It is based on master, so `build-containers.yml` runs. If it is green and nothing has changed, #179 is merge-ready per the ruling; merging is lane/01's.
2. **Do the grantor sweep (fork 13) as its own PR from master.**
   - Count first: `grep -rn "granted_by:" policy/ | awk '{print $NF}' | sort | uniq -c`.
   - Seal it with a validator row, and run the mutant that names a person.
3. **When v0.9.13 ships (fork 7):** as in the previous handoff.

## Scratch (session scratchpad, not durable)

- `mut3.py` takes a list of `(anchor, replacement)` pairs as one mutant, which K8 needs, and carries the `cc2` set (K1–K13).
- `cc2_hash_pre.txt` holds the restore hashes.

## Lessons

- **A seal you did not run can already be red because of you.** The 10-28 grant broke lane/01's walker seal and nobody saw it. When a change touches `users.yaml`, run every test that reads `users.yaml`, not only the rail you are working on.
- **A ruling that lands on another lane's PR binds your rows too.** Fin's `granted_by: seed` arrived on master between the commit and the rebase. Read the conflict's other side for its rule, not only for its text.
- **Count an anchor before you trust a mutant.** K12's anchor matched all three rows, so the run reported "SKIPPED, anchor count 3". The tool refuses an ambiguous anchor; a hand-rolled replace would have mutated the wrong row.
