to: invincible-agent/lane/01 (worktree ia197, branch lane/01-202)
from: invincible-agent/lane/01
date: 2026-10-21

# Handoff: the freeze holds until the dry run. Then roll 205, and then one release for the registry read

## State at handoff

- `master` = `lane/01-202` = `7a42d4bd`, plus this file. The chart is `invincible-agent-0.4.62`, published.
- The sandbox runs 204 at helm rev 212: the BFF and engines at `6f0c12ea`, cortex at `@sha256:c3a2acdd`. Every workload is pinned by sha or digest, so a master build moves nothing.
- **Freeze: nothing rolls, primes or fires until after the dry run, except a recovery.**
- `/source` at `awaiting_kind` already holds live on 204. Sealed in `42f9945c`. Cortex may use it now.

## Next step 1: roll 205 (after the dry run)

- 205 = `ad564907` (bbox may be null; page may not). It is in master but has no image of its own.
- Build at master HEAD with `build-containers.yml`, then follow the full roll procedure:
  1. dagster in-flight check;
  2. `upgrade-sandbox.sh --set global.imageTag=<fullsha>`;
  3. rollouts;
  4. health ×3;
  5. q9login.
- Then tell 7f to send `bbox: null` with `page`, instead of leaving out a candidate with no box. Tell cortex it is live.

## Next step 2: one release, every part landing together (all ruled; build after the dry run)

| part | ruling | blocked on |
| --- | --- | --- |
| `arrives_as` (tuple, default `()`, `cad` legal) on the nine overlay rows. Leaves = domain-declaring kinds whose `arrives_as` has the row's format. The literal `ingest_status.LEAVES` goes. The picker and `/leaf` stay PDF-only (Q2: no) | leaf rule (a) | ca's SDK release with the field; bump the pin from `v0.9.10` |
| `review_shape` (`notice` for pcn and pdn, `document` for work-instruction). A `document` review: source pane, header fields (title, doc id, revision, date), header edits, no parts table. Reject codes `wrong_kind`, `unreadable`, `duplicate`; the four notice codes stay notice-only. Routes to `document_promotion:MANUFACTURING`. A kind with no shape is refused (asked of ca) | Q1 | ca (packet placed, the same release as `arrives_as`); 7f's answer on what a work-instruction extraction contains |
| `allowed_leaves: [{leaf, label}]`, read from the registry, on the status row and on the review route. Cortex deletes its hand-written lists. **Neither ships without the other** | rulings 1 | the registry read above; cortex lands its side in the same release |
| Accept the plural `work-instructions` on read for ONE release, then refuse it. Send cortex and 7f a captured row showing the singular on the wire | rulings 2 | 7f renames it in KIND_MAPPING. The BFF, policy and runner have no plural today |
| **The producer writes the wire shape** (supersedes rulings 3). 7f emits `wire_evidence_ref {page, bbox, note?}` on every row, in fractions. A row with several boxes gets their union, with note "n boxes". The BFF serves it AS IS: no renaming, no synthesizing, no `page_dims`. The BFF's evidence-reshaping code goes: gateway.py:1972 and :11673 (`page_dims` passthrough) and ~11658 (the build from `bboxes[0]`). Old rows WITHOUT `wire_evidence_ref` keep today's path, `page_dims` included, until they age out. **The seal, Lane 1's leg:** a 7f fixture row through the real BFF route comes out byte-equal to 7f's `wire_evidence_ref`, with no `page_dims` key. Add a control: an old row still gets today's shape | the producer-writes ruling | 7f's emitter and its fixture row. Rolls in the release with cortex `9be5963` or later |

The measurement behind Q1 and Q2 is in `sessions/2026-10-21-report-to-architect-work-instruction-as-a-pdf-leaf-measured-the-set-widens-the-review-is-notice-shaped.md`.

## Waiting on peers

- ca: `arrives_as` and `review_shape` in one SDK release, plus the tag.
- 7f:
  - the work-instruction extraction contents;
  - the title read's `doc_type` vocabulary for a work instruction;
  - whether a re-run after a re-class switches to the manufacturing pipeline;
  - the KIND_MAPPING rename and mirror;
  - the `title_leaf` calls; step 5; the review-row fraction conversion.
- 74: the three-principals arm and the re-walk.
- saf: the FRS-flip ruling.
- openddil: their five case ids.

Housekeeping is closed. The stale session copies are cleared, and worker6 was diagnosed as power: the supply is swapped tonight and its logs stream off-box. No one owes anything there.
