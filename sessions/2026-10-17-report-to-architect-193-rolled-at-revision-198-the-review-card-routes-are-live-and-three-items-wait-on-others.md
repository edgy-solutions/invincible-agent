# Report: 193 rolled at revision 198; the review-card routes are live; three items wait on others

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, invincible-agent/lane/74, cortex-ui/master
from: invincible-agent/lane/01 (worktree `ia193`, branch `lane/01-193`), 2026-10-17

re: your 193 list (items 1 to 5) and the Day 2 addendum.

## The roll

| | |
|---|---|
| master | `148931dd` → `31d0590e8e60186757550770ff702284febae294` (fast-forward) |
| image | "Build & Push Container Images" run 39006373117 succeeded. GHCR answers 200 for the full tag; a fake sha answers 404 and the previous tag `b89d4c95` answers 200 |
| helm | revision 198, chart `invincible-agent-0.4.53`, `upgrade-sandbox.sh --set global.imageTag=<full sha>`, exit 0 |
| Dagster before the roll | 0 runs QUEUED, NOT_STARTED, STARTING, STARTED or CANCELING, listed twice (once while the image built, once immediately before `helm upgrade`) |
| fleet after | all 19 iagent deployments run `31d0590e…`; cortex-ui runs digest `cc2ad9cc…`; every deployment is ready except tika, which is scaled to 0 |
| cortex-bff | `/health` 200 three times; the live `openapi.json` carries `GET /ingest/{ingest_id}/extraction` and `GET /ingest/{ingest_id}/source` |

About 20 minutes after the upgrade, the chart's `engine-reregister` post-upgrade hook did a
rolling restart of every registering engine (`restartedAt`, written through the Kubernetes API).
That is the hook doing its job, not a second roll. All of them rolled out cleanly.

Pre-roll gate: the 75 test files that consume what 193 changed, run one at a time. 73 are green. Two are red, and both fail identically, on the
same arm, on a clean `148931dd` checkout, so they predate 193. Neither is in
`docs/plans/suite-signal-session.md`:

- `tests/routing/test_no_legacy_dns_references.py`: a legacy cluster-DNS literal at
  `tests/test_networkpolicy_flows_survive.py:44` (added by `f4c01b45`, 10-10).
- `tests/safety/test_the_acceptance_row_names_its_requester.py`: the case ends in
  `KeyError: 'CASE_RUNNER_CLIENT_ID'` (read by `agent_fleet/utils/service_identity.py:112`).
  The test does not supply the env var.

I did not fix either one. Both belong to other lanes' areas, so this is a report, not a change.

## 193 item by item

1. **MRAD re-ingest: not done, blocked on 7f.** No row is written. 7f's prediction
   (MAINTENANCE_INSTANCES 112, the union over all ten drops) settles 10 rows, not 6. The retry needs
   the xml retry sensor my packet asked 7f for, and 7f's report did not address it. Writing
   `failed:reingest_required` and then the retry rows needs a svc token, and I will ask Chris for
   that form before minting anything. No run keys exist to report yet.
2. **Task payload and the two routes: live at 198** (`71cdc40b`).
   - A newly filed `document_promotion` task carries `mfr`, `notice_date`, `part_count` and
     `attempt`, alongside `ingest_id`, `notice_id`, `content_kind` and `dropped_by`. Its title is
     the notice id, never the sha.
   - Tasks filed before 198 keep their old payload; `/extraction` serves those.
   - `GET /ingest/{id}/extraction` returns the rows, each with `evidence_ref {page, bbox, bboxes,
     page_dims, units}` or `null`. It also returns `rows_without_evidence`, which is 7f's
     corpus-gate number.
   - `GET /ingest/{id}/source` streams the dropped bytes.
   - Both routes allow the dropper or a holder of the OPEN task, and answer 403 `not_entitled`
     otherwise, decided before any store read.
   - Every decision is audited on `iagent.audit.ingest_access`.
3. **Cortex pin: `8fe23fc` is in** (`91100f28`, digest `cc2ad9cc…`). Cortex now offers `8066347`,
   which carries the xml lift and `/ingest/mine` paging. That is a pin for a later roll, if you want
   it. **fa231498 / 0096a523 are not retried.** They are alice's drops (PCN23-002.pdf twice), and a
   retry must be made as alice. That needs Chris.
4. **The e2e walk: written, not run** (`tests/e2e/walk_document_promotion.py`, `31d0590e`).
   - Steps: drop as alice through the door, watch to review, then bob reads the task, the eight
     payload keys, the title, the extraction, every row's evidence and the source sha. Bob
     promotes and the origin is recorded. Alice then reads `promoted`, and bob's source read is
     403.
   - It prints PASS/FAIL per step, and SKIP when an earlier step failed.
   - It needs two things from Chris: approval to mint persona tokens from env credentials, and
     local copies of the TI and IDT corpus PDFs, which exist only in the sandbox store.
5. **gov `e5fb8319`** was already on master through `ac9c5a3c` (10-07), so there was nothing to
   merge. **fin Q1**: the packet is placed in fin's `sessions/`; Q1 is not on `lane/fin`. **The 193
   roll**: done, see above.

## Day 2 addendum

1. **The universalReferent pool leg: waits on 7f's flag sync, as you ordered.** The leg is in
   engine-o (`_universal_referent_iris`, `_docs_pool_accepts`). Today the Jena read it relies on is
   refused for a service identity, so it degrades to zero rows. The seal, with the ordinary-cost-ask
   control written into the test, comes with the leg.
2. **The cosine probe: taken once,** in
   `docs/measurements/2026-10-17-mesh-explain-cosine-probe-the-held-number.md` (`71a98495`).
   - `mesh:DocPage` ranks 86, 16, 22 and 146 of 24,933 stored vectors for the four docs-walk
     questions, never in the top 5.
   - The DOCS-domain subset is empty.
   - Vector similarity alone will not bring DocPage into the pool. That is the hold's answer, and
     it supports item 1's route.
3. **`test_citation_paths.py`: green** (`f63f3b94`, 15 passed alone). The four dead links were
   **not** the four your addendum named. Those four are already in `PHANTOM_CITATIONS`. The real
   four:
   - two citations into `iagent-mesh-sdk` and `doc-tools`, which now name their repo;
   - one abbreviated file name, spelled out;
   - one measurement written on 74's `lane/74-acceptance-and-docs-subject` (`cea00aad`, 09-29)
     and never merged. It is allowlisted, the seal reports it PENDING, and it reds by itself after
     30 days, around 10-29, unless 74 merges or retires that branch.
4. **The "how do I add an engine" walk: not run.** It walks the leg from item 1, and nothing of
   item 1 is rolled. Per your order, no roll of the docs leg comes before the OpenDDIL case renders.

## Open with others

| what | who |
|---|---|
| xml retry sensor, then the MRAD re-ingest | 7f, then Lane 1 |
| fa231498 / 0096a523 retried as alice; persona-token approval and the PDFs for the walk; the svc token form for MRAD | Chris |
| `lane/74-acceptance-and-docs-subject`: merge or retire before ~10-29 | 74 |
| the two pre-existing reds above | their owning lanes; triage is the architect's call |
| Day 2: `/answers` paging, the borduria login and atlantia grant check, the broker checklist packet | Lane 1, next |
