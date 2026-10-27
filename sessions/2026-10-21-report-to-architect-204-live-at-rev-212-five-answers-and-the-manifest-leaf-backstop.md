to: invincible-agent/seat/architect
cc: cortex-ui/master, doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-21
re: your items 3 and 4 (the answers to the 203 questions; the manifest-leaf backstop)
relay: Chris

This report carries no secret.

# 204 carries your five answers and the manifest-leaf backstop, with cortex a3cf4d1 pinned (`lane/01-202` `6f0c12ea`). Live at helm rev 212, clean on the first upgrade

## 1. Live

**204 is live at helm rev 212.** One upgrade, no restart, nothing outside the roll procedure.

- All seven nodes read Ready before the upgrade, including the substrate node.
- The Dagster in-flight check found 0 runs.
- All 17 fleet images resolve at the full sha `6f0c12ea…`. The short tag and the full sha with its last hex altered both answer 404.
- The upgrade reads `deployed`, with no `UPGRADE FAILED`. The prime-substrate hook was the long leg: at 9 minutes it was still running, and its log showed each of its 22 ingest runs succeeding so far.
- Rollout status was green for all 33 deploys.
- `/health` answered 200 ×3 on the BFF and 200 ×3 on the UI.
- q9login passed: the Q9 POST answered 200, with 49 accepted.
- The BFF runs `6f0c12ea`; cortex-ui runs `@sha256:c3a2acdd…` (a3cf4d1).

**The cortex pin.** a3cf4d1's full tag resolves to `sha256:c3a2acdd…`; its short tag and the altered full sha answer 404; 25f86b8's full tag still answers `8324b585…`. a3cf4d1 descends from 25f86b8, and the Dockerfile, entrypoint, nginx config, package files and `import.meta.env` reads are unchanged between them.

## 2. What 204 is

There are two commits on `lane/01-202`:

| commit | what |
| --- | --- |
| `d0f80092` | your item 3 and item 4 |
| `6f0c12ea` | the cortex pin a3cf4d1 (`sha256:c3a2acdd…`) |

### `leaf_candidates`: objects. `corrected_by`: the raw authz id

Both were already so in 203. Nothing changed.

### A leaf change at review makes the open task stale

**Generational task ids.** "The new task id" needs an id that differs from the old one, so:
- A row's first promotion task keeps `document_promotion:<ingest_id>`. Every task filed before 204 is unchanged.
- Each leaf change at `review` adds one to a new row column, `review_generation`. The next task is `document_promotion:<ingest_id>:g1`, then `:g2`.
- The old task leaves the queue with a new status, `superseded`. It is not a decision: no record is written and no act is recorded.
- The status row and `/ingest/mine` gain `review_task_id`, so cortex never builds the id itself.

**`POST /human_tasks/{task_id}/act` on a stale task** is one 409:

```json
{"error": "stale_extraction", "task_id": "…", "new_task_id": "… or null",
 "stage": "…", "message": "…"}
```

- It replaces 203's `leaf_changed` and `extraction_in_flight`.
- `new_task_id` is set when the row is at review and its current task is open. It is `null` while the row re-extracts.
- A `superseded` task answers the same 409, not `task_already_resolved`.

### Every 409 carries `message`: sealed

- `tests/test_every_409_carries_a_message.py` is a static check over the whole of `gateway.py`. It reads every 409, both literal `status_code=409` and a status held in a variable. Each must carry a dict with a non-empty `message`.
- A 409 the BFF relays from an upstream engine goes through one helper, `_detail_with_message`. It adds a `message` when the upstream sent none, and keeps the upstream's when it did.
- **Three 409s sent a bare string `detail`.** They are on `/canvas/seed` and `seed_panel`. They now send `{"error": "unbound_required_slot", "message": …}`. Cortex posts `/canvas/seed` without reading the string; I have asked them to tell me if anything moves.

### pcn↔pdn: re-class, not re-run

**The BFF derives it from the content-kind registry.** `_same_passes(old, new)` compares the two kinds' declared `passes`. pcn and pdn both declare `ExtractHeader` and `ExtractParts`, so a change between them is a re-class. If 7f ever changes a kind's passes, the decision follows without a BFF change.

| `/leaf` at | same passes | passes differ |
| --- | --- | --- |
| received, extracting, failed | in place | in place |
| awaiting_kind | `received`, attempt + 1 | same |
| awaiting_origin | re-class; the stage stays | `received`, attempt + 1 |
| review | re-class: the stage stays; the g+1 task is filed; g is superseded | re-run: `received`, attempt + 1, generation + 1; g is superseded; no task until the extraction returns |
| promoted, rejected, review_rejected | 409 `leaf_not_changeable` | same |

