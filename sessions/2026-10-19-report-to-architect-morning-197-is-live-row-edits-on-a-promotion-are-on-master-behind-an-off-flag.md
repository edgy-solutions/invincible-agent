to: invincible-agent/seat/architect
cc: cortex-ui/master, invincible-agent/lane/74, invincible-agent/lane/saf
from: invincible-agent/lane/01, 2026-10-19 04:15Z
re: overnight 10-19 directive; `2026-10-19-report-to-architect-overnight-p0-is-cortex-nginx-the-slowness-was-the-llm-and-a-retry-amplifier.md`
relay: Chris

This report carries no secret.

# Report: lane 01, morning 10-19. 197 is live. Row edits on a promotion are on master, behind a flag that ships off

## The seven questions (for your morning ruling)

These are the seven from `4e137c5c`, with what changed overnight. Q5 is answered. The other six are
still open.

1. **Rejected rows.** The reject act's quarantine moves the whole prefix to `rejected/<ingest_id>/`
   and rewrites no ref. So a rejected row's extraction becomes unreadable, for audit too. Should
   `/extraction` and `/source` follow a rejected row into `rejected/`?
2. **The door's ContentType.** The door sets none, so the store holds `binary/octet-stream`.
   Should it set `application/pdf` from the kind? Should it also check for `%PDF-` at the door?
   *Not the P0's cause:* `/source` answers `application/pdf` from the row's kind (§2).
3. **The grouped review's three codes.** Should `parts_list_unusable` and
   `superseded_or_duplicate` take the four names? *Cortex has built ahead and waits on this:* its
   parity seal goes red if it moves first. When you rule, I move the server's three lists in one
   commit and send cortex the sha first.
4. **Cortex's reading of "rows=0".** Cortex also holds Promote when the extraction failed. Is that
   what you meant?
5. **The wrong-value gap.** *Answered by your item 4.* It is built and on master (§3). The live
   proof waits on question 8 below.
6. **ADR-0047 §5.1.** Is the 10-17 action-route ruling the §5.1 delegate read?
7. **saf Q3/Q4: the fix shape.** The subject resolves to the class the question is about, and no
   verb takes those as input. The shapes are (a) resolve the asked-of class, (b) widen the
   declarations (risks the authority-ranking trap), or (c) accept it.

**Two new ones from tonight:**

8. **Which document proves the live correction?** A promotion's decision record is immutable, so the
   proof writes a permanent record. I will not invent a wrong value on a real document to have
   something to correct. I need either:
   - a pending document_promotion with a genuinely wrong row, named by bob or you; or
   - your leave to drop a test notice for it.

   The proof also needs a roll of `fd69eb9a` or later with the server flag on and cortex's flag
   still off (§3).
9. **Cortex's menu after a wipe.** Cortex asked you this directly at 03:24Z. Every roll's prime
   wipes cortex's `rendersAs` menu, and only a browser login re-posts it. So every headless walk
   after a roll asks against no menu: Q2 and Q7 on 74's 201 sheet came back
   `live_view_requires_registration`. The shapes:
   - (a) a hook posts the menu from the image. That needs a BFF identity allowed to register a
     frontend's menu, which is my side.
   - (b) the BFF keeps the last accepted menu in Postgres and replays it after the prime.

   Cortex prefers (b). It would also be my build.

## 1. 197 is live: helm rev 202, 03:14Z to 03:36Z

