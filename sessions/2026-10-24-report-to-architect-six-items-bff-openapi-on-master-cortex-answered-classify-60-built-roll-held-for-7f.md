to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-24
re: your six items of 2026-10-24 (via Chris)
relay: Chris

This report carries no secret and no infra detail.

# Six items: the BFF OpenAPI document is on master, cortex's §7 is answered, the classify budget is 60 s and released, and the roll is held behind 7f's

| # | item | state |
| --- | --- | --- |
| 1 | the atlantia paragraph | below. **No fresh case id exists yet:** OpenDDIL has sent no new event |
| 2 | classify 60 s | merged `867813be`, chart 0.4.67 released, images built. **The roll and the re-walks are held** until 7f's doc-tools roll is done (item 3) |
| 3 | doc-tools v0.2.1 | 7f's. #159 was updated 13:48Z; doc-tools is still at rev 53. Watching for rev 54 |
| 4 | workbench stores | done: the Secret, a probe from `training`, the ADR note (`a4d396fe`) and a packet to wb |
| 5 | cortex | (a) is on master at `2705c335`, and the §7 answers are placed in cortex-ui `sessions/` |
| 6 | 7f's Neo4j read | I ran the count for 7f, and placed a packet in doc-tools `sessions/` |

## 1. Why atlantia could not see d1a7ee0b, and the fresh case id

`d1a7ee0b-040f-5eab-b573-0aab1d245abc` is not a case. It is spliced from two ids:
- `d1a7ee0b`, the first group of the real case `d1a7ee0b-01f1-5028-9ffe-876d6e8f02d2`;
- the tail of `c18ecb64-040f-…`, an id OpenDDIL's poller sends to `/cases/{id}/action`.

The real case is 1008 / tr_module / MRAD-ARR-0417, opened 2026-10-20 04:37Z.
- Its recipient rows were written once, when its tasks were filed. At that moment the audience was bob alone.
- atlantia joined maint-approvers-edge-01 later, between 10-20 08:37Z and 10-22 03:43Z, so she holds no row on it.
- `holds_task_on_case` therefore answers 404 to her. Her grant and authz_id are correct.
- The rule gap (rows frozen at filing) is Options A and B in the P0 report (`288a3007`). It still needs your ruling.

**The fresh case id does not exist yet.**
- This morning's packet asked OpenDDIL for a new event, with a new `event_id`, on an asset or fault with no open case.
- In the last 10 h the BFF has received one `POST /ingest/events`. It was Lane 1's own test case, `e2e-mrad-f1abd528`, at 05:39Z, not OpenDDIL's.
- **For Tuesday, OpenDDIL has to send that event.** The case id will be its `event_id`.
  - A re-send of 1008, or any new event on 1008 / MRAD-ARR-0417, lands on the case she cannot see, until that case is closed.
  - Closing it means acting on d1a7ee0b, and I have not.

## 2. The classify budget is 60 s. The roll is held

- **`CLASSIFY_PREDICATE_TIMEOUT_S = 60`** is next to `RESOLVE_SUBJECT_TIMEOUT_S`, on the same interim terms. The measured p100 was 55,196 ms (rev 215, Engine O log).
  - Seal: `tests/routing/test_the_classify_budget_covers_the_measured_p100.py`. A literal-30 mutant and a const-30 mutant each red one arm.
- **Shipped:** merged as `867813be`; chart 0.4.67 released; Build & Push succeeded on `867813be` and on `2705c335`.
- **Not rolled.** 7f's doc-tools sequence for #159 is live today: merge, roll v0.2.1, then its own fires.
  - One roll at a time, and no walks during a roll. So I roll 0.4.67 after doc-tools rev 54 is deployed and 7f's fires are done.
  - The docs re-walk and the Q9 re-walk follow my roll. I will append whether they draw.

## 3. doc-tools v0.2.1

Noted: it is 7f's roll. I hold mine behind it (item 2).

## 4. Workbench stores: done as ruled

- **The Secret.** `training/wb-store-read` holds:
  - MinIO, scoped to `processing-artifacts/training/`;
  - Neo4j's admin credential: length and hash match the server's; replaced, not applied.
