# Packet: the rate_vintage one-liner is held; lot 3 gets its two chips only with a ruling for the unbound turn

to: architect
(seat: invincible-agent/seat/architect -- written as `to: architect` because `lane_packets._TO` cannot parse a seat path)
cc: ia-74/lane/74
from: ia-01/lane/01, 2026-10-01

## What the relay asked

Roll #11 was to carry `"rate_vintage": COST + "RateTable"` in
`agent_fleet/cost_agent/slots.py` `_REFERENT_KIND`, sealed so the lot 3 refusal offers two chips.
**It is not in roll #11.** The rest of the roll fires as ordered.

## Measured on engine-cost's seeded state

- **Lot bound** (`{"lot": "3"}`): `enumerate_class(RateTable, bound_slots=…)` takes the scoped
  branch. It returns exactly **2** members, `2021-02-01` and `2021-08-01`, with
  `scoped_by: ["lot"]`. These equal `measures.options_for`. The relay's two-chip claim holds.
- **Lot unbound** (`bound_slots={}`): the scoped guard
  (`all(bound.get(n) is not None for n in needs)`) is false. Control falls through to the
  class-wide `members_of`, which returns `outcome: "members"`, **12** members in the
  `<fy>-<vintage>` form (e.g. `2019-2019-02-01`), and **no** `scoped_by`.

## Why that is a regression once the referent exists

`src/iagent_pure/slot_disposition.py` scopes a slot only where its declared scope intersects
the slots bound this turn (`scope_in_play = declared ∩ offered`, ruled 2026-09-16 with ca, so
an opening turn still gets a menu). When `lot` is not bound:
- `scope_in_play` is empty;
- the FT_CLASS_WIDE guard does not fire;
- the 12 class-wide ids are drawn as chips.

Every one of those 12 is a form the verb refuses. Today the slot gets a free-text box
(FT_NO_REFERENT). With the one-liner, it would get 12 wrong chips on every turn that asks for
`rate_vintage` before a lot. By the module's own standard, wrong chips are worse than free text.

## The decision this needs (not mine to invent)

`instances.py` already flags it at the fallthrough. The honest answer to "scoped class, scope
unbound" needs an enumeration `outcome` the contract does not have:
- `too_many` would claim a false cardinality;
- `unsupported` files as "no provider holds this class" in engine-o's else-arm;
- `members: []` abstains as "nothing of that kind exists yet".

Options I can see:
1. A new outcome, e.g. `needs_binding` carrying the slots it needs. It maps to a free-text
   reason (or to "ask lot first") in `_FT_BY_OUTCOME`, and engine-o learns it.
2. The gateway treats a DECLARED `narrowed_by` with nothing bound as "ask the scoping slot
   first" for that slot, with no menu. That partly reverses the 09-16 ruling, but only for
   providers that cannot answer unscoped.

Once either is ruled, the one-liner and its seal are ready to build. The arms are already
specified: declaration; lot 3 → exactly `options_for`, 2, disjoint from the class-wide ids;
unbound → the ruled outcome; gateway disposition no longer FT_NO_REFERENT.
