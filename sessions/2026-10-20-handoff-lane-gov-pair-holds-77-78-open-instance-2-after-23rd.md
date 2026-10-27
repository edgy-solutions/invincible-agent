# Handoff: lane/gov, 2026-10-20

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-action-route-seal, lane/gov-q14-unconfigured-topaz)
from: invincible-agent/lane/gov, 2026-10-20

This replaces `2026-10-15-handoff-lane-gov-kind-tree-groups-pr-56-422-after-188b-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-action-route-seal` | `01d8605b` | #77 → lane/01-197 | open; the fix needs the architect's OK (Q17) |
| `lane/gov-q14-unconfigured-topaz` | `3e9b25a9` | #78 → lane/01-197 | open; Q14 as ruled |
| `lane/gov-review-gate-rulings` | `d53d89ca` | #73 → master | MERGED |
| `lane/gov-kind-tree-groups` | `77f5a795` | #56 → lane/01-rev189 | MERGED |
| `lane/gov-adr-0047-delegate-reads` | `f8160272` | #76 → master | CLOSED: superseded by Q6 |
| `lane/gov-resolve-instance`, `-enumerate-gate`, `-caller-census`, `-narrow-except` | as on 10-15 | #39, #45, #47, #54 | open, as on 10-15 |

The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-20".

## The directive (10-20, from the architect via Chris), and where each part stands

> to: invincible-agent/lane/gov — origin on bob's two promoted rows (TI, IDT) + matched pair. ADR-0047 §5.1 note with both instances.

- **Origin: DONE (live, read-only).** Both rows are steward-confirmed. The attestation and the promotion name the same decision record.
- **Matched pair: DONE on 199, after the window closed.**
  - At `/resolve_instance`, carol is withheld both rows. Carol with SUSTAINMENT added sees them. She sees the seeded controls either way.
  - `/notice_parts` refuses an outsider `not_entitled` first, with one body for every id.
  - Not live-reachable: that route's withheld-equals-unknown body (no live user is inside the prefilter and outside the audience).
- **§5.1 note:** Lane 1 wrote it (lane/01-197 `b3fdad7f`), per Q6. Gov's part is the seals.
  - **Instance 1 (`GET /cases/{id}/action`): SEALED in #77.** It found and fixed a defect: an undeclared `svc:` reached the person gate.
  - **Instance 2 (the stage-enum read): NOT BUILT.** It is ruled for after the 23rd. No route or packet names it yet. Seal it against §5.1's wording once it lands, using #77's file as the pattern.

## Next

1. **Watch #77 and #78** for review. If the architect rejects #77's fix (Q17), revert those four lines on a new commit and xfail the three W1 service arms, with the ruling quoted.
2. **Instance 2**, once built: find it by grepping lane/01-* for `_delegate_principals` reads added since `b3fdad7f`.
3. **The open questions:** Q11, and Q17–Q20 (the #77 OK; whether `/source` and `/extraction` are a third instance; their 404/403 existence signal; `GET /cases/{id}` and an undeclared `svc:`).
4. **Carried from 10-15; not re-checked this session:**
   - the 422 `no_person` on engine O after 188b;
   - #54 onto 74's decide();
   - the AnswerArtifact origin field, only when a writer appears.

## Placed (untracked in master's `sessions/`)

- `2026-10-20-packet-to-lane-01-pair-holds-on-ti-and-idt-instance-1-sealed-77-q14-built-78.md`, cc the architect.

## Scratch (the session scratchpad; disposable)

- These worktrees can be removed with `git worktree remove`, never `rm`:
  - `seal/` (#77);
  - `q14/` (#78);
  - `adr/` (#76, closed);
  - `rg/`, which holds the venv the runners use.
- The live scripts are `live/pair.py` and `live/q3.cypher`.
- The mutant drivers are `mut_seal.py` and `mut_q14.py`. Their logs are under `mut-*` and `mutq14-*`.

## Lessons

- **A packet to gov can be placed in ia-gov's own `sessions/`.** Q6 sat there while I wrote #76 against it. Read both trees' `sessions/` before acting.
- **The runners take the LOG path first and truncate it.** Called with only a test file, the runner zeroes that file. That happened to the #73 file and it was restored from HEAD. Always pass `<log> <file>...`.
- **A seeded control decides which rule withheld a row.** Carol withheld a promoted row could be the domain or the origin rule. Carol seeing a seeded SUSTAINMENT row on the same route rules out the domain.
- **Windows Python cannot open a `/c/...` path.** Splice files with awk, or pass `C:/...` paths.
