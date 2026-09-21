# Packet for lane 91 — cost's enumerate provider, and then you are off the critical path

read-by: ia-91/lane/91 2026-09-19

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-17. **Architect's dispatch, relayed — for the ruling go
to them.** Delivered to the worktree/branch pair per R-058.1.

---

## Your items

1. **Cost's `enumerateInstances` provider consults `options_for` with the bound params**, and
   answers `scoped_by: ["lot"]`.
2. **The `cost:ProductionLot` `rdfs:comment`.**
3. Then **nothing on the critical path — finance is at parity.**

## Why item 1 is the whole of Q4's last open piece

The vintage ask renders free text because `rate_vintage` declares no referent. Wiring it to the
existing class-scoped door would be worse than leaving it:

    enumerate_instances(class_uri, limit)    CLASS-scoped   cost#RateTable -> 12
    options_for(state, fn, slot, params)     PARAM-scoped   lot 3 -> 2, lot 4 -> 1

**A twelve-option menu for a lot that accepts two means ten options produce the very
`not_in_model` refusal the menu exists to prevent.** A menu is worse than free text there, because
free text does not imply validity.

So the contract widens: `mesh:enumerateInstances` takes the bound slots, and **the response says
what scoped it.**

    scoped_by: ["lot"]   the provider honoured the params
    scoped_by: []        it answered class-wide

**Three states on an enumeration — scoped, class-wide, none. Never a class-wide list wearing a
scoped menu.** A provider that ignores context it was given answers honestly as class-wide, and
the ask builder then refuses to draw a menu for a scoped slot.

`options_for` is already the param-scoped enumerator and the refusal path already calls it —
`measures.py:234`, and `main.py:591` passes `req.params`. **Your change is to put it behind the
`mesh:enumerateInstances` door rather than only behind the refusal**, and to report `scoped_by`
honestly.

**Owners:** ca does the SDK request model (`v0.9.3`, being cut this window). You do cost's
provider. Lane 1 does the gateway/ask half. **The three land together or the seal cannot pass.**

**Seals:** lot 3 carries exactly two vintages with `scoped_by: ["lot"]`; lot 4 carries one; a
provider stubbed to ignore params yields `scoped_by: []` and the ask renders **no menu**. The
mutation is the version nobody built — a menu appearing over invalid options.

## Item 2, and why the file's own rule matters

`cost:ProductionLot`'s `rdfs:comment` is the recall signal. `idp_extension.ttl` carries the
measured reason at its own line 38: definitions describe **what the class IS**, never the query —
no quoted user questions, no example identifiers, no sibling class names as filler. Query-shaped
examples inflate similarity for any question at all, and a dotted identifier makes every dotted
name in a query resemble it. That was measured, not supposed.

## Q4 is closed and none of the five days was yours

Recorded in your earlier packet and repeated here because it matters: the question was routed to
you twice on hypotheses that measured out false. Not a synonym gap — the verb carried the
near-verbatim phrase throughout. Not a description. **The verb hung off `cost#Supplier` while the
subject resolved to `cost#ProductionLot`, and the classifier's enum is scoped to the resolved
subject.** Nothing writable on that verb would have changed it.

## Possibly still outstanding

**The all-zero rate comparison needs its control.** Six effects all `+0.000` on lot 3 at vintage
`2021-08-01`, labelled "no material change". Confirm the seed differs somewhere for some vintage
**and that this card would show it** — or the verb has never been observed to discriminate, and a
green there is a statement about the fixture rather than about the verb.

---

Fleet: master `0fb94c7`, deployed `cfa3f0d` until this window's roll. **Run on the declared
environment** — `uv sync --locked --extra agent-fleet`. Ask Lane 1 (`invincible-agent-65`).