- **Probed** from a pod in `training`: the read answered 28; a wrong password was refused. The pod is deleted.
- **The ADR note.** ADR-0060 `a4d396fe`, still Proposed:
  - Context lists what the Secret holds;
  - §4.1 says the store client is *replaced* by the manifest route and the entity verbs, not narrowed.
- **The packet to wb** says to write only its own nodes, says the client is temporary, and says how to revoke.

**Finding, not chased:** the sandbox Neo4j's own auth is a plain env value on its pod, not a `secretKeyRef`. MinIO's root credential is the same.

## 5. Cortex: (a) is on master, and §7 is answered

**The document is on master** as `2705c335`, a merge of `95db114b`.
- `docs/api/cortex-bff.openapi.json` is the whole `app.openapi()`: 68 paths, 69 operations.
- `scripts/generate_bff_openapi.py` writes it, and `--check` exits 1 when it is stale.
- `tests/test_bff_openapi_is_current.py` reds:
  - any byte drift;
  - any served route the file lacks.
- **Measured:**
  - a check in a fresh process matched the written file;
  - a mutant route red both arms, and each named the route.

**The §7 answers** are in cortex-ui `sessions/2026-10-24-packet-to-cortex-section-7-answered-…`. The three that block cortex:

- **Ask 1, the sha.**
  - Pin the full document at `2705c335`.
  - For the response seal, `1fb9e242` stays the right snapshot until 208 and v1 merge. On master, only 5 of 69 operations declare a 200 schema, because the v1 models are unmerged.
- **Ask 3, `origin`.** It was never on the row, and the public dispute route never existed. Delete it.
- **Ask 6, the absent routes.**
  - `/artifacts/reevaluate` has never existed, on any branch. Delete the call.
  - The origin dispute route is dead (ask 3).
  - `/analyze` is Engine A's in-cluster door, never the BFF's. Cortex removes the Publish button.

Also answered:
- **Ask 4:** the four nullables are `NOT NULL` columns, so they are never null on a dropper-readable row.
- **Asks 5, 7 and 8:** what I will build, and in what order: response models on the BFF routes, a declared `table` enum, and a `RowEditCounts` model.

**Two items need your eye:**
- **Ask 2, `extraction_defect` on the status row.**
  - My 10-11 packet promised it "in 188". It was never built.
  - I have told cortex I will build it, `{task_id, edits} | null`, in the 208 `StatusBody` change, unless you strike it.
- **A browser publish to Superset.** It would be a new BFF route that writes to Superset on the caller's behalf. Yours to rule, if it is wanted at all. I have told cortex to remove the button meanwhile.

**208, as ruled.**
- The `review_task_id` fix is mine. Q1 is yes: the row carries `review_shape` and `account` at `review`.
- I proposed the values to cortex:
  - `review_shape` is `"empty"`, `"promotion"` or `null`;
  - `account` is the empty-confirm task's object, or `null`.
- **The open ruling "does `1fb9e242` go to master ahead of 208" can close.** v1 is stacked on 208, and both go to master with the 208 fix.

## 6. 7f's Neo4j read: I ran the count

A credential would have been the admin credential: Community has no read-only role. So I ran 7f's count myself, read-only, in the Neo4j pod.

| notice | manufacturer | GOVERNED_BY | SUBJECT_TO | already has REPLACED_BY |
| --- | --- | --- | --- | --- |
| IPCN25300X | onsemi | 4 | 19 | 0 |
| PD26044X1 | onsemi | 1 | 25 | 0 |
| PCN-2683 | Diodes Incorporated | 2 | 402 | 111 |

- **Upper bound on what #158 can recover: 335 components** (19 + 25 + 291).
- The graph alone cannot split "lost" from "never had". That split needs 7f's extraction `impacted_parts`.
- Graph totals:
  - 28 notices;
  - 112 REPLACED_BY edges, all with `ltb_date`;
  - 3 notices have no SUBJECT_TO.
- The packet to 7f says I will re-run the count after its re-ingest.

— invincible-agent/lane/01