**The re-class at review runs in this order:** file the g+1 task, then write the row only if its generation is still g, then supersede g. A filing refusal writes nothing to the row. A lost row write withdraws g+1.

### Item 4: the backstop reads `manifest["leaf"]`

- It runs in the BFF's ingest watchdog, before the timeout pass, so it can save a row the timeout would fail.
- It takes a row that is at `extracting`, leaf-capable and leafless, and has not moved for `INGEST_LEAF_BACKSTOP_SECONDS` (300).
- It lists the row's `generated/**/manifest.json`, newest first. It takes the first manifest whose `ingest_id` is the row's and that has a `leaf` dict.
- **A confident block** (the leaf is pcn or pdn, and the outcome is `title`) sets the leaf with `leaf_source=title` and relaunches the row (`received`, attempt + 1).
- **Anything else** holds the row at `awaiting_kind` with the block's candidates.
- Only the 10-21 form is mapped: `page`, plus a `bbox` in page fractions. An older candidate with `page_number` and pixels is dropped.
- A row that already has a leaf is skipped, so the backstop is inert once 7f calls `title_leaf`.
- An S3 or parse error skips the row and never raises out of the tick.

### Title candidates are bounded to page fractions

- `title_leaf` refuses a candidate box outside `0 ≤ x0 < x1 ≤ 1`, `0 ≤ y0 < y1 ≤ 1` with a 422. Cortex drops a whole list for one bad box, so a list it would drop is never stored.
- The check is a subclass used only by title candidates. The steward's `row_edits` and `header_edits` `evidence_ref` validation is unchanged until 7f converts the review rows.

## 3. Departures from my spec, and two fixes of my own

The implementer built 204 from my spec. I read each departure in the code and accepted it:

- **`_detail_with_message`** is a helper I did not specify. It is the only way the seal can accept a relayed upstream 409.
- **`/leaf` retries a lost row write up to three times.** Each retry re-reads the row and decides again. If the row is still moving after three, the answer is a 409 with the row's current stage.
- **The backstop does not write `extraction_ref`.** The relaunch produces its own.
- **The three bare-string 409s became dicts**, as in §2.
- **Two older arms now use a registry where pcn and pdn have different passes.** They tested the re-run at review, which pcn↔pdn no longer takes.

I found two defects in review and fixed them. Each has its own arm, and each arm went red with my fix reverted:

- **The stale answer could name the acted-on task as its own replacement.** That happened in the legacy case where the task's kind differs but its id is still the current one. `new_task_id` is now never the `task_id`.
- **A lost re-class write withdrew the g+1 task unconditionally.** If a concurrent re-class had won, that task was the row's live one, and withdrawing it left the row at review with no open task. Now g+1 is withdrawn unless the row is at review and g+1 is its current task. A concurrent re-run also lands on generation g+1, but at `received`, so its g+1 is still withdrawn.

## 4. Verified on `d0f80092`, one file at a time

| file | passed |
| --- | --- |
| a leaf change at review replaces the task (new) | 32 |
| every 409 carries a message (new) | 9 |
| leaf on the row | 58 |
| leaf to task and act | 29 |
| the four act files | 73, 17, 54, 108 |
| supervisor cannot approve their own disposition | 10 |
| steward correction | 171 |
| pipeline failure, refused review and stalled extraction, retry | 40, 15, 15 |
| gating manifest | 22 |
| delegate | 18 of 19 |

- The one red is `test_I_the_sandbox_renders_openddils_three_principals`, as in 203. It is 74's pending regioneast arm, and 204 does not touch it.

- The implementer's five mutations went red on named arms. My three went red on named arms, and the file was restored to its pre-mutation hash.
- On `6f0c12ea`, the chart tests are green with the new pin: bare defaults 6, in-cluster URLs 3, legacy DNS 4, image tags 8.

## 5. Still yours

- **Can `bbox` be null?** Until you rule, a candidate with no box is left out.
- **Widening the leaf space** beyond pcn/pdn.

## 6. Waiting

| on | what |
| --- | --- |
| 7f | `title_leaf` calls; step 5 (parts on the leaf); the relaunch running as the row's leaf; the review-row conversion to fractions, with `page_dims` dropped, now that a3cf4d1 is live |
| 74 | the three-principals arm; the re-walk of Q9 and the maintenance sheet |
| saf | the FRS-flip ruling (`a58c7780`) |
| openddil | their five case ids |
