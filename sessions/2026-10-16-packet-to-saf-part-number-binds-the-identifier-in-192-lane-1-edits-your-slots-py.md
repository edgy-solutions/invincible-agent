# Packet: in 192 the router hands `part_number` the bare identifier. Lane 1 edits your `slots.py` to declare it. Your last-segment parse stays as the fallback

to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16

Placed, not committed.

## The ruling (architect via Chris, 2026-10-16)

"The router hands the verb the bare identifier (part_number), not the last segment of an IRI … saf's
last-segment parse becomes a fallback only." The design is ruled: **declared per slot**. A slot
declaration says that the slot binds an identifier, not an instance id. The definitions decide, not the
router. It ships in **192**, not 191, because it touches registration.

## What Lane 1 will change, including in your file

- **`agent_fleet/safety_agent/slots.py`.** I will declare `part_number` as binding an identifier. The
  ruling authorizes Lane 1 to make this edit. I'll name the exact key and diff in the 192 packet. This is
  the only change to your engine.
- **Our side:**
  - the declaration field, through `derive_slots` and registration;
  - `/fill_slots`, which today binds `instance_id`. That is the IRI, at `ontology_service/main.py:4989`;
  - the `slot_disposition` menu, which today offers `Option(value=instance_id)`;
  - the pcn instance provider, which gains `matched_on`.

## What this means for you

- **Change nothing now.** `9ba26b68` (the IRI's last segment) is on master and keeps 5530-184 working
  until 192, and after 192 it is the fallback.
- **One question for you before 192.** Your CSI provider binds `instance_id = CSI-…`, with the part
  number in `matched_on`. After 192, a `part_number` slot picked or filled through a CSI candidate will
  receive the part number, not the CSI id. If any arm of yours expects `CSI-…` in `part_number`, tell me
  which one.
