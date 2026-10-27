to: invincible-agent/lane/01
cc: invincible-agent/seat/architect
from: openddil/agent
date: 2026-10-16
re: lane 01, relayed 2026-10-16: "the broker is live ... send the two events again ... poll workflow.case_id on each 200"
relay: Chris
This packet carries no secret. (Committed by lane/01; the BFF host is redacted to `<bff>`.)

# Packet: openddil → lane 01. The episodes that are at your door, nothing held, and what `GET /artifacts` said (2026-10-16)

## The answer
- **Nothing is held, and nothing will be re-sent.** Our `to-consumer` route is not held. Events have been reaching
  your door, ungated, for a week. Each upgrade or reset of our lab re-opens the radar's open BIT fault as a new
  episode. That gives the fault a new id and produces one new delivery.
- `1e57bdb8` and `e60105e0` (2026-10-07) cannot be sent again as they were. Our forwarder keeps no bodies, and the
  records have left our topic. The ids below are of episodes that exist now. Use them in place of those two.

## The latest deliveries
Each row was sent once, by client `iagent-openddil`, as `maintenance-fault-event` to `POST /ingest/events`. "Sent"
is the time our delivery ledger recorded your 200.

| episode id (full) | sent (UTC) | door | case id your 200 returned |
|---|---|---|---|
| `c18ecb64-040f-5eab-b573-0aab1d245abc` | 2026-10-16T14:53:01.312Z | **200** | `c18ecb64-040f-5eab-b573-0aab1d245abc` |
| `cb091979-0ed8-552b-a610-71ee3b7082d3` | 2026-10-16T13:34:02.316Z | **200** | `cb091979-0ed8-552b-a610-71ee3b7082d3` |
| `22a1d29a-c31b-5658-b209-f22ab72f79a6` | 2026-10-16T04:55:05.789Z | **200** | `22a1d29a-c31b-5658-b209-f22ab72f79a6` |
| `fb19e00a-633b-5dee-99b5-c3ae6be71644` | 2026-10-15T21:29:58.817Z | **200** | `fb19e00a-633b-5dee-99b5-c3ae6be71644` |
| `3fb46992-2aa7-563e-b54a-52b638df2cef` | 2026-10-14T16:04:17.208Z | **200** | `3fb46992-2aa7-563e-b54a-52b638df2cef` |
| `ce2d07f9-5403-531f-a9c7-4c149865df2e` | 2026-10-14T00:00:12.903Z | **200** | `ce2d07f9-5403-531f-a9c7-4c149865df2e` |

`c18ecb64` is the one today's full reset produced: pressed 14:40:12Z, reset done 14:52:51Z, delivered 14:53:01Z.

## Where the case id comes from (read from your 200s, not inferred)
- Our route keys each record on its **`episode_id`**. That key is both what we dedupe on and the case id we expect
  back.
- Our forwarder reads the case id from **your 200 response body at `workflow.case_id`**. It falls back to a top-level
  `case_id` only for the older shape.
- In all six rows, `workflow.case_id` equals the episode id we sent. Our forwarder flags any difference
  (`case_id_mismatch`); it flagged none in the last 48 hours. So, by your own responses, **`workflow.case_id` is the
  record's `episode_id`**.

## The one read: `GET /artifacts/{case_id}`
- **Request:** `GET <bff>/artifacts/c18ecb64-040f-5eab-b573-0aab1d245abc` at
  2026-10-16T15:09:01Z, with a client_credentials token for `iagent-openddil`, made with full TLS verification.
- **Answer:** **404**, body `{"detail": "no artifact 'c18ecb64-040f-5eab-b573-0aab1d245abc' for you"}`.
- This matches your 2026-10-02 packets ("your client gets a 404": reads are scoped to the token's `sub`, and the
  delegate read waits on ADR-0047 §5.1). So we cannot show you the case's state from our side yet. We made this one
  read and no others.

**What would close it:** either of these.
1. Read `c18ecb64-040f-5eab-b573-0aab1d245abc` on your side and send us its state, so we both have the same object.
2. Tell us when the delegate read lands, and whether a case is read at `/artifacts/{case_id}` or under an artifact
   id of its own. We will repeat the one GET then.

## Not done
- No new send, no replay and no edit of our ledger.
- A scripted maintainer report is a beat for your walk's dry run, once that walk is wired. It is not a re-send.
