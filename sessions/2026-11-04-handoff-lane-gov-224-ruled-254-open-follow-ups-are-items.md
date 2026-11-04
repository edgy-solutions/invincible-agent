# Handoff: lane/gov, 2026-11-04 (#224 ruled and built as #254, open; #247 and #248 merged)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-04

This replaces `2026-11-04-handoff-lane-gov-fork-2-is-247-ready-not-merged-v0-9-13-has-a-defect.md`. Fork 12 and the lessons in older handoffs still stand.

## The rulings since (via Chris, verbatim)

> gov: #247 merges now; closed-network installs wait for ca's v0.9.14 on the index. Nothing else.

> from the architect, via Chris — #224, the three delegate-list readings
> 1. Right list. policy/gateway_delegates.yaml is the central gateway's list: which service may act for a person, on which gateway route. The BFF's DELEGATE_ON_BEHALF_OF stays as it is today, but it is the second internal door and it reads the same file at the next cut (one list, two readers; a BFF-only row carries `door: bff`). Scheduled item for Lane 1, not a retrofit in #224.
> 2. First row stands: svc:data-analyst on assets.authorize, from A2. Add `reason:` and `ratified_by: owner` to the row; every row carries both from here on. A pipeline run with no person is `pipeline:<name>`, never a delegate row.
> 3. GATEWAY_ROUTES as a constant fails the standing rule (code copies what the server serves). dag-tools publishes the route-id list as data in its package (gateway_routes.json, owned where the routes are); the validator imports it. Until that ships: keep the constant, mark it with the dag-tools sha it was copied from, and add a test that fails when the pinned dag-tools digest changes without the constant being re-read. dag-tools agent: ship the json in the #3 rebase or its own PR; Chris merges.
> Close 01M6G57K5VSQVAKPZG029AYEQ2 when (2) is in.

## State

| PR | what | state at writing |
| --- | --- | --- |
| #254 `lane/gov-delegate-rows-ratified` | readings 2 and 3, plus the board: closes `01M6G57K5VSQVAKPZG029AYEQ2` and writes the three follow-up items | open, MERGEABLE, head `bd081765`. The merge is lane/01's. |
| #247 | fork 2 and the fleet pin to v0.9.13 | merged `a8152e2b` (Chris: "merges now") |
| #248 | board moves | merged `b22b9b22` |

#254 was measured in-process on `6969a16e`. The 53-file area run (tests/security plus the policy-rail tests) gave 1299 passed, 1 xfailed, 0 failed. The delegate rail gave 49 passed, and 6 of 6 mutants were killed. `test_a_chart_change_bumped_the_chart_version` is red until lane/01 cuts 0.4.79. Nothing ran live.

## Open forks

2. Fork 2's item `01M6A9QDN1M16XMBNHHWVK9EHJ` is still `review` on master, though #247 merged. I didn't move it, because Chris said "Nothing else". Move it to done in the next board commit he approves.
12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| merge of #254 (it closes the readings item) | lane/01 | `01M6G57K5VSQVAKPZG029AYEQ2` |
| the BFF's door reading the delegate file, with `door: bff` | lane/01 (packet placed 11-04) | `01M6KF81WMJJXVKQAP12M0QTMY` |
| `gateway_routes.json` in a dag-tools release | dag-tools owner, Chris merges (packet placed 11-04) | `01M6KF821P2C3KRQN86FF0N61N` |
| gov's import of that json | blocked on the row above | `01M6KF8279KZ843KG5MMM0R3YH` |
| v0.9.14 on the index (closed-network installs) | ca | `01M6JJVP0KKT9HAM99YX2TEDBZ` |
| Chris's go-ahead to adopt `GRANTED_BY_SEED`, which #247's merge unblocks | Chris | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
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

1. Read #254 and master, and the inbox in the master tree's `sessions/`.
2. If master moves before #254 merges, re-read the changelog head. #254's entry sits under `## 0.4.79 — not yet cut`, and a cut entry is never edited. If another board PR lands first, re-render the board.
3. **When ca tags v0.9.14:** re-pin in one commit (the 17 pyprojects, 17 locks and `values.yaml`, per `docs/runbooks/pinning-the-fleet-sdk.md`), and drop the `index` caveat. Read the published wheel's version before pinning, because v0.9.13 built as 0.9.12.
4. **On Chris's word only:** adopt `GRANTED_BY_SEED` (`01M6A9QDN199K1WE2H3QN3ZVQ9`), and move fork 2's item to done.
5. **When dag-tools ships the json:** start `01M6KF8279KZ843KG5MMM0R3YH`. The json replaces `GATEWAY_ROUTES` and `GATEWAY_ROUTES_READ_AT`, and the read-at seal goes with them.
6. **Later, as ruled:** the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`).

## Scratch (session scratchpad, not durable)

- `gs` (own venv, v0.9.13) holds #254.
- `rp` (own venv) is detached at `6969a16e` and free.
- `ct` (own venv, v0.9.12) is detached at `8a2717e0`.
- `bd` (#248, merged) can go.

## Lessons

- **Name what the area run covers before you rely on it.** The chart-version test wasn't in my 53-file selection, so the run's green said nothing about it. I ran it separately. Before the commit it was red twice, because the CHANGELOG was uncommitted chart content.
- **A mutation's filter can survive a mutant on its own.** A `FAILED (\S+)` match drops param ids that contain spaces, so a killed mutant reported as SURVIVED. Read the failed list before believing a survivor.
- **A per-roll overlay isn't the pin of record.** `values-roll-frontend-digest.yaml` still pins a 09-26 gateway image. The read-at seal excludes it and says why, and lane/01 has the packet.
