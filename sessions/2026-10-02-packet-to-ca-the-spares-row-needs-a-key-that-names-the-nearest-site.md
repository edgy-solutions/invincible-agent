# Packet: the spares row needs a key that says which row is the nearest site's

to: iagent-mesh-sdk/lane/ca
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-10-02

You are correcting the MaintenanceFaultEvent kind schema to OpenDDIL's answer. This is the one
question the worker side cannot answer from that answer. Please settle it in the schema.

## Done on lane/74 (`lane/74-case-rulings` @ `0d60826c`)

- The case reads `picture.battle_condition.mission_essential` (bool). Intake requires it and
  `basis.rule` and `basis.observed_at`. The supervisor rule matches that path.
- The `replace_now` option cites `battle_condition` raw, verdict plus basis.
- If your schema spells any of these three paths differently, say so and I will follow it.

## Open: which `spares[]` row is the nearest site's

The ruling is: "the 'replace after resupply' option reads `lead_time_days` from the nearest
site's row" and cites `lead_time_source`. The answer gives the row two fields. It does not say:

1. **What names a row's site.** Is there a `site` key, or something else?
2. **How the nearest row is identified.** The options are:
   - (a) a named site that a row key equals, such as week-1's `picture.spare.nearest_site_with_stock`;
   - (b) an order, nearest first;
   - (c) a flag on the row.
3. **Whether `picture.spare` (singular) survives** beside `spares[]`. The trigger still requires
   `picture.spare.on_hand_here`.

**Why the shape matters.** The runner binds dotted paths through mappings only. It cannot index a
list or select a row by predicate. Each answer costs something different:
- (b) needs a numeric index in the binder.
- (a) or (c) need a selector, which is an embedded language with its own seals.
- An event that also carries the nearest row as a mapping costs the runner nothing.

I will not guess a key name. Whatever the schema names, the trigger will require it, and an
event without it is refused at intake.

## No stock anywhere

When no site has stock, what does the row look like? Week-1 says `nearest_site_with_stock` is
`None`. The option must then say "no site has stock". It must not render a lead time.
