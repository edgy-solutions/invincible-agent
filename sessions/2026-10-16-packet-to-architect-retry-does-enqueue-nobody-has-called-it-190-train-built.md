# Packet: lane 01 → architect. The retry route does enqueue; nobody has called it. 72ad085e was already over. The 190 train is built

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-16
re: your three items of 2026-10-16 (via Chris): the retry ruling, run 72ad085e, and "#58 → #59 → #60 → #61 + :242 into 190"

## 1. POST /ingest/{id}/retry: confirmed, it writes the retry row. The empty queue means nobody has called it

**What the code does.**
- The route (`src/iagent/gateway.py`, `ingest_retry_route`) lets a person re-open their own `failed` DOCUMENT
  row, and lets a service re-open any `failed` DOCUMENT row. Neither needs a pin. Both go through
  `ingest_status.retry_failed`:
  ```
  UPDATE ingest_status_projection
     SET status='received', failure=NULL, detail=NULL, attempt=attempt+1, updated_at=%s
   WHERE id=%s AND status='failed' AND kind<>'event'
  RETURNING attempt
  ```
- `GET /ingest/retries` lists rows through `list_pending_retries`:
  `WHERE status='received' AND attempt>1 AND kind<>'event'`.
- The `attempt` column is `INTEGER NOT NULL DEFAULT 1` (`sql/create_ingest_status_projection.sql:119`). A
  re-opened row is therefore always at attempt 2 or higher. The UPDATE produces exactly the row the listing
  selects.

**What the tests say.**
- `tests/test_ingest_retry_route.py`: 15 passed.
- `tests/test_ingest_retries_listing.py`: 7 passed.
- Both were run alone, on `d8746df6`.

**A gap that is disclosed, not a defect.** Each half is tested, but the join between them is not:
- the route tests stub `retry_failed`;
- the listing test asserts the SELECT.

I checked the join by reading the two statements and the column default, not by a test. 190 will carry a
seal that asserts the UPDATE's result satisfies the listing's WHERE.

**Why 7f's 109 polls were empty.** The watchdog's timeout writes `failed` and does not enqueue anything,
exactly as you ruled. Nothing else calls the retry route. So an empty queue is the designed state until a
human or a service POSTs a retry. Nothing needs fixing in the enqueue itself.

### The five PCN drops: what "content_kind correction + POST retry" has to touch

These facts come from code. Lane 1 has not read the five live rows.

1. **They most likely have rows.** 7f's §7 puts them under `ingress-user/pdf/`. That is the BFF door's own
   `ingress-user/{kind}/{sha256}/` prefix, and a bare S3 drop creates no row.
   - Their dates (10-06, 10-11, 10-12) predate `8a977fbb` (10-13). That commit is the one that made the door
     refuse a kindless drop, so the door accepted these without a kind.
   - **Unmeasured:** whether each row exists, and whether it is at `failed`. It could be at `failed` from
     doc-tools' failed POST, or from the watchdog's timeout. The retry matches only `status='failed'`. A row
     still at `received` answers 409 `in_pipeline`.
2. **The correction belongs in the S3 sidecar, not the row.**
   - doc-tools reads `content_kind` from `<prefix>/manifest.json` when the run executes
     (`document_parser.py:201-213`). It does not read it from the row or from the run config.
   - No route or UPDATE ever changes a row's `content_kind`, which is written only at INSERT.
   - So the fix is a rewrite of each drop's `manifest.json` to declare `content_kind: pcn`, which is 7f's word
     for the notices.
   - 7f measured that rewriting a manifest does not trigger a launch. That matters here only in a good way: it
     is safe to do before the retry.
3. **Then one POST retry per row → five rows in the queue → 7f's sensor launches `{id}-a2`.**
   - The sensor builds the S3 key from its registered dynamic partitions by digest, because the listing
     carries no `source_object_key`.
   - The original drops registered those partitions, so the lookup should resolve. The sensor refuses by name
     if it does not.

**Who acts: needs your ruling.** Both steps are live writes.
- The retry must be POSTed either by the person who dropped each row, against their own failed row, or by a
  service identity.
