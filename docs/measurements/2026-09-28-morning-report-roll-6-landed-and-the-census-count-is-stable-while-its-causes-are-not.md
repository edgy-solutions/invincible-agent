# Lane 1 — morning report, 2026-09-28: roll #6 landed, and the census count is stable while its causes are not

**Lane:** `invincible-agent/master` · **Dispatch:** overnight items 1–5, all five closed or reported
· **Fleet:** revision 155, uniform on `ec055c49`, never degraded

---

## The five items

| item | state | where |
| --- | --- | --- |
| 1 — docs defects named with owners, sealed | committed `fadda10f` | prior report |
| 2 — lineage split in the gateway | committed `d3944da8` | prior report |
| 3 — MESH in `scope_domains` for the vector path | **seal CONFIRMED live; the delta is NOT COMPUTABLE** | `2026-09-28-item-3-measured-on-the-deployed-payload…` |
| 4 — stub harness restores `sys.modules` | committed `f17df904`, stability control run | `…the-lineage-split-and-a-stub-harness…` |
| 5 — arm, fire, census, HAZ-1003 row | **fired twice, LANDED at revision 155** | `2026-09-28-roll-6-fired-and-the-cluster-cannot-authenticate…` |

## What happened to the roll

Fired 09:45 with every gate satisfied, and it could not land: all 20 new pods took **403 Forbidden from
ghcr's token endpoint** while every payload package answered **HTTP 200 anonymously**. The cluster was
presenting a credential ghcr rejected, which makes a stale pull secret strictly worse than none.

**My gate had read the registry as me.** `docker manifest inspect` answers a question about my docker
credentials; the consumer is the kubelet, with a different identity nothing in the gate ever asked
about. Image existence and image pullability are different properties and I had verified only the
first. Roll #5 taught the fleet to separate a build's claim from a registry read, and I applied that one
step short of the consumer.

The remediation was then proved **from a node** — a pod with no pull secret pulled the payload image in
23s, which is what the gate was missing and it costs 23 seconds. A human rotated the credential at
20:27:03, and the re-fire at 20:31:25 landed: **`STATUS: deployed`, revision 155, 31 of 31
`invincible-agent` containers on the payload sha, every deployment at full ready count.** Nothing was
ever down — the rolling update held roll #5's replicas for the ten hours in between.

Two process notes worth keeping:

- **Leaving the blocked helm client alone was right, and is now measured rather than argued.** It
  reached its own 100m timeout and finalized `failed`, which the re-fire could proceed from. An outside
  kill would have left `pending-upgrade`, which refuses the next upgrade. The script's warning about
  that was a claim; this run is the check it was owed.
- **The action I was refused was unnecessary.** The classifier declined my deletion of the leftover hook
  pod; helm's hook delete policy replaced it on its own and the new hook primed and completed. My
  stated reason for wanting it — that the rollout might stall on it — was a prediction, and it was
  wrong. A denial is not evidence that the denied action mattered.

## ⛔ The docs census: the count is identical three times and the causes are not

Three fires, `repo=cee1ef73`, `fleet=ec055c4` (uniform — the prior census read
`fleet=MIXED(b5eeb40,c000514)`), `rows=20`, five rows selected:

| | fire 1 | fire 2 | fire 3 |
| --- | --- | --- | --- |
| aggregate | `0 pass, 5 fail, 0 blocked` | **identical** | **identical** |
| `safety-haz-1003-risk-assessment` | `disposition 'drawn', row accepts ['task_requested']` | same | same |
| `docs-what-is-an-archetype` | `0 row(s) under 'sections', floor is 1` | same | same |
| `docs-how-do-i-add-an-engine` | **route miss** — verb `UNKNOWN` lacks `explain`, `route_status='no_match'`, fell back `subject_unknown` | `disposition 'slot_required'` + archetype `ELICITATION` lacks `KNOWLEDGE_DOCUMENT` | same as fire 2 |
| `docs-how-do-i-add-a-canvas-template` | `disposition 'slot_required'` + archetype `ELICITATION` | same | **the route miss** — fire 1's diagnosis, on a different row |
| `docs-how-do-i-roll-a-service-abstains` | `disposition 'drawn'` | same | same **plus `route_status='infra_error'`, fell back `infra_error`** |

**Three of five rows report a different cause between fires, and the aggregate is the same every
time.** The route-miss diagnosis sits on `add-an-engine` in fire 1, on `add-a-canvas-template` in fire
3, and on neither in fire 2. An `infra_error` — a different failure class entirely — appears once in
three fires.

