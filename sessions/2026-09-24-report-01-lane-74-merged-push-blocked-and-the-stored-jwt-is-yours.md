---
to: Chris, and the architect on item 1's second half
from: invincible-agent/master (Lane 1 seat)
date: 2026-09-24
subject: lane/74 merged at fa1b5cc — the push is blocked and needs you; the order's "four
         commits" was nine, two of them code; the stored JWT is live and neither remedy is mine
---

# Headline

**The merge is done locally and verified. The push is blocked** by the permission classifier, so
`origin/master` is still at `ced8fdf`. Everything downstream of it — item 2's arm, item 3's
re-launch — waits on that one action, which is yours.

**The order's premise was stale.** It said four commits. The pinned tip carries **nine**, and two
of them carry code in two deployed engines. That materially changes what item 2's gate must cover,
so I am not carrying the old arm forward.

**The stored caller JWT is live.** I merged 74's report; merging a report is not fixing a defect.
Both remedies are named below and neither is this seat's.

# Item 1 — the merge

Merged `lane/74` at `b12f0ddaf0e5e226d5f378efad6667b985286b55`, confirmed by `git ls-remote`
immediately before merging as still the remote tip (it had moved once during my earlier
measurement, which is why it was pinned to a file). Merge commit **`fa1b5cc`**, parents
`ced8fdf b12f0dd`, `Lane:` trailer derived not typed.

**Nine commits, not four.** The four the order describes are lane/74 as it stood at 21:36 on
2026-09-23 (`019a3b6`). Read as stale rather than restrictive, because the order also tells me to
read the stored-JWT packet, and that packet is commit **five** (`153cb96`) — the order already
reaches past its own count. I merged the tip.

**Two of the nine carry code, which the "four commits" framing did not describe:**

| commit | kind | files |
| --- | --- | --- |
| `4432111` | **feat(cost)** | `agent_fleet/cost_agent/instances.py`, `agent_fleet/cost_agent/main.py`, `policy/graphs/cost_lot_costing_review.yaml`, + a 170-line test |
| `bc998f4` | **fix(engine-o)** | `agent_fleet/ontology_service/main.py`, + a 292-line test |

The other seven: five `sessions/` packets, `docs/runbooks/backfilling-the-vector-space.md`, and the
`setup/ontologies/docs_corpus.ttl` regeneration.

**How the merge was verified, and one trap avoided.** `git diff master..b12f0dd` reports 27 files,
1565 insertions, **1908 deletions** — and every one of those deletions is a master-side file the
lane simply predates. A two-dot diff is not a merge preview. I trial-merged with
`git merge-tree --write-tree` (no working-tree mutation), got tree
`742601714c586afc39ca8421b5a33da96e1e22a9` with **rc=0, no conflicts**, and checked both directions
by name:

- master-only files **KEPT**: `scripts/bm25_vs_hybrid_arm.py` (absent at merge-base `c6436ee`,
  added on master, absent on the lane — the largest apparent "deletion"), the prime measurement,
  the morning report, ADR-0038.
- lane-only files **KEPT**: both new test files, the backfill runbook, the stored-token report.

The real merge's index tree came out byte-identical to that trial tree, and
`git rev-list --count HEAD..b12f0dd` is **0** — nothing left behind.

**The two new tests, run against the merged tree** (consequence-scoped, not the full suite):
`13 passed, 0 skipped, rc=0` in 4.14s. The skip count matters — a skip would be a test that did not
run, wearing green.

**The one file both sides touch resolved cleanly.** `setup/ontologies/docs_corpus.ttl`: master's
blob is identical to the merge-base (master never touched it), the lane regenerated it, the merge
takes the lane's. No conflict.

# What needs you — the push

`git push origin master` was **denied by the permission classifier.** The order states you granted
the push; the classifier does not know that, and I am not going to route around it with another
tool. One approval unblocks items 2 and 3 together.

Note what the push does besides publishing the merge: `build-containers.yml` triggers on every push
to master with **no path filter**, so it will build a fresh 17-image set at the new head. This time
that is not incidental — the merge changes code in two deployed engines, so the new images differ in
substance, not just in tag.

# Item 2 — roll #2, and why the old arm cannot be carried forward

**The `ca23e9e` arm is void for this head, and not merely out of date.** That arm was verified over
a docs-only delta: I measured **0** files under `helm/ src/ agent_fleet/ setup/ scripts/ policy/
schemas/ sql/ baml_shared/ .github/` and no `.py`, with the matcher positively controlled against a
range that did touch the chart. That premise is now false — this merge lands
`agent_fleet/cost_agent/*`, `agent_fleet/ontology_service/main.py` and
`policy/graphs/cost_lot_costing_review.yaml`. Firing the old arm would deploy a verified-empty
delta while the tree holds a behavioural one.

**Re-arming is blocked on the push, not on me.** Two of the gate's legs cannot be run until the
push triggers CI:

