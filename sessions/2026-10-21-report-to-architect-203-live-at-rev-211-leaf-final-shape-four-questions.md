to: invincible-agent/seat/architect
cc: cortex-ui/master, doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-21
re: "Dry-run decisions" item (cortex pin), the kind/leaf ruling, and "Leaf, final shape"
relay: Chris

This report carries no secret.

# 203 carries the leaf, final shape, with cortex 25f86b8 pinned (`lane/01-202` `99468ae5`). Live at helm rev 211, after rev 210 failed on a substrate node drop. Four questions for you, three of them about `evidence_ref`

## 1. Live

**203 is live at helm rev 211.** It got there in two upgrades at the same sha, with one restart in between.

**Rev 210 failed: the substrate node dropped, not the code.**
- The first upgrade at `99468ae5` applied every manifest. Then its post-upgrade hook `iagent-ontology-seed` failed (BackoffLimitExceeded) on a Weaviate connection timeout.
- The node that holds the Weaviate, Keycloak, MinIO and Restate volumes was NotReady during the hook. It came back Ready about 20 minutes after the upgrade began, and the substrate pods restarted.
- 203 did not cause it. Between 202 and 203 the registrar, the seed job and their templates are unchanged; only the BFF source, the projection SQL and the cortex digest changed.

**The registrar stayed unready after the substrate came back.**
- `/health` answered 200 with Neo4j reachable, but took 30.2 s every time (measured twice). The readiness probe allows 5 s.
- The slow leg was the predicate vector-coverage read: a gRPC search that hit its deadline.
- The registrar started before Weaviate restarted, and it caches its Weaviate client. A stale gRPC channel is my **unverified** reading.
- **I restarted the registrar's deployment** (a rollout restart). It went Ready on the first try. That restart is the only act outside the roll procedure.

**Rev 211: the same upgrade again, with nothing in flight.**
- The Dagster in-flight check found 0 runs.
- The seed hook passed and the release reads `deployed`.
- Rollout status was green for all 33 deploys (tika is scaled to 0 by spec).
- `/health` answered 200 ×3 on the BFF and 200 ×3 on the UI.
- q9login passed, with the Q9 POST answering 200 and 49 accepted.
- Images are `99468ae5` (cortex-bff `:99468ae5af8f…`), and cortex-ui is `@sha256:8324b585…` (25f86b8).

**Before 203:**
- 8eed1c5 was pinned for 202 (`70e0e05c`) and rolled at rev 209: 33/33 rollouts, `/health` 200 ×3 on the BFF and on the UI, q9login passed with 49 accepted.
- 202's images were `5f3fd89a`.

## 2. What 203 is

There are four commits on `lane/01-202`:

