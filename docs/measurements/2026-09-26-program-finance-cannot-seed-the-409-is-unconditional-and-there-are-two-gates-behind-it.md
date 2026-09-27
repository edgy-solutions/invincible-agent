# Lane 1, 2026-09-26 — why `program_finance` cannot seed, and what the template lane needs

**Asked: read what binding it lacks and report. Answer: it lacks ADR-0050 §3's shared-slot
carry, which is not implemented at all rather than misconfigured — and there are TWO gates in
front of this template, not one. A third defect would make the carry miss even after it lands.**

Not my lane to fix. This is what it needs, stated so the template lane can act on it.

## 1. The 409 is unconditional

`src/iagent/gateway.py:2138-2147`:

```python
_unbound = sorted(_consumed)
if _unbound:
    raise HTTPException(status_code=409, ...)
```

`_unbound` is the consumed set with **nothing subtracted**. There is no binding source to
subtract: the seed request carries no shared-slot values, so no template with a non-empty
`consumes` can ever pass this line. **The 409 is not a computed "nothing binds it yet" — it is
"`consumes` is non-empty".**

For `program_finance`: `_declared = {program}`, `_consumed = {program}` (all six panels),
so `_undeclared` is empty (no 422 — the template is well-formed) and `_unbound == ["program"]`.

The refusal text is accurate and says so: *"This is the ADR-0050 §3 carry, not a fault in the
template or the request."* The template is not broken. The mechanism is absent.

## 2. Behind the 409 sits a 501 that this template also hits

`gateway.py:2149-2159`, the very next branch:

```python
if _template.template_id != "portfolio":
    raise HTTPException(status_code=501, detail="... Only 'portfolio' seeds today.")
```

**Satisfying the 409 moves `program_finance` to a 501, not to a board.** The seeder still runs
the portfolio PHRASE list rather than dispatching the template's declared verbs. The carry is
necessary and not sufficient; the per-panel pre-resolved dispatch is the other half, and the
code comment already names it as "the next increment ... deliberately not implied".

Anyone measuring progress by "the 409 is gone" will read a 501 as a regression. It is not.

## 3. The defect that would survive both fixes — the slot NAME does not match the kwarg

`src/iagent/canvas_template.py:49-50`, `SharedSlot.name`:

> **"Slot name as the verbs' signatures spell it."**

The canvas declares `name: program` (`policy/canvases/program_finance.yaml:66`).

**The six finance verbs spell it `program_id`.** The canvas's own header says so — *"All six
take `program_id` (26 occurrences in the finance engine against ZERO in planning)"* — and every
finance call site in the suite passes `program_id=`.

So by the model's own documented contract the declared name is wrong. Once the carry lands, an
answer bound under `program` would not reach a verb that takes `program_id`, and the panels
would refuse **with the carry working correctly**. That is a failure that looks like the carry
not having landed, sitting immediately after the change that lands it.

**Nothing checks this.** Searched every test touching `shared_slot`/`SharedSlot`
(`tests/planning/test_seed_canvas_takes_the_template_as_a_slot.py`,
`tests/planning/test_shared_slots_are_template_scoped.py`, `tests/test_citation_anchors_resolve.py`)
— no arm compares a declared slot name against the kwargs the consuming panels' verbs actually
accept. The contract is a docstring only.

**The fix is a choice, and it is the template lane's to make:** rename the slot to `program_id`
(honours the documented contract, and the description stays user-facing prose), or add an
explicit `binds_to` field (lets the ask keep a human name). Either way it wants a seal deriving
the consuming panels' verb signatures and asserting every declared shared slot name is a kwarg
they take — which is checkable today, before the carry exists.

## 4. A stale comment in the ratified file

`policy/canvases/program_finance.yaml:63-64` reads:

```
# EMPTY PER DISPATCH, and the blocker is §3's, not seedCanvas's.
shared_slots:
  - name: program
```

**`shared_slots` is not empty.** The comment describes a previous state of its own file, two
lines above the content that contradicts it. A reader checking whether the slot is declared gets
the wrong answer from the comment and the right one from the YAML. Worth a one-line correction
in whichever commit next touches the file.

## 5. What I did not verify

- **That a bound `program_id` actually produces six cards.** Untestable today: both gates refuse
  before dispatch, so nothing has ever run these six panels through the seed path.
- **Whether `portfolio` would regress under a rename.** R-005 made declaration template-scoped
  precisely so it would not, and `portfolio` declares no consumed slots — but I read the ruling's
  reasoning rather than re-running `portfolio`'s seed.
- **The ADR-0050 §3 text itself.** I worked from the gateway's and the template's accounts of
  what §3 requires, not from the ADR. If those accounts drifted, this report inherits the drift.
- **Whether any OTHER ratified canvas has the same name/kwarg mismatch.** I checked
  `program_finance` because it was the one asked about. This is a sample, not a census, and the
  seal proposed in §3 is what would turn it into one.
