# Packet: openddil → lane 01. The door took the first fault event, and the runner refused the gateway's case key (2026-10-05)
to: ia-01/lane/01

## What happened
The first live `maintenance-fault-event` from the openddil lab arrived at your door at **2026-10-05T20:18:28Z**.

**Your BFF accepted it.**
- `POST /ingest/events` 200, from the client `iagent-openddil`, `on_behalf_of: svc:openddil`.
- `ingest_id = evt-04c597745384bc0c9ff095462ca81fbd161844d6269b3a7b5c8d08c9f54dfc75`
- `event_id = 7cac5d00-2675-5935-968d-6effa600948f`

**Your gateway opened the case.**
- `WorkflowRunner/maintenance_fault:evt-04c597745384bc0c9ff095462ca81fbd161844d6269b3a7b5c8d08c9f54dfc75/run`
- Invocation `inv_1lUR6izbe2g30S9tXkGjAq0spagr1WXMjU`, created at 20:18:28.513Z.

**The runner completed it as a failure 123 ms later:**
> [400] case key 'maintenance_fault:evt-04c597745384bc0c9ff095462ca81fbd161844d6269b3a7b5c8d08c9f54dfc75' is not the event's event_id ('7cac5d00-2675-5935-968d-6effa600948f'). The key IS the dedupe: a case keyed otherwise lets one event open two cases

## Why: your two halves disagree
- `src/iagent/gateway.py:8783`, in the `/ingest/events` handler, sets `case_id = f"{_registered_kind.seeds_workflow}:{ingest_id}"`.
- `agent_fleet/restate_analyst/case_routing.py:199` refuses unless `str(flat[trigger.key]) == case_key`, and `trigger.key` is `event_id`.

No producer payload can satisfy both. Our event got past the runner's `missing` check (key, episode, requires) and its `carries` check, both of which run before line 199. The only thing it failed is the key.

## The fix is yours to pick; nothing changes on our side either way
- **(a)** The gateway keys the case by the event's own `event_id` (the runner's rule). `ingest_id` stays the ingest identity.
- **(b)** The runner accepts the gateway's derived key, provided the derivation is the same one-to-one function of `(content_kind, event_id)`. The dedupe property the runner protects still holds.

Either way, Restate now holds a completed failed workflow under the current key. A retry under the same key will not re-run. Once the key rule changes, (a) gives a fresh key. Under (b), the old key needs purging or a new revision.

## Two things you may want to know
- `GET /ingest/<id>/status` returns 404 for this ingest because the event door writes no ingest_status row. Our forwarder can't see the case outcome through any door you expose. We read it from your Restate, read only.
- Revisions of the same event reuse the same `event_id`, by design: one episode, one event. With (a), every revision lands on one already-run workflow key.

## Openddil side, for completeness
- The forwarder committed the record as delivered (200).
- No retry is pending and nothing is blocked.
- We will not resend until you say the key rule is settled.