- 17-images-exist-with-arm64 **at the arming sha** — the images do not exist until the build runs.
- both CI workflows green at that sha — same dependency.

The legs I can run without it (`--dry-run`, the full-manifest diff, the four sibling digests
re-read immediately before firing) are worth nothing dated earlier than the images they describe,
so I will run the gate as one pass once the push lands. **Nothing will be fired.** You fire on go.

# Item 3 — blocked on your reboot, and one banked figure is now void

Fingerprints re-derived from the merged head, because the merge changed one of the two inputs:

| file | bytes | md5 |
| --- | --- | --- |
| `setup/ontologies/mesh_system.ttl` | 68293 | `34dc125f324c90644bfa67c659fe8ca5` |
| `setup/ontologies/docs_corpus.ttl` | 5573 | `98138798082bf32836ef09f950e5456d` |

**The figure I had banked for `docs_corpus.ttl` — 5573 bytes, md5 `ad77ab1349…` — is void.** The
merge changed its content and left its **byte count identical at 5573**. The diff is a `body_sha`
and a `source_committed_at` swapped for the same page, and two hex digests are the same length:

```
- mesh:body_sha "b42ace7e…"   mesh:source_committed_at "2026-09-19T22:17:01-05:00"
+ mesh:body_sha "4c483230…"   mesh:source_committed_at "2026-09-23T21:20:39-05:00"
```

A size-only comparison would have called this file unchanged and re-uploaded stale bytes with an
`[OK]`. That is the same instrument defect that produced the null prime, one layer in: last time
`ContentLength` differed and I caught it; here it would not have. **The S3 comparison for item 3
must be on content, not on length.** I will re-derive both fingerprints again immediately before
uploading rather than trusting this table — the tree is shared.

The item-3 seal's target numbers, read from the merged tree rather than restated: `mesh_system.ttl`
declares **75** classes, contains `mesh:Thing` (**1**), and carries exactly **1**
`mesh:universalReferent true`. So the order's "expect Neo4j 73→75, one universal_referent" agrees
with the file.

# Item 1's second half — the stored caller JWT

I read 74's report in full. It is a sound, well-controlled finding and I am escalating it rather
than filing it.

**What is measured:** five distinct bearer tokens in **fifteen plaintext copies at rest** in the
`iagent` Postgres, across three sites (`checkpoint_blobs` channels `identity` and `__start__`, and
`checkpoint_writes.blob`), each a well-formed three-segment JWT of 1361–1402 bytes, **no expiry**,
retained **four days or more**. The matcher was controlled in both directions — `payload` and
`artifact` fire 15/15 and 12/12 through the identical query path that returns 0 on the identity
channel — and 74 discarded an earlier control (`channel = 'program_id'`) precisely because it could
not fire. That is the right instinct and it is why I trust the count.

**Why it is not a coding mistake.** Threading the caller's credential is ADR-0049 Ruling 1. The
defect is that a durable saver silently converted an in-flight credential into an at-rest one:
`agent_fleet/graph_host/main.py:494` assigns `state["identity"] = identity`, and a durable
checkpointer persists state channels by construction.

**Why a per-graph fix would be a guard that cannot fire.** The mechanism is in the **host**, not in
any one graph. `checkpointer: true` is set on one of two ratified rows today;
`cost_lot_costing_review.py:99` leaks the day that flag flips. Fixing `fin_program_brief` alone
would leave a remedy that looks like protection and protects nothing.

**74 did not decode the tokens.** The safety classifier refused, 74 calls that refusal correct and
did not route around it, and no replayability is asserted. I did not decode them either.

**Neither remedy is mine, and merging the report is not one of them:**

1. **The design change is the architect's.** 74 names three options without choosing:
   redact-on-persist; keep the credential out of checkpointed state and pass it per-super-step as
   non-persisted config; a short row TTL. Choosing between those is an ADR-0049-adjacent ruling.
2. **Deleting the fifteen rows is a store write, and that is Chris's.** 74 built the `--apply`
   path and did not fire it.

I have done neither and will not without a named instruction.

# Item 4

The suite, once, alone, after items 2 and 3. Not attempted. It was deferred overnight on a measured
precondition — 0.5 GB free of 31.7 GB, paging file 20142 MB against a 23392 MB peak — and that
measurement predates your reboot, so it must be re-taken rather than reused. A suite run under the
old condition would be **void rather than red**, which is worse than not running it.

# State

- `master` local: **`fa1b5cc`**, clean. `origin/master`: **`ced8fdf`** — one merge commit unpushed.
- Untouched in the tree: three untracked inbound `2026-09-23-packet-from-ca-*` packets
  (include-referents, mode-vocabulary, NetworkPolicy chart gap). Not mine; left uncommitted.
- 74's report, now on master: `sessions/2026-09-23-report-74-a-stored-token-a-citation-with-no-referent-and-one-import-idiom.md`
