# Handoff: lane/gov, 2026-11-04 (fork 7's loader half is #262; #254 merged; #256 waits on lane/01's train)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-04

This replaces `2026-11-04-handoff-lane-gov-224-ruled-254-open-follow-ups-are-items.md`. Fork 12 and the lessons in older handoffs still stand.

## The ruling since (via Chris, verbatim)

> gov: go on the rest of fork 7 — compose_export_profiles from the SDK, delete the copies in validate_policy.py. #254, #256 merge in Lane 1's next train; the second re-renders BOARD.md.

## State

| PR | what | state at writing |
| --- | --- | --- |
| #262 `lane/gov-export-profiles-from-sdk` | fork 7's loader half: `policy/export_profile_sources.yaml` (one SDK `ExportProfileSource` row per kind), `validate_policy.known_export_profiles` calls `compose_export_profiles`, the copies and `_EXPORT_KIND_LABEL` are deleted | open, MERGEABLE, head `d1089812`. No board commit yet (see Next 2). The merge is lane/01's. |
| #256 `lane/gov-granted-by-seed` | the seals import `GRANTED_BY_SEED`; the board moves fork 2 to done and fork 7 to open | open, CONFLICTING (only `board/BOARD.md`, after #254), head `181b619a`. Per Chris, lane/01 merges it in the next train and re-renders. |
| #254 | delegate readings 2 and 3, the board | merged `e81c7d5c` |

#262 was measured in-process on `459679e7` with v0.9.13 (`d8165f33`). The export rail gave 38 passed, and 8 of 8 mutants were killed. The 61-file area run (tests/security, every test naming `validate_policy` or an export profile, the declared-dependency test) gave 1684 passed, 4 xfailed, 0 failed. `test_a_chart_change_bumped_the_chart_version` is red until lane/01 cuts 0.4.79. Nothing ran live. The image's SDK importability was READ (Dockerfile.agent PATH), not run: Docker was down.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
13. (Candidate, not yet an item.) `validate_policy.py`'s other "no SDK here" forks, content kinds (~line 124) and review shapes (~line 437), rest on the premise #262 drops. Write an item when fork 7 goes to done; don't change them in #262.

## Waiting on

| for | who | item |
| --- | --- | --- |
| merge of #256, then #262 | lane/01 | `01M6A9QDN199K1WE2H3QN3ZVQ9`, `01M6A9QDN1M16XMBNHHWVK9EHJ` |
| the engines reading `export_profile_sources.yaml` via the SDK (packet placed 11-04, five v0.9.13 differences listed) | ca | `01M6A9QDN1GQ20347W16EM0D3X` |
| the BFF's door reading the delegate file, with `door: bff` | lane/01 (packet placed 11-04) | `01M6KF81WMJJXVKQAP12M0QTMY` |
| `gateway_routes.json` in a dag-tools release | dag-tools owner, Chris merges (packet placed 11-04) | `01M6KF821P2C3KRQN86FF0N61N` |
| gov's import of that json | blocked on the row above | `01M6KF8279KZ843KG5MMM0R3YH` |
| v0.9.14 on the index (closed-network installs) | ca | `01M6JJVP0KKT9HAM99YX2TEDBZ` |
| the five person-refusal seals, red since #229 | lane/01 | `01M6JJVP4ZEWGEENN2P067EBPX` |
| one `topaz_sync` at 0.4.76 or later, then the roll | Chris | `01M6FMQYFY8K233JWP2HXN91ED`, `01M6AJR52DDXSJPFKQ12WG08J3` |
| the gateway's reader for the delegate list | lane/01, architect | `01M6FZQ9TK0F5VQS2E1ERZ927Y` |
| the gauge, read rather than measured until a chart with #213 rolls | lane/01 | `01M6FZQ9ZCBFZCCEGWGFH2HW6G` |
| the remaining `sys.modules` files | lane/01, saf | `01M6FRZ3K5477A0CNFKW1D9BBM`, `01M6FRZ1Z5BNQ9GQ85GY72YRPC` |
| the remaining kind-audit sites | lane/74, lane/01 | `01M6FRZ2PKYJKHX9FW4W18T24A`, `01M6FRZ3QPBAN8D1R97TTWEC3K` |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |

## Next (in order)

1. Read #256, #262 and master, and the inbox in the master tree's `sessions/`.
2. **When #256 is on master:** rebase or merge master into #262 and add the board commit (pattern: the `gb_board.py` script from #254): move `01M6A9QDN199K1WE2H3QN3ZVQ9` to review/done with #262 added, write item 13 above, re-render with `scripts/render_board.py`, run `--check` and the 23 board tests. `blocked_on` non-empty iff blocked. If master moved, re-read the changelog head: #262's block sits under `## 0.4.79 — not yet cut`.
3. **When ca tags v0.9.14:** re-pin in one commit (the 17 pyprojects, 17 locks and `values.yaml`, per `docs/runbooks/pinning-the-fleet-sdk.md`), and drop the `index` caveat. Read the published wheel's version before pinning, because v0.9.13 built as 0.9.12.
4. **When dag-tools ships the json:** start `01M6KF8279KZ843KG5MMM0R3YH`. The json replaces `GATEWAY_ROUTES` and `GATEWAY_ROUTES_READ_AT`, and the read-at seal goes with them.
5. **Later, as ruled:** the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`).

## Scratch (session scratchpad, not durable)

- `ct` (own venv, v0.9.13) holds #262; `rp` holds #256; `gs` (#254, merged) can go.
- `ep_pr.md`, `ep_packet_ca.md`, `ep_mut.py` (the 8 mutants) are drafts in the scratchpad.

## Lessons

- **A dropped premise has siblings.** The validator's "the SDK isn't importable here" comment justified three forks; the ruling retired one. Grep the premise, not the fork, and file the siblings as an item rather than widening the PR.
- **A global substitution misses the unquoted form.** The edit script's quoted-kind replace skipped the COLLISION message, where kind names appear bare. Grep every FORM of a renamed string before trusting a rename.