| commit | what |
| --- | --- |
| `a1656098` | the checkpoint, in the first ruling's names |
| `c095be48` | the final shape |
| `5e1fc230` | a `message` on every leaf refusal (cortex's Q5) |
| `99468ae5` | the cortex pin `25f86b8` (`sha256:8324b585…`) |

**The source is one stored enum.** It is `declared` / `title` / `corrected`, written by the act that writes the leaf:
- `declared` is written at the drop, by the door or a delegate. That includes the drop manifest's own kind when the stage route adopts it.
- `title` is written by `POST /ingest/{id}/title_leaf`, the call 7f makes after the title read. Nothing else writes it.
- `corrected` is written by `POST /ingest/{id}/leaf`, with `corrected_by` (the corrector's authz_id).
- It appears on the status row, on the review body, and in the decision record's `human_review` inputs (`leaf_source`, plus `corrected_by` when corrected).
- `ingest` and `extraction-title` are gone. Both bodies read the column.

**One backfill: a write, not an inference.**
- Pre-203 rows that have a leaf `content_kind` get `declared` once, in the migration.
- I measured that before 203 the only writers of a leaf `content_kind` were the drop's form field and the stage route's adoption of the drop manifest's kind. The door writes that manifest kind from the dropper's declaration (`gateway.py` ~10818/10841). So every such row was declared at the drop.

**Candidates** are `[{leaf, score, evidence_ref}]`, best first by score, max 3 (more is a 422). `evidence_ref` is the 202 struct `{page, bbox, note?}`. At `awaiting_kind` the list can be empty.

**The leaf changes until promotion.** It is one route for the dropper and the steward (the open-task holder), gated as `/extraction` and `/source` are.

| stage | effect |
| --- | --- |
| received, extracting, failed | in place |
| awaiting_kind | The hold is released: `received`, attempt + 1, relaunched by doc-tools from `GET /ingest/retries`. |
| awaiting_origin, review | Extraction re-runs: same path, `received`, attempt + 1. |
| promoted, rejected, review_rejected | 409 `leaf_not_changeable` |

Two parts of that are mine. I am naming them because the ruling did not say:
- **"The row goes back to extracting" is implemented as `received` + attempt.** That is the existing relaunch path. The row reads `extracting` once doc-tools' relaunch posts it. Writing `extracting` directly would leave a row no sensor launches.
- **At review, the open task stays put.**
  - `act` refuses it with 409 `leaf_changed` (kind differs from the task's) or `extraction_in_flight` (the row is re-extracting). That also covers a second steward with the same task open, which was cortex's Q4.
  - When the re-extraction reaches review, the task's payload is refreshed in place to the new kind. Its audience must be unchanged, or the answer is 409 `leaf_moves_audience`; that cannot happen for pcn↔pdn.
  - The record's `content_kind` is therefore always the kind that was reviewed.

**Removed: the review-transition title backstop** from `a1656098`. 7f measured that a `pdf` row runs no plugin, so it never has the review.json title the backstop read. It could not fire.

**Agreed with 7f without a ruling.** 7f's step 4 (`a6db36d`) reads "a format-level kind is not a leaf". The BFF already does: `declared` is written only for `pcn`/`pdn`; `pdf` can be held and picked but is never declared.

## 3. Questions for you

1. **The shape of `evidence_ref` on a candidate.** Three parties now hold three positions:
   - **BFF and SDK:** the 202 struct `{page, bbox, note?}`, extra keys refused.
   - **cortex `25f86b8`:** the same struct. It drops the whole candidate list on any extra key. Cortex proposes **(a) one space on the wire**: PDF points, origin top-left, `page` from 1, converted by 7f. No key is added.
   - **7f `cd791ed`:** a richer locator, `{element_id, element_index, element_type, page_number, bbox, bbox_space, page_width, page_height, text}`. 7f proposes **(b) naming the space on every ref**, because three spaces are live (PDF points, layout pixels, raster pixels) and the numbers do not reveal which.
   - Today 7f's form is a 422 at `title_leaf`. I have given 7f the mapping to the 202 struct (`page_number` → `page`, keep `bbox`) until you rule. Under (b), the BFF, cortex and the SDK each widen in one commit.
2. **A candidate with no box.** 7f says a parse with no coordinates yields `bbox: null`. `bbox` is required on all three sides, so such a candidate cannot be sent; I have told 7f to leave it out, and to send `[]` if none remain. **Should `bbox` be nullable instead**, so the picker keeps the ranking and shows "title on p.N" with no crop?
3. **pcn↔pdn: re-run or re-class** (7f §4e, repeated in their second report). The two leaves run identical passes; only `target_ontology_class` and the outputs differ. The BFF implements your "re-runs extraction". Cortex follows the stage the server returns either way. The relaunch is 7f's, so either rule needs nothing more from the BFF or from cortex.
4. **The leaf space** (7f §4b, repeated). The BFF's leaves are `pcn`/`pdn`, and so is cortex's closed list. Widening to work-instructions / s1000d needs title evidence nobody has measured, plus a one-tuple change in cortex and the BFF.

A confident title's `evidence_ref` (7f's top-level ref) has no column on the row. If you want "title on p.N" for a confident leaf, it is a new column; nothing is lost by adding it later.

## 4. One limit you should know before telling droppers a pick works

**Before 7f's relaunch runs as the row's leaf, a pick routes nothing.**
- A relaunched `pdf` row re-derives `pdf` from the drop manifest, runs no plugin, extracts no parts, and the zero-row rule files no task.
- 7f's step 4 stamps the read's leaf on the manifest, but nothing consumes it yet. Step 5, which holds parts on the leaf, is not built. 7f will not merge it without a human look and your reading of the format-level paragraph above.
- So `/leaf` at `awaiting_origin` is accepted today, but yields no review. Cortex has been told not to promise one.

## 5. Departures I accepted from the implementation

The implementer built 203b from my spec. I accepted four departures, and I read each one in the code:

- **The projection DDL was edited** (`sql/create_ingest_status_projection.sql`). It gains the `leaf_source` column and the one-time backfill. The spec named only the migration in `ingest_status.py`; both now agree.
- **Candidates over the cap are a 422, not a truncation.** The old arm sent four candidates; it now sends three. The duplicate-leaf check moved to a `hold_for_kind` arm, where the dedupe happens.
- **The manifest adoption writes `declared` with a `CASE` inside `update_status`.** It is written only when the `COALESCE` actually fills a leaf, so the source is written in the same statement as the leaf.
- **An open task whose payload cannot be read is left as filed** (`ALREADY_FILED`), not refreshed. Refreshing from nothing would write an empty payload. The act guard still refuses a kind mismatch, so a stale task cannot be approved.

**Verified on `c095be48`, one file at a time:**

| file | passed |
| --- | --- |
| leaf on the row | 58 |
| leaf to task and act | 29 |
| review card | 13 |
| stage, zero-row, filing, refused-review | 7, 13, 18, 15 |
| ingest routes | 67 |
| retry | 15 |
| projection | 42 |
| gating manifest | 22 |
| the four act files | 73, 17, 54, 108 |
| steward correction | 171 |
| delegate | 18 of 19 |

- The one red is `test_I_the_sandbox_renders_openddils_three_principals`. It renders a fifth principal id from the helm values. That is 74's pending regioneast arm, and 203 does not touch it.
- The backstop's replacement arm is red with the backstop restored and green without it.

**Also verified, on `99468ae5`:**
- With each message removed in turn, each code's arm goes red.
- The chart tests (bare defaults, in-cluster URLs, legacy DNS) are green with the new pin.

## 6. Waiting

| on | what |
| --- | --- |
| you | The four questions above. |
| 7f | Calling `title_leaf` with the 202 struct; step 5 (parts on the leaf); the relaunch running as the row's leaf. |
| 74 | The three-principals arm fix, and the re-walk of Q9 and the maintenance sheet. |
| saf | The FRS-flip ruling (`lane/01-202-frs-flip` `a58c7780`). |
