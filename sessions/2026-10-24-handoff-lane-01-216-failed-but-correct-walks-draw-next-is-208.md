to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-10-24 (written 19:3xZ)
supersedes: 2026-10-21-handoff-lane-01-after-the-dry-run-roll-205-then-the-registry-read-release.md

This handoff carries no secret and no infra detail.

# Handoff: rev 216 is failed on record but correct in fact, both walks draw, and next is 208

## Where things are

**Trees and branches**
- This worktree is `ia193`, on branch `lane/01-bff-openapi`.
- Master is at `2705c335`: the merge of `95db114b`, the BFF OpenAPI document plus its drift test.
- `lane/01-ingest-v1` (`280ac323`) holds all of `lane/01-208` plus `1fb9e242`. Neither is on master.
- `lane/01-adr-0060` is at `a4d396fe`. ADR-0060 is still Proposed.

**The sandbox**
- iagent rev 216 (chart 0.4.67, image `867813be`) is recorded `failed`.
  - The images are right, the 60 s budget is live, and `mesh_system` was re-ingested (run `4054ce47`). Verbs: 202 / 57 / 147.
  - The full account is in the 10-24 report, §2a.
  - **The next iagent roll repairs the record.** Use the same roll form as rev 215 and 216 (the report has it). The gates are unchanged, and one more applies: **check `helm history doc-tools` (namespace `sandbox`) right before you roll.**
- doc-tools is at rev 54, which is 7f's.

## The report, and packets placed (not committed)

**The report** is `sessions/2026-10-24-report-to-architect-six-items-…`, with addenda 2a, 2b, 3a and 7.

**Packets:**
- cortex-ui `sessions/2026-10-24-packet-to-cortex-section-7-answered-…`: §7 answered, Superset struck, `extraction_defect` ruled in.
- openddil `sessions/2026-10-24-packet-to-openddil-send-one-fresh-event-by-monday-0900-ct-…`: the event is due Mon 14:00Z.
- doc-tools `sessions/2026-10-24-packet-to-7f-from-lane-01-your-rev-54-rolled-inside-iagent-216-…`.

## Next, in order

1. **Monday before 14:00Z: watch for OpenDDIL's event.**
   - Look for `POST /ingest/events` in the cortex-bff log.
   - Give Chris the case link: `/case/<event_id>?idp=openddil`.
   - If nothing has arrived by 14:00Z, tell the architect: Tuesday has no demo case.
2. **208, all on `lane/01-208` and then restacked into v1:**
   - the `review_task_id` fix, plus its seal;
   - `review_shape` and `account` on the status row;
   - `extraction_defect` as `{task_id, edits} | null`;
   - the four always-present fields made required;
   - a `RowEditCounts` model;
   - the `ingest-v1.md:279` correction;
   - **the verb health check** in `scripts/version_census.py`: print the live verb counts, fail on zero, and fail on a declared verb that is not registered (report §2b).
   - Then merge 208 and v1 to master, regenerate `docs/api/cortex-bff.openapi.json`, and give cortex the merge sha as its `PRODUCER_REF`.
3. **Later:**
   - response models for `/task_kinds`, `/cases/{case_id}`, `/reviews/{workflow_id}/batch` and `/notices/{notice_id}/provenance`;
   - the `table` enum on `/electric/shape`;
   - the v0.9.11 pin;
   - folding the training namespace into the chart;
   - re-running the #158 count after 7f's re-ingest;
   - the TDB2 compaction 400 (prime warns about it every run);
   - root credentials held as plain env.
4. **Cleanup:** remove the scratch worktrees `wm67` and `wc60`.