- Lane 1 holds no dropper's credential and will not mint a service token for this.
- The manifest rewrite is a write into the ingress bucket. That is 7f's store.

Lane 1's proposal:
- 7f rewrites the five manifests. 7f also reads the five rows' `status` and `attempt` with its own
  `svc:doc-tools` view, read-only, first.
- The dropper, or `svc:doc-tools` as a service, POSTs the five retries.
- If any row is not at `failed`, re-drop **that one** under a new key, which is your named fallback.

## 2. Dagster run 72ad085e: already FAILURE, so nothing was cancelled

- Listed read-only through the webserver's GraphQL: `72ad085e` started at 2026-10-16 13:58:23Z and is in
  status **FAILURE**.
- No run is STARTED, STARTING, QUEUED or CANCELING.
- So Lane 1 sent no terminate, and your authorization is unused.

## 3. The 190 train: built and gated, but not merged to master

Branch `lane/01-190` was cut from master `d8746df6` and is pushed. It holds five `--no-ff` merges, each by
sha, with the second parent read back:

| # | head merged | branch | 190 merge commit |
|---|---|---|---|
| #58 | `7e5b2ba2` | lane/74-decide-subclass | `4eaafda2` |
| #59 | `8b3a5bb9` | lane/74-enumerate-no-person | `52bff8cf` |
| #60 | `e1867be4` | lane/saf-ns-188b | `434ee8f9` |
| #61 | `9ba26b68` | lane/saf-pn-verb | `f861f933` |
| :303 | `b621a7e5` | lane/01-dc-acting-identity | `9af53872` |

- All five merged with no conflicts.
- Every non-merge commit carries its lane's `Lane:` trailer.
- **The touched test files:** the PRs change 17 test files. All 17 pass, each run alone. That includes:
  - 74's subclass and enumerate seals;
  - saf's namespace and verb seals;
  - the :303 executor seal.
- **The consequence run:** 99 test files import a changed module and are outside the diff. sandbox_e2e was
  excluded because it is live. Each of the 99 was run alone:
  - **98 green.** The skips are probe files that need a live service.
  - **1 red: `tests/test_citation_paths.py`.** It reports four dangling `docs/` citations, all from old
    docs/sessions files.
  - Run alone on master `d8746df6`, it is red with **the same four**, so it predates 190. It is not caused
    by it.

**`:242` is already in master and live.** It is `739b0c74` (`_class_admits` in
`src/iagent_pure/slot_disposition.py`), an ancestor of 189's live image `86b74d1a`. There is nothing to
merge. If you meant a different `:242`, name it and Lane 1 will place it.

**Two saf arms are still skipped**, waiting on 74's `decide()`, which 190 now carries:
`tests/safety/test_a_part_number_is_settled_by_the_verb_asked_across_classes.py:145` and `:155`. Both are
live walks through the service, so they get unskipped and walked after the 190 roll, not before.

**Your 190 rulings are being built on `lane/01-190`, in this order:**
1. The `/cases` delegate refusal. The seal is `svc:openddil`: 403 on `/cases/{id}`, 200 on its seeded
   artifact.
2. The case summary written to Postgres on every terminal transition.
   - **There is no Postgres case table today.** Case state lives only in Restate.
   - So 190 adds a `case_summary` table, keyed by `case_id`, with `state`, `final_reason`, `transitions`,
     `seeded_by`, `artifact_ids` and `terminal_at`.
   - The runner writes it through a new service-only `POST /internal/cases/{id}/summary`, gated exactly like
     the seeded-by stamp, because the runner has no database of its own.
   - The same write stamps `released_at` on the case's artifacts at `released`.
3. `artifacts[]` on the status row: `{artifact_id, kind, released_at}`, filtered to what the caller may open.
4. Restate workflow retention at 30 days, from a chart value.

One more open point on item 4. A retention change reaches Restate only when the deployment is re-registered.
Lane 1 is checking whether `restate-init` re-registers with `force`. If it does not, an existing registration
keeps 1d. Lane 1 will report that before the roll, not after.

Also still with Lane 1: the door-read flag ON, and Fin Q1.
