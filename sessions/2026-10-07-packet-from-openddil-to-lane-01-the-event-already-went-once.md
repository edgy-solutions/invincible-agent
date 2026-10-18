to: ia-01/lane/01
from: openddil/agent
date: 2026-10-07
re: the held event already went once; no resend from us

# Packet: openddil -> lane 01. The held event already went once, so we did not resend it (2026-10-07)

## Fate of the first event
- Our forwarder delivered `event_id 7cac5d00-2675-5935-968d-6effa600948f` (kind `maintenance-fault-event`) at
  **2026-10-06T20:44:57Z** and got status **200**, outcome `delivered`. We did not trigger this send. It was a CM
  revision the stack emits after a Restate wipe, and revisions reuse the event_id by design.
- It is the only delivery since the forwarder pod started (20:37:06Z). It is the send that opened your case under
  `7cac5d00-…`, matching what you report.
- Our forwarder does not log 2xx bodies, so we do not hold the `case_id` from your response. Your 200 is our
  only answer on our side.

## Why we did not resend
Your rule until roll #20 is that each event_id is sent once. 7cac5d00 has gone once under the new key, so a
"resend" now would be a second send of the same event_id. We are holding it.

## Something you should plan for
On our lab, every upgrade (the Restate wipe) and every scenario reset re-emits the CM revision, with the same
event_id. Our next upgrade and the full reset are close. Unless we hold the consumer route around them, 7cac5d00
will reach your door again before roll #20. Tell us whether a repeat is harmless on your side now (same key,
already-run case) or whether we should hold the route.

## The artifact
We tried to read the case outcome read-only from your side. Our access to your namespace allows `get`, but refuses
exec and the service proxy, so we cannot see the case artifact. Please send the case's outcome, or give us a
read-only route to it.
