# To the architect, via Chris: 208 is built on `lane/01-208` at `d5061ffb` and pushed. One ruling is asked: where hand-entered parts land.

from: invincible-agent/lane/01 · 2026-10-23 · answers "Build for 208" (cc 7f, cortex)

## Built as ruled

- **The task.** A zero-row extraction on a notice (content_kind `pcn` or `pdn`) files
  `document_empty_confirm` to `document_promotion:<DOMAIN>`, with `review_shape: "empty"`.
  - The payload carries the source pane (`/ingest/<id>/source`) and the extraction's own account.
    `why` is `no_table`, `no_parts_column`, `zero_rows`, or `unknown`, derived from review.json's
    stats; no figure is invented.
  - The row waits at `review`.
- **`confirmed_no_parts`** ends the row at a new terminal stage, `no_parts`, with detail
  "no parts (confirmed by <who>)". It is not `failed`, and it never appears in `/ingest/retries`.
- **`has_parts`** requires a page.
  - It files `extraction_defect` with that page to `dispatch_failure:<DOMAIN>`.
  - It relaunches the row with `force_text_fallback = TRUE`, at attempt + 1, with
    `reason: text_fallback` on `/ingest/retries`.
  - A second zero files a new task with `add_missed_part: true`.
- **The doors.** There are two doors and one writer:
  - the task act route;
  - `POST /ingest/{id}/empty`, where the dropper confirms their own.
- **The manifest.** The gating manifest declares the new route as `gated`.
- **No change** to the SDK, helm, or values.
- **Unchanged:** every other kind keeps today's `failed:extraction_empty` and 422.

## Tests, run one file at a time

| file | result |
|---|---|
| `test_a_zero_row_notice_is_asked_about_not_failed` | 19 passed |
| `test_an_empty_notice_is_confirmed_or_sent_back_by_a_steward` | 18 passed |
| `test_a_zero_row_extraction_never_files_a_promotion` | 13 passed |
| `test_ingest_status_projection` | 42 passed |
| `test_endpoint_gating_manifest` | 22 passed |

- In `test_a_zero_row_extraction_never_files_a_promotion`, five arms that asserted a leaf row
  goes `failed` now use `pdf` rows, which still do.
- The manifest seal was red until I declared `POST /ingest/{ingest_id}/empty`. That was caught
  before the commit.

One red I did not cause:
`test_the_status_is_the_decision.py::test_THE_DECISION_COLUMN_WAS_ALWAYS_RIGHT_and_that_bounded_the_damage`
fails on this branch. It reads `human_tasks.mark_task_resolved`'s source, and both that test and
`human_tasks.py` are byte-identical to `lane/01-207`. I have not run it on 207 itself.

## Three things I decided that you may want to overrule

1. **A steward on `/ingest/{id}/empty` gets 403.** That door shares `/leaf`'s gate, which admits a
   steward only through an open *promotion* task. Stewards answer through the act route instead,
   and the dropper through either. Cortex is told to pick the door by where the card opened.
2. **`extraction_defect` is filed by the BFF's own task filer.** The workflow's filer lives in
   restate_analyst and cannot be reached from the BFF.
3. **The second round's `has_parts` is 409 `add_missed_part_not_built`.** The task does return
   with "add a missed part" open, as ruled, but entry is refused. That leads to the question below.

## The ruling asked

**Where do hand-entered parts land?**

The candidates I can see:
- (a) as part rows in the run's extraction artefact, so the existing promotion task reviews them
  like extracted rows, carrying `source: steward`;
- (b) straight into the promoted store with the steward as the evidence, with no promotion step.

(a) keeps one review path. (b) is shorter, but it is a write the content gate has never seen. I
will build whichever you rule.

## On the roll

- **208's BFF must roll with, or after, cortex's empty card.** Without the card, a zero-row
  notice turns from a visible `failed` with Retry into a task nobody can see. I have asked cortex
  what today's build does with an unknown `review_shape`.
- **7f's consumer can come later.** Until 7f reads `force_text_fallback`, `has_parts` relaunches
  the same passes. They will most likely give a second zero, and so the add-missed-part task.
- **208 is not in Monday's 207 set.** Say if you want it there.

Packets placed, uncommitted:
- `doc-tools/sessions/2026-10-23-packet-from-lane-01-208-a-zero-row-notice-is-asked-about-and-retries-can-force-the-text-route.md`
- `cortex-ui/sessions/2026-10-23-packet-from-lane-01-208-the-empty-confirm-card-and-its-two-doors.md`

— invincible-agent/lane/01
