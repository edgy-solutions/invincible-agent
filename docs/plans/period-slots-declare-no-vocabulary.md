---
id:         period-slots-declare-no-vocabulary
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/planning_agent/slots.py (_type_of), agent_fleet/planning_agent/entities.py (FISCAL_PERIODS), agent_fleet/planning_agent/measures.py (_periods, plan_maturity_grid), src/iagent_pure/slot_acceptance.py
summary:    THIRD INSTANCE of "the declaration is less precise than the code it describes" (after `direction: str` over a closed vocabulary and the six id-typed slots). Period slots declare `window: list[str]` and `as_of: str` with NO `values`, because there is no Literal to read them out of — so `accept_slots`, whose whole contract is that the declarations ARE the acceptance schema, has a blind spot exactly here and D05's `window=["this quarter"]` passes the guard clean. THE TWO HALVES FAIL DIFFERENTLY AND THE SILENT ONE IS WORSE. `window` reaches `_periods()` and raises NotInModel -> 422, loud. `as_of` reaches a bare STRING COMPARISON -> `'2026-03-15' <= 'FY26-Q4'` is True for EVERY ISO date including 9999-12-31, so `as_of="FY26-Q4"` is a COMPLETE NO-OP: 200, unfiltered superset, identical to passing nothing. AND THEY ARE TWO DIFFERENT VOCABULARIES BOTH DECLARED AS BARE STRINGS — window takes a fiscal period, as_of takes an ISO date — which is why acceptance row 2 ("maturity grid as of FY26-Q4") CANNOT GO GREEN FROM THE CARRY ALONE. Verified by execution, not by reading.
---

# Period slots declare no vocabulary — and the two halves fail in opposite directions

**Found 2026-08-29** while scoping the `ask` disposition's option sources
(`[[elicitation-ask-disposition]]`), which needed to know what a period menu would be built from
and discovered the declaration carries nothing to build it from — and then that the same absence
has a live consequence in the guard.

## The declaration gap

`slots_for()` derives everything from `inspect.signature`, and `_type_of` emits `values` only when
it finds a `Literal`. Period slots have none:

```
window   ->  {"name": "window", "kind": "spoken-optional", "type": "list[str]"}     # no values
as_of    ->  {"name": "as_of",  "kind": "spoken-optional", "type": "str"}           # no values
```

Meanwhile `FISCAL_PERIODS` is **eight fixed keys** in `agent_fleet/planning_agent/entities.py`,
named explicitly rather than computed *"because a computed fiscal calendar is a second place for
the convention to live."* The vocabulary is closed, small, and already single-sourced. **It just
never crosses into the declaration.**

This is the **third instance** of one species:

| # | slot(s) | declared as | actually requires |
|---|---|---|---|
| 1 | `direction`, `kind` | `str` | a closed 2-value vocabulary — **fixed**, now `Literal` |
| 2 | `site_id`, `capability_id`, `project_id`, `process_id`, `tech_id`, `scope_initiative_id` | `str` | an opaque id from a small closed set (`[[the-filler-has-no-entity-resolution]]`) |
| 3 | `window`, `as_of` | `list[str]`, `str` | **this item** |

> **The imprecision always runs toward permissiveness** — the model is invited to supply something
> it cannot get right, and the guard is invited to accept it.

## The live consequence: `accept_slots` has a blind spot exactly here

`src/iagent_pure/slot_acceptance.py` is explicit that **"THE DECLARATIONS ARE THE ACCEPTANCE
SCHEMA"** — *"not merely router-facing metadata … the contract an extraction must satisfy."* The
module fails **closed** on missing declarations, deliberately, so that an undeclared verb is never
more permissive than a declared one.

**But a declared slot with no `values` is not "missing" — it is present and says nothing.** There
is no membership test to run, so the guard passes the value through. Measured, `D05`:

```
"what does spend look like this quarter"  ->  window: ["this quarter"]   conf=0.85
```

That is not an invented period — it is **the raw words, shaped like a value**, and it clears
acceptance cleanly on its way to the engine. The guard's fail-closed posture is correct everywhere
except the one place where the declaration is silent rather than absent.

## THE TWO HALVES FAIL DIFFERENTLY, and the silent one is worse

### `window` — loud

```python
def _periods(window):
    unknown = [p for p in window if p not in FISCAL_PERIODS]
    if unknown:
        raise NotInModel(f"unknown fiscal period(s): {', '.join(unknown)}")
```

