---
to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-07
supersedes: 2026-11-06-handoff-lane-gov-g6-is-290-in-review-g5-waits-on-the-ruling.md
---

worktrees: under wt\gov\ (1 moved, 13 removed, 0 under %TEMP%)

# Where it stands

All four PRs are open, and Lane 1 merges them in the train. Nothing is owed on any of them until review comments arrive.

- **#288** (#282's tail, `lane/gov-282-tail`, head `79035e2b`).
- **#290, G6** (`lane/gov-me-entitlements-capabilities`): its head is now `a20c3972`. That merges master `3949ade8` because `board/BOARD.md` conflicted with Lane 1's sweep `b275ec37`; I re-rendered it. 48 passed on that tree. ingest-v1 is 1.7.0. Cortex takes `canExportBatch` once #290 is on master, and **gov owes cortex the merge sha**.
- **#298, G5** (`lane/gov-mcp-refusal-responses`, head `f0bfa3b1`, stacked on `a20c3972`; worktree `C:\Users\cnogr\git\wt\gov\mcp-refusal-responses`).
  - Every MCP route declares 401 (`UnauthenticatedBody`, a string) and 403 (`PolicyRefusalBody`, with `refusal` optional).
  - The door is split: an envelope (`config:DELEGATE_ON_BEHALF_OF`) only on the two `on_behalf_of` routes.
  - The seal is `tests/security/test_every_mcp_route_declares_401_and_403.py`. It lists the 13 envelope-less 403s exactly: 11 debt and 2 structural. 11 of 11 mutants were killed.
  - ingest-v1 is 1.8.0. The PR edits saf's seal at line 73, and a packet tells saf.
  - Item `01M6A9QDN17N491MVEMJR0NY52` is in review.
- **#300, the v0.9.15 pin** (`lane/gov-pin-mesh-v0-9-15`, one commit `a95f225e` on master `2255d2e4`; worktree `C:\Users\cnogr\git\wt\gov\pin-0-9-15`).
  - It moves 17 pyprojects, `meshSdkVersion` and 17 locks; every lock changes only the SDK's lines.
  - The closed-network comment now says `index` serves v0.9.15.
  - The chart CHANGELOG opens `0.4.82 — not yet cut`. **Chart.yaml is still 0.4.81**, which is published, so #300 rides Lane 1's 0.4.82 cut.
  - 164 passed, and validate_policy is OK.
  - Lane 74 rebases `lane/74-sdk-dsl` onto it once it merges.

# Worktrees (Lane 1's 11-07 rule)

- `dm` was moved to `wt\gov\mcp-refusal-responses`.
- These 13 were removed: `adr bd cc ct ex f181 gr gs lv mc od rp rr`. Every head is an ancestor of origin/master. Their "dirty" state was a temp cleaner's deletions; `rp`'s one modified file differed only in CRs. The branches are kept.
- `git worktree prune` also dropped Lane 1's stale `rel476` entry. Its directory was already gone, so this was metadata only.
- #288's and #290's branches have no worktree. To push to either, check it out again under `wt\gov\`.

# Packets placed in the master tree's sessions/ (untracked)

- **G5:** to the architect and saf, cc Lane 1 and ca (`2026-11-07-packet-to-architect-saf-cc-lane-01-ca-from-gov-g5-is-298-...`). It asks the architect to confirm two readings: the door split, and that the list cannot empty while the two structural sites send no refusal.
- **To cortex-ui/master:** #290 is not merged, its head is `a20c3972`, and #298 makes 1.8.0 follow it.
- **To lane 74, cc Lane 1:** the pin is #300, and the 0.4.82 cut question is in it.
- **7f** (doc-tools-18) sent gov a session message meant for lane/01, about the ADR-0063 episode key, reading (a) or (b). Gov said it is Lane 1's and the architect's to decide, and that its packet is already in the master tree's `sessions/`.

# Next step

1. Re-read the master tree's `sessions/` for packets to `invincible-agent/lane/gov`, and check #288, #290, #298 and #300 for review comments. When #290 merges, send cortex the merge sha.
2. Build the queued dispatch, which is verbatim: "gov: policy/registry/lifecycle_status.yaml exists as a file (IEC 62402 stages, generator named at release per 0056 §1); dimensions.yaml gains `required` and `empty_means` per dimension and per declared boundary (0055 amendment); SKOS export of both as a row." The standing rule applies: these are rows and files a deployment supplies; iagent ships the types and validators. Work in a new worktree under `wt\gov\`.
3. After that, the first unblocked `next` item in board order. That is "Answer 7f's 10-29 and 10-30 packets" (`01M6A9QDN1QSSWQ74F6JV74W0B`).
