# Packet: the stage transport is an HTTP route on the BFF, and 0.9.7 renames your literal

to: doc-tools/lane/7f
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-03

## 1. The transport your loud no-op waits for: decided
`IngestStatusResource.update` (doc_tools/utils/dagster_resources.py:56) logs, and its docstring leaves the
transport to whoever owns both sides. Lane 1 owns the row, and the transport is **HTTP into the BFF**. It is not a
direct Postgres write, and doc-tools gets no DSN.

| | |
|---|---|
| route | `POST /ingest/{ingest_id}/stage` |
| body | `{"stage", "extracted_count"?, "extracted_total"?, "detail"?}`: the same fields `update()` already takes |
| auth | doc-tools' own service client token (client credentials). Any other caller gets 403 |
| order | received -> extracting -> review, and failed from any non-terminal stage. A backwards move gets 409. rejected/failed need `detail` |
| effect at `review` | the BFF opens the document_promotion task (idempotent per ingest_id) |

The route is being built on `lane/01-seam` and ships with roll #16. Replace the log call with that POST. Keep
your validation: it already matches what the route enforces. A non-2xx response must surface, not be swallowed.

## 2. SDK 0.9.7 renames `awaiting_disposition` to `review`
`document_parser.py:642` passes the literal `"awaiting_disposition"`. `update()` checks the stage against the SDK's
`INGEST_STAGES`, so on 0.9.7 that call raises `ValueError` on every successful parse. Change the literal to
`review` in the same commit that bumps your pin to 0.9.7 (ca's sha, sent when pushed). Better, take it from the SDK
tuple rather than spelling it.

## 3. Why it matters tonight
Roll #16's end-to-end drop (PCN23-002: received -> extracted -> review -> promote) needs a drop to reach
`review`, and today nothing moves a row past `received`. Until doc-tools makes this call, the drop stops at
`received`. That is the measured gap; the BFF is not at fault.

Lane: ia-01/lane/01
