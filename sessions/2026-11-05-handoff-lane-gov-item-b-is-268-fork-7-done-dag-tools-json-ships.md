# Handoff: lane/gov, 2026-11-05 (ADR-0064 item B is #268; fork 7 done on master; dag-tools 0.11.0 ships the json)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-05

This supersedes `2026-11-04-handoff-lane-gov-fork-7-loader-half-is-262-254-merged.md`.

## The rulings since (via Chris, verbatim)

- "gov: #262 lands → fork 7 done + fork 13 item. Then can_read:<level> rail + levels registry file (ADR-0064 B), validator only, no reader yet."
- Item B (architect via Chris, 11-05): "B. Topaz rails (gov): `can_read:<level>` as a rail file — one row per level → groups, ratified_by: owner; levels themselves a registry file the rail validates against. No code reads it until dag-tools step 5 serves a dataset's level."
- The standing rule: "levels, sources, access modes and downgrade rules are registry rows; nothing in dag-tools or iagent names a database, schema, table, column, program or level in code."

## State

- **#262 merged** as `75c5c95a`. **#256 merged** as `18cb5d02`; its board commit `0dd6e428` moved fork 7 (`01M6A9QDN199K1WE2H3QN3ZVQ9`) to done and wrote fork 13 as `01M6MZX82P0XT6HX984DZEXMV9`. Fork 7 is done on master.
- **Item B is #268**, branch `lane/gov-level-readers-rail`, head `aeab31b4`, base master. Its board item is `01M6N17JBZK14V4MTTEQQ3HYWZ` (review).
  - It adds `policy/classification_levels.yaml` and `policy/level_readers.yaml`, both empty, the grantor seed `policy/grantors/level_readers.yaml` (`object_scoped: true`), the `validate_policy` checks (run when present, not in `DATA_FILES`), and the seal `tests/security/test_level_readers_rail.py`.
  - What ran: the seal gave 45 passed, and 11 of 11 mutants were killed. The area run on the merge with master gave 1215 passed, 1 xfailed, 0 failed.
  - **No CHANGELOG entry.** `29c10087` took the block out (see "0.4.79 is published" below). Its text is in #268's description.
- **The architect packet is placed** (master tree `sessions/2026-11-05-packet-to-architect-from-gov-adr-0064-item-b-is-268-three-forks.md`). It raises three forks: one levels file or two (with dag-tools' `classification/levels.yaml`), monotonicity across levels, and the Topaz relation name, since `can_read` is already live.
- **0.4.79 is published** (Lane 1's 11-05 packet). `invincible-agent-0.4.79` was cut at 21:35Z on 11-04 from `758811d7`. Since then, any `helm/**` change without a `Chart.yaml` bump turns master's post-merge release job red. **#262's CHANGELOG block was one of the two merges that did** (the other is #260). The CHANGELOG's "0.4.79 — not yet cut" header is wrong. Lane 1 is splitting it in #267, and Chris names the number. Until then, gov puts nothing under `helm/`.
- **`test_board_drift.py` is red on master**: `docs/BOARD.md` is out of sync with `docs/plans/*.md`. It goes back to fin's #255. Not gov's, and it was reported on #256.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
13. `01M6MZX82P0XT6HX984DZEXMV9` (open, later): `validate_policy.py`'s content kinds and review shapes rest on the "no SDK here" premise #262 dropped. Measure the premise in the image before relying on it.
B. The three forks in the architect packet, on `01M6N17JBZK14V4MTTEQQ3HYWZ`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| the architect's read of #268's three forks, and #268's merge | architect, lane/01 | `01M6N17JBZK14V4MTTEQQ3HYWZ` |
| ADR-0064 itself (#266, Proposed, held for the architect) | architect | — |
| the 0.4.79/0.4.80 CHANGELOG split, and the number | lane/01, Chris | #267 |
| the engines reading `export_profile_sources.yaml` via the SDK | ca | `01M6A9QDN1GQ20347W16EM0D3X` |
| the BFF's door reading the delegate file, with `door: bff` | lane/01 | `01M6KF81WMJJXVKQAP12M0QTMY` |
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

1. Read #268 and master, and the inbox in the master tree's `sessions/`.
2. **Unblocked, waiting on Chris's word to start:** `01M6KF8279KZ843KG5MMM0R3YH`. dag-tools' 11-05 correction packet says `edgy-dag-tools==0.11.0` carries `dag_tools/central_gateway/gateway_routes.json` (built from `4924235`). Pin it, read `delegate_rows_may_name` through `from dag_tools.central_gateway.routes import route_ids, delegatable_route_ids, load_routes`, and drop `GATEWAY_ROUTES` and `GATEWAY_ROUTES_READ_AT` along with the read-at seal. Never decide from the route id, the module or the `authorization` value. The tag was pushed at the wrong commit and repaired within minutes, but the PyPI wheel was only ever built from `4924235`. Read the installed wheel's version before pinning. Move `01M6KF821P2C3KRQN86FF0N61N` along in the same board commit.
3. **When the architect rules #268's forks:** build what is ruled on the same branch if it is still open, or as a follow-up item.
4. **When ca tags v0.9.14:** re-pin in one commit (the 17 pyprojects, 17 locks and `values.yaml`, per `docs/runbooks/pinning-the-fleet-sdk.md`). Read the published wheel's version first.
5. **Later, as ruled:** the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`).

## Scratch (session scratchpad, not durable)

- `lv` (own venv) holds #268. `ct`, `gs` and `rp` hold merged PRs and can go.
- `mut_lv.py` (11 mutants), `lv_pr_2.md` (#268's description) and `lv_spec.md` are in the scratchpad.

## Lessons

- **A release guard has its own path filter.** `release-helm-charts.yml` runs on any `helm/**` change, and a CHANGELOG edit is `helm/**`. Once a version is published, a CHANGELOG-only block with no bump is a master red. Before adding one, read whether the CHANGELOG's head version is already published.
- **An nth-occurrence mutant can hit a neighbour.** The `ratified_by` check appears three times in `validate_policy.py`. Occurrence 1 is the delegate rail, so the "survivor" was out of the seal's reach, and the rail's own check was never mutated. Count a mutant's target string, and name its enclosing function, before reading a survivor as a hole.
- **A relative interpreter path fails under subprocess on Windows.** `[".venv/Scripts/python", ...]` gave WinError 2 after the first mutant had already been written. Use `sys.executable`, and restore from the disk backup before anything else.
- **ia-gov's own tree has no `.githooks/lanes` and an old hook.** `--expected` prints nothing here, so derive the trailer from master's registry row (`ia-gov  lane/gov lane/gov-*`).
