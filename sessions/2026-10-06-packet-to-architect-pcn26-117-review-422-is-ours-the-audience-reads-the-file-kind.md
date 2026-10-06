to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: ia-01/lane/01, 2026-10-06 ~23:40Z
re: "7f's stage POST for PCN26-117 (run 82586878) got 404 ingest not found"

# The ids match and the row exists. The last hop is a 422 from OUR review branch, not a 404

## The ids: identical, so the one-id rule holds on both sides

- **doc-tools posted:** `ingest_id=sha256:b58ec2f6e0438479eea35715a060d9686a8e3efa49803202c15f18dde9f0745c`
  (doc-tools pod log, 23:16:02Z).
- **Our row:** `ingest_status_projection` has the same id: `kind=pdf`,
  `submitted_by=alice@example.com`, `status=review`. Read live inside cortex-bff.

## What the BFF actually answered (access log, timestamps UTC)

| time | request | answer |
|---|---|---|
| 23:14:52 | POST /ingest/sha256%3Ab58e.../stage (extracting) | **200** |
| 23:16:02 | POST /ingest/sha256%3Ab58e.../stage (review) | **422 `no_entitled_recipients`** |
| 23:20:07 | GET /ingest/sha256%3Ab58e... (x2) | 404 -- **no such route**; the route is `/ingest/{id}/status` |
| 23:20:07 | GET /ingest/sha256%3Ab58e.../stage (x2) | 405 |

The only 404s are someone's GETs on a route that does not exist. FastAPI answers an unknown
route with 404 `Not Found`. Our route's `ingest_not_found` was never raised.

## The stop: `POST /ingest/{id}/stage` with stage=review (`gateway.py:8993`)

    kind_reg = content_kinds.by_kind(row["kind"])     # row["kind"] == "pdf"
    domain   = kind_reg.domain if kind_reg is not None else None   # -> None
    audience = f"{promotion.KIND}:{domain}"           # -> "document_promotion:None"

The `kind` column on the row is the **file** kind (`pdf|xml|...`, constrained to
`ingest_status.KINDS`). The declared content kind (`pcn`) is written **only** to the S3 manifest
(`gateway.py:8600`) and is never stored on the row. So the review branch could never resolve the
domain for any document drop, which means bob's queue gets nothing.

**A second gap under the first:**
- **Measured:** in the live BFF, `by_kind("pcn")` is also None.
- **Why:** the sandbox's `CONTENT_KIND_OVERLAY_DIRS` holds only `maintenance-fault-event.yaml`.
  `pcn` is registered only in doc-tools' own `registry/content_kinds/pcn.yaml`, and that file
  forbids a `domain:` key: the domain lives in doc-tools' `content_kind_domains.json`.
- **So:** reading the right field still yields no domain on this fleet.

**A third, the state it leaves:**
- **Measured:** `update_status` runs **before** `register_task`, so the 422 left the row at
  `review` with **no** promotion task.
- **Read from the code, not fired:** a retry is refused as a 409 `backwards_move`, because review
  is not strictly later than review. PCN26-117 is wedged at review with an empty queue.

## Fix (ours; NOT built -- the order said report first)

1. **Carry the declared content kind on the row.** Add a column, or a field read from the
   manifest, and derive the audience from it, never from the file kind.
2. **Register `pcn` (with its domain) in the platform's content-kind overlay for the sandbox.**
   Or rule that the platform reads doc-tools' registry. That is a seam decision, not a one-liner.
3. **File the task first, then move the status.** That stops a refused task from leaving a
   wedged row: atomic or ordered, review only after `register_task` succeeds.

**My recommendation:** 1 and 3 as one change on `lane/01-review-audience` for roll #19.
2 needs your ruling on which registry is the platform's authority for `pcn`'s domain.
**I need from you:** that ruling, and whether to un-wedge PCN26-117's row. That would be a live
write, so a human runs it, or we re-drop a fresh notice after the fix, per your order.

## Not done

I built nothing, wrote nothing live, rolled nothing, and dropped no fresh notice.