→ **422**, naming the bad value. Recoverable, visible, and the engine is doing the job the
declaration didn't.

### `as_of` — silent, and it is a complete no-op

```python
cutoff = as_of or "9999-12-31"
... if a.assessed_at <= cutoff
```

A **bare string comparison** against ISO dates. Verified by execution, not by reading:

```
'2026-03-15' <= 'FY26-Q4'   ->  True
'2027-12-31' <= 'FY26-Q4'   ->  True
'9999-12-31' <= 'FY26-Q4'   ->  True
```

`'2' < 'F'`, so **every** assessment date passes. `as_of="FY26-Q4"` is **indistinguishable from
passing nothing**: 200, every cell, no error, no signal. The parameter arrives, is accepted, is
*used* — and changes nothing.

> This is the silent twin of the same defect, and `[[the-filler-has-no-entity-resolution]]` already
> named it in passing — *"`plan_maturity_grid.as_of` has no such validation: a wrong-shaped value
> there returns 200 with an unfiltered superset."* This item supplies the execution that confirms
> it and the reason it happens.

## ⚠ AND THEY ARE TWO DIFFERENT VOCABULARIES, WHICH IS THE PART THAT WILL COST SOMEONE A DAY

Both are declared `str`-ish. They are not the same thing:

| slot | vocabulary | example |
|---|---|---|
| `window` | **fiscal period** | `["FY26-Q4"]` |
| `as_of` | **ISO date** | `"2026-09-30"` |

A filler reading *"maturity grid as of FY26-Q4"* will produce `as_of="FY26-Q4"` — the natural
reading of the phrase, the same vocabulary the neighbouring slot uses, and a **no-op**.

> ### CONSEQUENCE FOR ACCEPTANCE ROW 2, and it belongs in the carry lane's hands
>
> `[[slot-resolution-entities-in-the-resolver-substrate]]`'s four-row table, row 2:
> *"maturity grid **as of FY26-Q4**" — today unfiltered, latest per cell → green when cells are
> assessed **at or before** that date.*
>
> **Row 2 cannot go green from the carry alone.** The parameter will arrive correctly and the
> output will be unchanged, because the value is in the wrong vocabulary and the comparison
> silently accepts it. Someone will read that as a broken carry and go looking in the supervisor.
>
> Row 2 needs one of: `as_of` accepting a fiscal period and converting it to the period's end date;
> or the declaration saying `iso-date` loudly enough that the filler produces one. **The first is
> better** — the phrase is the spec, and users say "as of FY26-Q4", not "as of 2026-09-30".
>
> Row 4's lesson generalises here: **row 2 is a row whose answer can be right for the wrong
> reason** — assert on the filtered cell set, never on the parameter's arrival.

## The fix, and why it is small

**Attach the vocabulary to period-kind declarations.** `FISCAL_PERIODS` is already the single
source; the declaration layer is already **derived, never hand-kept** — *"this repo has paid four
times for lists someone remembered instead of enumerating; this is not the fifth."* So the fix must
**read the keys**, not restate them.

Three things it buys at once:

1. **`accept_slots` gains its membership test** — `D05` is refused at the guard, loudly, instead of
   422ing at the engine. The refusal is already a first-class, logged outcome.
2. **The filler is told the vocabulary** — the same `Literal`-visibility that fixed `direction`.
   (With the coercion caveat banked from `E06`: declaring a vocabulary made a plausible wrong
   answer *more* available, so this must be paired with the membership test, not substituted for
   it. **A permitted-value list is a membership test, not a menu to snap to.**)
3. **The period menu becomes real** for ADR-0033's amended #2 — `[[elicitation-ask-disposition]]`'s
   option-source table currently has to mark period "the vocabulary exists; the declaration does
   not carry it."

**Not a blocker for the `ask` disposition.** `window` and `as_of` are both **spoken-optional**, so
they never trigger an elicitation. This is a carry-lane and guard-lane defect that the elicitation
scoping happened to surface.

## What this item does NOT claim

**Not that `D05` should have been answered.** The corpus's ruling stands: nothing supplies the
filler a notion of *now*, so *"this quarter"* has no honest resolution and MISSED is correct. This
item is about what happens to the non-value **after** it is produced — it should die at the guard,
not at the engine, and certainly not silently.

**Not a change to `_periods()`.** The engine's loud refusal is correct behaviour and stays. The
point is that the guard should have caught it first, and that its silent twin should be loud too.