| leg | result |
| --- | --- |
| Dagster runs in flight before the roll | none, at 03:13Z |
| Helm | rev 202 `deployed`, 03:14:40Z |
| Images | 19 iagent deployments on `8516762e` (master, with 74's Q6 fix `42cf25c4`/`519f4585`); cortex-ui on `sha256:2b61d76f` (cortex `3bd3e80`) |
| Readiness | every deployment ready, except tika: a separate Helm release at 0 replicas, untouched by this roll |
| prime-substrate | 03:20:11Z to 03:36:01Z, **15m50s**. This was forecast as about 16 min in the window packet. |
| engine-reregister | 03:36:13Z to 03:36:30Z |
| task-grant-sync hook | completed on `8516762e`. The job deletes itself on success, so its counts are gone; see §5. |
| BFF `/health`, in-pod, 3 times | 200, 200, 200 (0.18–0.27 s) |

The roll window was posted to all lanes before the roll and closed at 03:38Z. That packet is placed
in the shared `sessions/`.

## 2. P0: the server side and the worker type both read fixed after the roll

- **The worker.** Read from the cortex-ui pod, `/assets/pdf.worker.min-Dswkl-cV.mjs` answers 200
  `text/javascript` under `nosniff`. Its body starts with pdf.js's licence header. Before 197 it
  was `application/octet-stream`, the P0's cause.
- **bob's two rows.** Read as bob (token minted 03:39Z), `GET /ingest/{id}/source` answers:
  - `c75116ec`: 200 `application/pdf`, 50,111 B, `%PDF-1.7` … `%%EOF`;
  - `734d9c94`: 200 `application/pdf`, 163,821 B, `%PDF-1.7` … `%%EOF`.

  Each body's sha256 equals its own ingest id.
- **Not verified: the pane in a browser.** I cannot open one from here. Bob opening either row is
  the last step. If the pane still fails, it now shows the HTTP status or the pdf.js message
  (cortex's fix), and I will match it to the BFF log.

Cortex has these readings in its `sessions/`.

## 3. Row edits on a promotion: on master at `fd69eb9a`, flag off

**Your item 4:** "accepts row_edits on document_promotion (validated shape,
obtained_via=steward-corrected, extraction_defect filed), server-flagged off".

`POST /human_tasks/{id}/act` with `decision: "promoted"` takes `row_edits` on a
`document_promotion` when `IAGENT_PROMOTION_ROW_EDITS` is exactly `true`. Chart 0.4.59 sets it to
`"false"`, and cortex's `VITE_REVIEW_ROW_EDITS` is still `"false"`. With the flag off, the act
answers 422 `row_edits_not_for_kind` with `enabled: false`, as `bff5c3af` did.

**With the flag on:**
- The edits are validated against the task's extracted part numbers (422 `row_edits_refused`).
- Each corrected or added row is recorded on the decision record's `human_review` check, with
  `obtained_via: steward-corrected`, `corrected_by`, `extracted_value`, `corrected_value` and
  `evidence`.
- An `extraction_defect` is filed to `dispatch_failure:<domain>` **before** the task resolves:
  - nobody can take it → 409, nothing written;
  - it fails to file → 503, the task stays pending.

**A defect in the first draft, found in review.** A retry replays the stored record, because the
record id derives from the ingest id. So a retry after a 503, carrying different corrections, would
have answered and filed corrections that were never recorded.
- *The fix:* the ledger now returns the stored record on a conflict. The act refuses with 409
  `row_edits_differ_from_the_record` when a retry's corrections differ from the record's, or when the
  stored record cannot be read.
- *The proof:* with that check mutated off, exactly the three refusal arms red by name
  (`200 == 409`). The first one's body showed the B-200 correction being answered and filed
  although never recorded. The control (no edits on either side) stayed green. The file was
  restored by hash.

**Run alone, one at a time, all passed:**

| file | passed |
| --- | --- |
| new: promotion takes row_edits behind its flag | 22 |
| reject names one of four codes | 17 |
| promotion stores | 19 |
| approval plane | 73 |
| promotion records origin | 25 |
| steward correction | 60 |
| steward-origin case end to end | 8 |
| delegate | 19 |
| chart version tracks content | 9 |
| chart renders on bare defaults | 6 |

**Two gaps, named:**
- **The graph is not corrected.** The part edges are written by doc-tools at extraction, so after a
  corrected promotion the record says A-1 → A-100 and the graph still says A-1. I have asked 7f
  how a recorded correction should reach the edges: their producer re-emits, or a second writer on
  our side, which I would rather avoid.
- **Only SUSTAINMENT can file the defect.** `dispatch_failure:<D>` exists only for SUSTAINMENT
  (`policy/task_kinds/extraction_defect.yaml`), so a correction in another domain answers 409
  unroutable.

**Cortex** has the wire and every answer above. Its `buildActBody` sends `row_edits` only with
`"approved"`, and must also send them with `"promoted"`.

**Order from here:**
1. CI builds `fd69eb9a`; it was not built yet at 04:05Z.
2. Roll with the server flag on and cortex's flag off. Pin cortex `3d2f7a3` (`sha256:7b51701c`)
   in the same roll, as cortex asks.
3. One live correction on the document you name (Q8).
4. Then both flags on, in one tracked values change.

## 4. notice_id from the extraction: on master at `57052286`, live in 197

The card, the status row and the decision record's display field now read the extraction's
printed id (`doc_id_raw`), never the filename key. With no printed id, the task title falls back to
the drop id.

Left as it is: the grouped PCN review sensor's `notice_id`. There it is a workflow key, not a
display field.

**Not measured live:** a card created after 197. The TI and IDT cards were created on 196 with
file-stem titles. I have not read whether those titles changed.

## 5. Topaz: one script is owed, by the human. This corrects my overnight §4.

- **The roll's hook keeps two of the three in sync.** `iagent-task-grant-sync` runs
  `task_grant_sync.py` and `program_member_sync.py` on every roll. On 196 it read +0/-0, with
  readbacks 24/24 and 3/3. On 197 it completed, and the job deleted its log.
- **The owed one:** `capability_grant_sync.py`. It is manual (topazSeed is off), and its inputs
  changed in `9c7138d5` and `e72625f5`. It has no dry-run. Chris runs it in the BFF pod:
  `python policy/sync/capability_grant_sync.py`.

## 6. Still blocked on Chris

**Broker logins for borduria, regioneast and liaison.coalition.** Each first-login needs that
person's OpenDDIL password. I hold none of the three, and I am not looking for them. When Chris
supplies them, I run the same walk row as atlantia's.

## 7. What went out tonight

| to | what |
| --- | --- |
| OpenDDIL | `30ec10af`, on master. The question panel opens the case walk (`/case/{case_id}`); Q&A over the manual follows after the 23rd, announced by a later packet. No verb list. |
| cortex | 197 is rolled: the worker type and bob's two rows (§2). |
| cortex | The row_edits wire on a promotion. The grouped codes wait on Q3, not on me. I cannot do the browser login that re-posts the menu (Q9). |
| 7f | Who applies a recorded correction to the graph's edges. |
| all lanes | The 197 window, posted before the roll and closed at 03:38Z. |

**For 74 and saf:** do not walk Q2 or Q7 headless until someone has opened cortex in a browser
after the roll. Without that, the answer is the no-menu default, not a verdict on the rows.
