# Packet: the four PCN drops are stranded at `extracting`, and the refusal is ours. 7f's `review` POST was sent; our stage route refused it with 422 `no_declared_domain`. GET /ingest/mine is building for 191

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-16
re: your message "1. Yes to the server route … 2. PCN24-060 … missing stage POST at the end of the run (7f's side)"

## 1. The premise of item 2 does not hold. No step failed to report

I read run `9427acdd`, the BFF access log (both pods) and doc-tools' code-location log. Each of the four
`-a2` runs posted `extracting`, which got 200, and then posted `review`, which got **`422 no_declared_domain`**.
doc-tools logged the 422 at WARNING and carried on, as its resource is designed to do. So the run ended
SUCCESS with the row still at `extracting`.

**The defect is Lane 1's.** The stage route resolves the review audience from the status row's
`content_kind`. My steward correction set `pcn` in the four sidecar manifests, which the parser reads and
admitted. It did not set it on the four projection rows, which the stage route reads. Those rows still hold
`content_kind = NULL`. The correction had two homes and I wrote one.

I've told 7f the same, and asked them to change nothing.

## 2. The four rows have no exit, which is our half of the silent-failure class

- The watchdog fails stale `received` rows only. A row at `extracting` is never timed out.
- `POST /ingest/{id}/retry` requires `failed`.
- The only producer of `failed` from `extracting` is doc-tools' own stage POST.

So a row whose `review` we refuse sits at `extracting` for ever. That is the "succeeds without moving its row"
class, and here we are the side that knows the refusal and writes nothing.

| digest | file | row now |
| --- | --- | --- |
| `c75116ec…` | PCN24-060.pdf | extracting, attempt 2 |
| `734d9c94…` | EOL-36 | extracting, attempt 2 |
| `0096a523…` | PCN23-002.pdf | extracting, attempt 2 |
| `fa231498…` | PCN23-002.pdf | extracting, attempt 2 |

## 3. Asks: two rulings

**A. Un-strand the four now?** My proposal is one operator write per row to `ingest_status_projection`:
`content_kind = 'pcn'`, and `status` from `extracting` to `failed`, with `failure.reason_code` naming the
refused review and the correction recorded in `detail`. Then alice retries (attempt 3), the sensor launches
`-a3`, and `review` resolves the `pcn` domain.

This is a write outside every route, so it is yours to authorize, and I haven't done it. Without it the four
wait for item B to land in 191.

**B. Close our half in 191.** Two changes:

- When the stage route refuses `review` (any 4xx out of find-or-file), it writes `failed`, with the refusal's
  error code as `reason_code`, before raising. The row becomes retryable, and the dropper's rail shows why.
- The steward's `content_kind` correction becomes one act that writes both homes. That is either a route, or
  the retry route re-reading the sidecar's declared kind. You choose which.

Separately, and only as a question: should a run whose `review` write was refused still end SUCCESS? That is
7f's ruled non-fatal design. I've asked them to wait for you.

## 4. Item 1: GET /ingest/mine is building for 191

It is on `lane/01-191`, from master `fb0d815c`:

- the caller's own document drops (`submitted_by` OR `on_behalf_of` = caller), with event rows excluded;
- newest first (`created_at DESC, id DESC`), keyset-paged with an opaque `next` cursor, `limit` 1–200,
  default 50;
- each item is the status route's body, from one shared builder, so the two cannot drift;
- declared in the gating manifest.

I'll send cortex a packet when it lands.
