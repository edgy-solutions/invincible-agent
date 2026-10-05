# Packet: the four-item dispatch. Three shipped, and two rulings gate them going live

to: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-30-report-74-three-shipped-one-unmeasured-and-promotion-waits-on-a-store.md`

No store writes, no row inserted, no turn fired, nothing live. The three branches are pushed, all
from `3c9374a6`, and they merge onto it together with no conflict.

- `lane/74-canvas-export` `47fa6e1b`: packageExport takes a canvas. The alpha canvas
  reproduces the 09-06 document. Mutation 18/18.
- `lane/74-promotion` `f5e15a3b`: the `document_promotion` verbs on `/human_tasks/{id}/act`.
  Fail-closed, and the record is written first. Mutation 17/17.
- `lane/74-envelope-label` `0c957741`: `user-drop` becomes the fifth rung here, plus the pure
  label. Mutation 10/10.

## Needs a ruling

1. **Where the promotion fact lives (ADR-0041 Open §1).** `_promotion_store()` returns None, so
   the act refuses with 503 and the task stays pending. That holds until the fact has a home.
   The sweep's store is the same question.
2. **How an assertion carries `ingest_id`.**
   - Neither provenance block has the field: not this repo's, and not the SDK's `b68926a`.
     Both carry `ingest_run` and an optional `derived_from`.
   - The options are a new block field, or `derived_from` holding it.
   - Until this is ruled, the label reads it BESIDE the block, in one place
     (`envelope_label._ingest_id_of`). Rejection's keyed sweep has no key to sweep on.

## Findings, not asks

3. **The label has zero producers.** No production caller of `make_provenance` or
   `product_writer` exists. No reader of `obtained_via` exists outside provenance.py in src/,
   agent_fleet/ or cortex-ui/src. So the label is not on the live envelope, and wiring it needs
   a retrieval path that returns a block per row.
4. **SDK tuple agreement is armed.** The arm skips until this repo's SDK pin reaches
   `b68926a`, then goes live.
5. **Item-1 limits:**
   - The bff hop (canvas id → answers) is unbuilt.
   - A canvas export overwrites the program export's filenames.
   - A no-canvas call still exports the whole program.
   - No live fire.
   - Lane 1's item-5 report does not exist.
   - The one red in tests/cost is the pre-existing METHOD_FIELDS cause, and this branch
     touches neither failing file.
6. **HAZ-1003 is unmeasured, not failed.** Lane 1's run exited 2 without `HITL_POSTGRES_DSN`.
   - The credential is readable under the standing order.
   - The script fires a real turn that writes a real task, so I left the run with Lane 1.
   - **Who fires it is the open question.**
7. **No task-registration door exists.** No `document_promotion` task row exists anywhere, and
   none was made.
