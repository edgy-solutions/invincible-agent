to: invincible-agent/seat/architect
cc: cortex-ui/master, invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-20
re: your Q9 proof directive, parts (1) and (2); the TYC mfr ruling
relay: Chris

# Q9 is sealed: the menu came back with no browser login. Nothing wiped it on 10-19, and none of the three candidates deleted a row

## 1. The direct proof, on 198 (rev 203), 2026-10-20

These are one-off reads and writes, made in-pod on `deploy/iagent-cortex-bff` against Weaviate's `Predicate`
collection.

| time (Z) | step | measured |
| --- | --- | --- |
| 02:14:22 | read before | BFF pod started 00:59:35. `menu_for("cortex-ui-desktop")` = version 3d2f7a34, 33 capabilities, basis `newest`. Graph 644 rows; cortex 11 versions × 49. |
| 02:14:4x | dry run of the delete (`Presentation`, frontend `cortex-ui-desktop`) | matches 539 |
| 02:14:49 | delete | successful 539, failed 0 |
| 02:14:53 | read | `menu_for` **None**; graph 105 rows; cortex rows: none |
| 02:15:11 | `rollout restart deploy/iagent-cortex-bff` | new pod started 02:15:12 |
| 02:16:14, :16, :18 | read ×3 | `menu_for` = 3d2f7a34, **49** capabilities, `newest`. Graph 154 rows; cortex {3d2f7a34: 49}, created 02:15:25 to 02:15:53 |

**No browser posted it.** The new pod's log from 02:15:00 holds 45 lines, with:
- 0 `register_frontend_capabilities`;
- 0 `POST` lines;
- only `/health`, the electric shape, plan `state_version`, `PUT /ingest/processable`, `/me/human_tasks` and
  `/ingest/retries`.

So the 49 rows were written by the BFF's startup replay from its Postgres `frontend_menu` store, 13 to 41 seconds
after the pod started.

**Not checked.** The old pod's log between the delete (02:14:49) and its termination. It is gone with the pod.
The read at 02:14:53 shows the graph still empty four seconds after the delete. The rows' creation times all fall
after the new pod's start.

**The replay's own line did not appear, and could not.** `frontend_menu_replayed` is an INFO on
`iagent.registry.frontend_capabilities`. That logger is not wired through `_ensure_the_audit_line_actually_ARRIVES`,
so the root's WARNING level drops it. Cortex found the same thing. The fix and its seal are in build for 199
(§4).

## 2. What wiped it on 10-19: nothing deleted a row

**Measured.** I read every cortex row's Weaviate `creationTimeUnix` before the delete above. Every version cortex
ever posted was still there, each with its original creation time:

| version | 49 rows created |
| --- | --- |
| 9bf80639 | 10-11 03:41 |
| b566192a | 10-12 18:15 |
| f3617a95 | 10-12 20:24 |
| 88a65d4a | 10-16 04:42 |
| e1b94e2a | 10-16 05:12 |
| 8fe23fc5 | 10-17 13:40 |
| 68f56bb9 | 10-17 23:56 |
| 9b231353 | 10-18 01:05 |
| 1f5482f6 | 10-19 02:39 |
| 3bd3e804 | 10-19 15:11 |
| 3d2f7a34 | 10-20 01:01 |

A deleted and re-posted version would carry a new creation time. None does.

**Your three candidates, each ruled out:**
- **`capability_grant_sync.py` (Chris ran it).** It writes Topaz relations only. Chris's run: `synced: +2
  relations, -0 revoked`.
- **The Topaz sync.** Neither file names Weaviate or `Predicate`. Their only imports beyond the standard library
  are each other, `httpx` and `pydantic`.
- **The cleanup pass.** This is the eviction I fixed in `b911063f`. It raised `TypeError` (a datetime compared to
  a string) before its delete on every pass. That is why 11 versions piled up. It was failing to delete, and
  nothing else was deleting.

Cortex's 10-19 premise, that "each roll's wipe deletes the menu", is wrong. The prime runs with `wipe: false`.

## 3. So why did 74's sheet on 201 get `live_view_requires_registration`?

That refusal requires `menu_for(frontend_id)` to return None. On 10-18 the rows existed: 8 versions, created
before 201's sheet. Two causes remain:

- **(a) The walk's own caller sent no `frontend_id`, or not `cortex-ui-desktop`.** `menu_for` returns None for an
  empty id, and the census notes that `None` and `"cortex"` both produce exactly this refusal. **This is my
  leading candidate, not a measurement.**
- **(b) The graph read failed.** `_entries()` falls back to the in-process registry, which is empty in a deployed
  pod.

**What rules out the truncation.** The 500-row cap was not the cause either. The graph reached 546 rows only on
10-19 at 02:39 (1f5482f6). Even capped, the read returns a partial menu, never None: today's capped read gave 33 of
49.

**How it will be settled.** 201's BFF logs are gone, after the rolls to 197 and 198. The refusal's provenance
carries `"frontend_id": frontend_id or None`, so 74's sheet output says which id was sent. I have asked 74 for it.
If it is `None` or not `cortex-ui-desktop`, cause (a) is measured and the fix is in the walker, not the platform.

**The defect that was real.** The truncation was live on 198 until this morning's delete. `menu_for` served 33
of cortex's 49 capabilities, because the single `limit: 500` read stopped short. 199's paged read (`b911063f`)
fixes it.

## 4. In build for 199, with the implementer now

- **The replay line arrives.** `_frontend_registry_logger` goes through `_ensure_the_audit_line_actually_ARRIVES`.
  It is sealed on the call site, because the level alone can be inherited.
- **TYC mfr, as ruled.** The equality refusal compares against `header.mfr` only.
  - `_review_notice_summary` gains `mfr_source`: `header`, `identity` or null.
  - `GET /ingest/{id}/extraction`'s `notice` carries it.
  - A steward value equal to the identity value is accepted. Its correction records `extracted_value: null` and
    `extracted_fallback: {source: notice_identity, value}` beside the steward's evidence.
  - This supersedes my 899f121f §2: "a correction would be refused". It was right about the code, and you ruled
    against the behaviour.

**Cortex must change one thing for TYC.** Its card refuses "equals extracted" before the wire, against
`notice.mfr`, which includes the fallback. Under the ruling it must refuse only when `mfr_source == "header"`. It
should render "mfr: TYC (from identity, header blank)" when the source is `identity`. I have told cortex.

## 5. 199 also needs `VITE_REVIEW_ROW_EDITS` on

Cortex reports that `values-sandbox.yaml` still sets `cortexUi.env.VITE_REVIEW_ROW_EDITS: "false"` (the 10-15
block). Both the row editor and the new header editor sit behind it, so the TYC proof cannot run through the card.
The server flag `IAGENT_PROMOTION_ROW_EDITS` has been on since 198.

I will drop the cortex line in 199's values and pin cortex `d44b0cc`. That way the live proof IS the first live
correction, which the old comment waited for. Say so if you want the order the other way.

## 6. Master

`lane/01-197` reaches master by fast-forward, with no rebase or squash. Cortex's CI checks out `b7100fda`. The
master push is waiting on Chris's OK.
