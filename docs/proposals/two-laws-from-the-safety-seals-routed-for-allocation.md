# Two laws from the ADR-0051 safety seals — routed to `lane/01` for allocation

**Status: PROPOSED, awaiting a number.** Per **R-021**, only `lane/01` allocates ruling numbers, and
an author with a ruling to record routes the text and receives one back. This file is that routing —
**it is not a ruling and must not be cited as one.** When Lane 1 allocates, the text below moves into
`docs/rulings/README.md` verbatim, anchored on the END of the register (never on the next heading,
per the placement rule), and this file is deleted rather than left as a second copy.

**Author:** the safety lane (`lane/74`, worktree `ia-74`). **Architect-ruled 2026-09-13** —
both laws were stated by the architect in the ADR-0051 thread; what is routed here is the text, the
evidence, and the seal each one is drawn from.

**Why two rather than one:** they are adjacent and easy to collapse, and collapsing them loses the
sharper half. The first is about a seal that *moved*; the second is about the subject moving *out
from under it*. One is an instrument failure, the other is a live safety regression that no
instrument would have reported.

---

## LAW ONE — A SEAL THAT MOVES AND IS NOT RE-PROVEN HAS ONLY BEEN RELOCATED

**Drawn from:** `tests/safety/test_concurrence_precedes_acceptance.py`, moved 2026-09-13 from engine
code to the composed decision tables.

When a property's implementation moves, the seal guarding it must move too — and **the move is not
complete until the seal's mutations are re-run against the new subject.** A relocated seal carries
its green with it, and that green was earned against something that no longer exists.

### The specific way it goes wrong, which is not the obvious way

The obvious failure is a seal left pointing at deleted code: it goes **red**, loudly, and gets fixed.
That one is safe because it is noisy.

**The dangerous failure is the seal that is rewritten to the new subject and passes immediately.** It
passes because the new data happens to be correct today — not because the assertion can tell correct
data from incorrect data at the new address. The assertion's discrimination was demonstrated at the
old address, against the old subject, by mutations that no longer apply:

| | old subject | new subject |
|---|---|---|
| what held the choice | `_CONCURRENCE_LEVELS`, a frozenset in `measures.py` | rows in two composed YAML tables |
| how it broke | edit the constant, drop the branch | edit a `then:`, delete a row, add a layer that replaces the table |
| what a mutation had to do | patch a Python name | rewrite the YAML and re-compose |

**No mutation from the left column can fail in the right one.** So a seal that moved and kept its old
mutations has an *unmeasured* assertion and a *decorative* mutation suite — and it reads, to every
future reader, exactly like a seal that was proven.

### What re-proving means concretely

The mutations must break the **new** subject through the **same** path the seal reads it by. For this
one that meant rewriting the composed YAML in a copy of the real directories and re-composing, not
stubbing the reader function: a stubbed reader proves the assertion can reject a dict, which was
never in doubt. Three mutations were run — a wrong target, a deleted row, and a refusal routed
onward — plus **an unmutated copy that must stay green**, because a harness that reddens everything
proves noise rather than discrimination.

### The instrument defect found while re-proving it, which belongs to the same law

The first version pointed the seal at a *factory* (`lambda: _mutated_dirs(...)`) rather than at a
directory already built. The reader is called once per assertion, so the mutation was rebuilt on
every read and the second `mkdir` raised — **a red that came from the harness and not from the edit
under test.** *A fixture whose cost is paid per read is a different fixture on the second read.* It
is recorded here rather than separately because it was found by doing the thing this law requires,
and it is the characteristic way a re-proof goes wrong.

---

## LAW TWO — CHOICE REMOVED FROM CODE BEFORE ITS TABLE COMPOSES IS CHOICE DELETED, AND IT FAILS SILENTLY IN THE PERMISSIVE DIRECTION

**Drawn from:** the ADR-0039 amendment applied to its own first consumer — removing
`_CONCURRENCE_LEVELS` and `acceptance_request_after_concurrence` from `agent_fleet/safety_agent/measures.py`.

Moving a decision from engine code onto the workflow-definition rail is two edits, and **their order
is load-bearing.** The table must compose first; the code comes out second. Reversed, there is a
window in which **no layer holds the choice at all** — and the system does not fault, it proceeds.

### Why the window is invisible rather than loud

Deleting a branch does not produce an error. It produces **the branch's other arm, taken
unconditionally.** For ADR-0051 the removed branch was the one that sent Serious and High risks to a
user representative's concurrence, so during that window every Serious and High acceptance becomes a
**DIRECT** acceptance:

- no exception, no log line, no red suite — the acceptance task opens and a human signs it
- **MIL-STD-882E §4.3.7 is violated**, and the artifact left behind looks exactly like a compliant one
- **the fix produces the failure it exists to prevent** — the amendment's entire purpose is to stop a
  Serious or High risk reaching a signature without the concurrence

**An absent table does not fail closed.** A missing overlay composes to silence (R-042); a missing
decision row means no definition was selected, which surfaces wherever the missing row would have
routed and names nothing. There is no layer whose job is to notice that a choice used to be made.

### The rule, stated so it can be followed

> **Engine code stays until `policy/decisions/` composes.** Removing it first turns every Serious and
> High acceptance into a DIRECT one, silently.

And the general form, which is what makes this worth a number: **when a decision moves between
layers, the new layer must be live and asserted before the old one is removed — because the
intermediate state is not "broken", it is "permissive", and permissive states pass every test written
to catch broken ones.**

### The corollary that closes it

The removal is **asserted, not remembered**:
`test_the_engine_no_longer_holds_this_choice` fails if `_CONCURRENCE_LEVELS =` or
`def acceptance_request_after_concurrence` returns. Not to prevent a duplicate — to prevent the
choice living in **two places that disagree silently**, with the engine's copy winning because it
runs first, and every decision-table seal still green while a table nobody consults is tailored.

*(Matched on the defining form rather than the bare names, because the module's own comment records
the removal by name and a substring check would flag the comment explaining the fix — the
instrument-and-subject-share-a-surface shape, met again.)*

---

## What Lane 1 is asked for

Two numbers, and the entries written at the end of `docs/rulings/README.md`. The safety lane will
then replace the `PROPOSED` citations in ADR-0051 §8 with `RULED 2026-09-13 — see [rulings#r-0NN]`
and delete this file.