⛔ **Whichever single fire you ran, you would have named a different defect and had no way to know.**

### The attribution is sound, and that is what makes this a finding

The competing explanation was that the runner crosses results between rows, which would make the
variation an artifact of my instrument rather than a property of the system. It does not:
`scripts/walk_census.py:249` loops `for row in rows:` sequentially, and line 261 appends
`{"row": row, "state": state, "why": why}`, carrying each row object with its own result. No `zip`, no
`gather`, no `ThreadPool`, no positional pairing anywhere in the file. So the diagnoses belong to the
rows they print under, and **the deployed docs walk is nondeterministic per call.**

⛔ **The prior census recorded byte-identical output across three fires, and cited that as its evidence
of determinism.** That property is gone at this revision while the number it was attached to is
unchanged. **An aggregate that repeats is not evidence that the system repeats** — it is the most
stable and least informative reading available. This is the same shape as item 4's suite counts (5147
against 5146 at a fixed tree) reached by a different mechanism: the summary figure was the one that
looked trustworthy and the one that carried no information.

It also inverts a reading I recorded earlier: byte-identical rows across fires are *weaker* evidence
than differing ones, because they cannot distinguish repeated work from a cached or short-circuited
answer. Here the differences are what prove three fires each did the work.

### The HAZ-1003 row, as the dispatch asked

`disposition 'drawn', row accepts ['task_requested']` — **stable across all three fires** and unchanged
by items 1–3, which is the expected result since no item touched it. Still **owner 74**: the runner's
own note says `row_in_human_tasks` is not checked by this runner and 74 owns it. Measured here, not
diagnosed here.

## Leg 11a, with its filter defect repaired

The pre-fire baseline filtered on `invincible-agent` in the image path and so read **19 of 54** running
workload rows — the other 23 are served from other repositories and registries and were excluded **by
construction**. The filter let in exactly what I expected to find. Repaired reading: all 54 rows, and
**31 of 31** `invincible-agent` containers on the payload sha.

The repaired count then produced a surprise that was not one — 31 against the baseline's 19. **31 is
pod rows; 19 is workloads**, two generations of the same nineteen caught mid-reap. Only the identity
comparison settled it, and it had to be run in **both** directions: the `pre`-not-`post` direction is
the only one that can catch a workload disappearing. Result 19 = 19, no additions, no losses.

## Item 3 in one line

The seal holds live — a **MESH-graph class returned to a `DOCS`-scoped caller**, three fires — and
MAINTENANCE recall is undisturbed. **The delta the dispatch asked for cannot be computed**: no
before-reading of the candidate pool was ever taken, and the window closed when the fleet moved past
the pre-fix code. Recovering it would mean rolling the fleet back, which nothing authorises. One row
survives as a legitimate before/after on a single instrument: cold-start fallbacks on docs questions,
engine-o stdout, **9/9 → 0/3**, with four readings establishing that the zero is a real negative rather
than a marker that no longer exists.

Recorded there and **not item 3's business**: the DOCS path reports **0.97–0.99 confidence over a
candidate pool of one**, nine of ten candidates having been removed ahead of the classifier by gate
`productive_option`. A classifier handed one option cannot discriminate, so that figure must not be
cited as resolution quality. Whether that gate should remove nine of ten is its owner's question.

## Owed, and not done

- **The docs census is 0 of 5, and three of its five causes are unstable.** The next diagnosis needs
  repeated fires per row rather than one pass, and the instability may be the first defect to chase —
  it is upstream of every per-row conclusion anyone would draw from this walk.
- **The `infra_error` seen once in three fires.** Not diagnosed, and a single occurrence is a sample.
- **The pre-gate candidate pool** on the docs path: I read what survived `productive_option`, not what
  entered it.
- **HAZ-1003 stays with 74.**
- **Five commits are unpushed** (`1fe3ebbf`, `77592bd8`, `2548b8b8`, `3aa25367`, `cee1ef73`, plus this
  one). They were held through the roll deliberately — `git rev-parse origin/master` is what the fire
  derives its payload from, so moving it mid-roll would have changed what was being rolled. The roll
  has landed, so the hold can be released.
- **The inbox census must report the architect seat's count as `unenumerable`, not clear**, until every
  seat-addressed packet parses. A count over a population where some `to:` lines are silently dropped
  cannot distinguish "no packets for that seat" from "packets in a form the parser discards" — and the
  seat most exposed is the lane-less one, whose only evidence of existing *is* a packet addressed to
  it, so its gap reads as a clean zero.
- **The frontend bump pins the digest, not the head** — `60e245a` has no image.
