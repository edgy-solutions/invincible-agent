to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-07 (18:12Z)
supersedes: 2026-11-07-handoff-lane-01-0-4-81-cut-green-values-diff-waits-on-chris.md

# 0.4.81 is rolled (rev 228); fin's live check runs under Lane 1's lock

## NOW: waiting on fin's live check, with the lock held

- **The roll:** Chris approved the diff, and the architect's 0.4.81 message (via Chris) set the order.
  - `iagent` rev **228** = `invincible-agent-0.4.81`, deployed, rc=0, 17:45–18:07Z.
  - The seal read 49 of 49 pinned by digest.
  - The live images equal the dry-run set, apart from curl and mc, which are hook-only.
  - Every hook completed, and task-grant-sync refused no group.
  - engine-fin carries `FIN_DATASET_URN` and `FIN_DATASET_BANNER`.
  - Every iagent pod was Ready at 18:08:47Z, and 7 of 7 nodes are Ready.
- **The roll lock:** `sandbox/roll-lock` is held as `invincible-agent/lane/01`, with an expected end
  of 19:25Z. If fin runs long, run `scripts/roll-lock.sh renew` from `<scratchpad>/rel481`.
- **Fin's packet:**
  `sessions/2026-11-07-packet-to-fin-from-lane-01-0-4-81-is-rolled-run-the-live-check-now-the-lock-is-held.md`
  (master tree, uncommitted). The check is a granted caller and a denied caller, 3 runs each, plus
  one CDRL export each.
  - **If either caller fails,** roll back to rev 227 under the same lock, and #280 is fixed forward.
    Tell cortex and 7f, because the case read goes back with it.
  - **If both pass,** release the lock (`scripts/roll-lock.sh release`). Then run the refile walk,
    with the `/me/entitlements` readiness step: read `authz_id` from the session, and treat a 200
    with empty entitlements as a failure. Then tell tr and 7f the lock is free, for tr's hour.

## Done this window

- **#292**, the board sweep, merged at `b1ac07be`. It closed four items with the architect's ruling
  texts:
  - `01M6A9QDN1DE3AN1MSJ33T1AJW`
  - `01M6A9QDN16Q03BPSJAPWDSAEP`
  - `01M6AJR52DDXSJPFKQ12WG08J3`
  - `01M6FMQYFY8K233JWP2HXN91ED`
- **#293**, ADR-0064, merged at `3723e511`. It records §1a as signed 2026-11-06, and cites ISO/IEC
  15459 and IUID, RFC 9562 and SX002D by concept.
- **#285** (lane/74, the binder tuple) merged at `3949ade8`. Before the merge, the ratchet passed 24
  and its own test passed 17. #271 was already in 0.4.81.
- **Packets placed (uncommitted):**
  - **architect:** the five unruled items, each with its question text, for Monday.
  - **cortex, cc fin:** the menu is an overlay `menu:` block, provenance travels, and the pin stays.
    A copy is in the master tree.
  - **cortex:** 0.4.81 is live, and the case panel can start.
  - **7f, cc tr:** the case fields are served, and the lock is not free yet.
  - **74:** #285 merged.
- `tests/test_citation_paths.py` has 2 reds on master: dead `docs/` links, cited from board items,
  a release note, a test and sessions. These are not Lane 1's diffs, and they belong to master's
  census owner.

## 0.4.82 (queued)

- **The FLOW_DECOMPOSITION row:** branch `lane/01-flow-decomposition-is-projected` (`01ef9bcb`),
  worktree `<scratchpad>/flowrow`.
  - The tuple gains `data_provenance` last, and the banner arm flips to "arrives verbatim". Cortex's
    row at `01fa3134` already carries it.
  - The menu placement comes from fin's `menu:` block on the #255 rows, and the BFF serves it. Wait
    for fin's PR.
  - Cortex asks whether a `mesh:` class is needed. That question goes to the architect; don't rule
    it.
- **MULTI_SERIES:** append `data_provenance` last, then send cortex the sha.
- **The cortex pin:** 0.4.82 pins `0dc5366` at `sha256:6cf3367b…`. Taking `01fa313` instead is
  Chris's call.
- **Cortex's in-place edit of board item `01M6T3M9MZ74CZJ4T0W6HRRW5Q`:** commit it with the next
  board change.
- **ADR-0067:** wait for OpenDDIL's draft. Then build the index check that a reference ADR's cited
  sha exists in the other repo (a pinned read, like `.github/doc-tools.ref`).
- **The v0.9.15 fleet pin:** gov's PR. 74 rebases onto it.

## Queued, unchanged

- Forks 1+3 (`01M6KF81WMJJXVKQAP12M0QTMY`), and ADR A–E.
- The alice Topaz delete, which goes to Chris.
- NetworkPolicy, in the order Jena → Weaviate → Neo4j, by 12-01.
- Clean up `<scratchpad>/rel480`.
- Items `01M6QGKGVF12QW1REN9K0K1HMB` and `01M6QGKFTKSD18ZAPMA285F25X`.
