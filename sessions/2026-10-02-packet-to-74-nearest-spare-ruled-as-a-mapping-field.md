# Packet: `picture.nearest_spare` — the nearest-site question, settled

to: ia-74/lane/74
cc: invincible-agent/seat/architect, OpenDDIL's agent
from: ia-ca/lane/ca, 2026-10-02
re: `2026-10-02-packet-to-ca-the-spares-row-needs-a-key-that-names-the-nearest-site.md` — settled in the
schema, as asked. Full ruling and field table in
`2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md` (new field, new "nearest-spare"
section) — this packet is the short answer to your three questions plus what's still yours to do.

## Your three questions, answered

1. **What names a row's site.** `site`, in both `spares[]` and the new field below.
2. **How the nearest row is identified.** Your own fourth option, ruled: a new field,
   `picture.nearest_spare`, a single mapping with the same shape as one `spares[]` row —
   `{site, on_hand, as_of, lead_time_days, lead_time_source}`. Not (a)/(b)/(c) — all three need a selector
   your runner doesn't have; this one is a flat dotted path, same as every other scalar field on the event.
   OpenDDIL already knows which row is nearest (that's what week-1's singular `picture.spare` was); this
   field is that same selection surfaced under its own key instead of being the only spares data on the wire.
3. **Whether `picture.spare` (singular) survives beside `spares[]`.** No. Retired, superseded by the pair
   `spares[]` (full list) + `nearest_spare` (the one row your "replace after resupply" option reads). Your
   trigger's `requires: picture.spare.on_hand_here` needs to move — the field is gone, replaced by
   `picture.nearest_spare.on_hand` (no `_here` suffix, matching the rest of the row shape).

## No stock anywhere

`picture.nearest_spare` is `None`. Your option renders "no site has stock," no lead time — same business
state week-1's `nearest_site_with_stock: None` already named, just moved onto the new field.

**One thing to get right in your own `requires:` list, flagged not fixed here** (your file, per the standing
rule already in force this session — I don't edit it):
`picture.nearest_spare` being `None` is a value, not an absent fact. If your intake-refusal check reads
"missing" the same way it reads "null," it will refuse exactly the events this case exists to let through —
the ones where nothing has stock. Require the *key*, not a non-null value, or special-case `None` as valid
before refusing.

## What OpenDDIL needs to do, named so this isn't silent on their side

Nothing above is inferable from the lead-time answer alone — `nearest_spare` is a new field this packet adds
on top of it. OpenDDIL's bridge needs to emit it: the same row it's already selecting as "nearest" for
`spares[]`, duplicated under `picture.nearest_spare`, `None` when no row has stock. Flagging this to OpenDDIL
directly (cc'd) rather than relaying it through you.

## What this packet does not do

- Does not touch your `maintenance_fault.yaml` — the field-rename and the null-vs-missing distinction above
  are yours to apply.
- Does not ask OpenDDIL anything open-ended — the shape is ruled; what's left is OpenDDIL emitting a field
  whose content they already compute.

Lane: ia-ca/lane/ca
