# Handoff: lane/gov, 2026-10-30 (#149 rebased onto 0.4.73; the 0.4.73 audit is clean; can_call is #179)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-30

This replaces `2026-10-30-handoff-lane-gov-config-rule-applied-151-159-hold-lifted.md`.
- Its state table is superseded by the one below.
- Its open forks 7 and 8 still stand, as do its lessons. So do the older file's forks 1–6 and lessons.

## The directive (architect via Chris, 2026-10-30, verbatim)

> to: invincible-agent/lane/gov — rebase #149 (CHANGELOG + validate_policy); then the audit of 0.4.73's new routes against the ratchet; then the policy for the MCP surface: which tags a persona may call (can_call:<tag>), rows on the rail, deny by default.

**All three items are done.** Three forks went to the architect; nothing is held.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `20d62c4b` | #149 → master | Rebased onto `41230a7e` (0.4.73). The CHANGELOG entry sits under `## 0.4.74 — not yet cut`. 7 suites green, D1–D12 named-red. Backups: `backup/gov-149-pre-rebase` (`f4942845`) and `backup/gov-149-pre-0473-rebase` (`deb49519`). |
| `lane/gov-can-call-mcp-surface` | `49a6a149` | #179 → master | `can_call:<tag>`. 15-test rail plus 6 neighbouring suites green; C1–C12 named-red; the new refusal censuses COMPLIANT. No rows. |
| (merged) | — | #151, #159 | Merged to master. |

**Placed:**
- **Packet**, untracked in master's `sessions/` and copied here: `2026-10-30-packet-to-architect-gov-can-call-is-pr-179-three-forks-and-0-4-73-audit-clean.md`, to the architect, cc lane/01 and lane/saf.
- **Report**, committed here: `2026-10-30-report-gov-0-4-73-routes-against-the-ratchet.md`.

## Open forks (new)

9. **M1. `azp` selects the door** (`CAN_CALL_DOOR_CLIENTS`).
   - It is still never WHO is authorized.
   - An unset env fails open, as today.
   - Gov recommends it as built.
10. **M2. The first `can_call` rows.** None ship.
    - Under AND, the ingest-v1 routes need `mcp` + `ingest-v1`, and the export routes need `mcp` + `ingest-export`.
    - The env stays unset (lane/01's) until rows land.
11. **M3. A door caller outside the 13 MCP routes is unchecked** (for example `/interview/stream`).
    - Gov recommends an app-wide dependency, in a separate PR, if the architect says yes.
12. **Ratchet relay-form detector**, offered as a gov follow-up: 18 dynamic-status relays the ratchet cannot see. lane/01 owns `export_package_artifact` (`gateway.py:3888`).

## Next (in order)

1. **Read CI on #149 and #179.** Both are based on master, so `build-containers.yml` runs.
2. **On the architect's M2 ruling:**
   - append the rows to `policy/capability_grants.yaml` on #179's branch (`grant_to_groups`);
   - re-run the rail and `validate_policy`;
   - a new group means a `topaz_sync` precondition: say so in the PR.
3. **On M3 = yes:** an app-wide dependency that refuses a door caller on any route lacking a granted tag. Seal it by deriving every route from `gateway.app`.
4. **When v0.9.13 ships (fork 7):** as in the previous handoff.

## Scratch (session scratchpad, not durable)

- `mut3.py` now carries the `cc` set (C1–C12) beside `rp`.
- `census_at.py <repo> <base> <head>` runs the ratchet's census over blobs.
- `stale_and_manifest.py` checks list rows and manifest declarations.
- `fix149b.py` resolves a CHANGELOG conflict whose HEAD side moved: it keeps HEAD's side, then applies the commit's own hunk.

## Lessons

- **A release cut moves the CHANGELOG under a PR.** Rebase each commit by keeping HEAD's (empty) side and re-applying that commit's own `-U0` hunk to the moved block. Then check that the diff against master is additions only.
- **An implementer's "the file had CRLF before" is a claim.** Check it against the blob (`git show HEAD:<f> | tr -cd '\r' | wc -c`). Here both blobs were LF.
- **A per-route dependency checks only the routes it is on.** Say what it leaves unchecked: a handler shared by an untagged route is a second door.
