# `policy/decisions/` — the SEED half of the decision-table layer (ADR-0039)

**Choice lives in decision tables at trigger and termination. Definitions stay linear.** A
definition that branches is a definition that has absorbed a policy question; the table is where
that question belongs, because **a table's rows are reviewable as policy and a branch is
reviewable only as code.**

## This directory is STRUCTURAL. Domain tables live in an overlay.

Same ADR-0036 split as `policy/task_kinds/`, and for the same reason: a **domain name may not
enter the platform seed.** A programme's tailoring — which risk levels need concurrence, which
disposition routes where — is that programme's, and it composes over this seed from
`policy/overlays/<deployment>/decisions/`.

    policy/decisions/                          seed        structural rows only
    policy/overlays/<name>/decisions/          overlay     domain tables, FULL REPLACEMENT by key

Composition is the SDK's `compose(seed, overlays, key_field=..., builder=...)` — **the same
composer `task_kinds` uses, parameterised rather than copied.** ADR-0039 refuses a fourth
composer by name.

## The row shape

```yaml
decision: <table id>                 # the key; an overlay row REPLACES a seed row wholesale
matches: [<attribute>, ...]          # the attributes this table reads — DECLARED, not inferred
terminals: [<state>, ...]            # states this table may END at — DECLARED, see below
domain:                              # every value an engine can EMIT for each attribute
  <attribute>: [<value>, ...]
rows:
  - when: {<attribute>: <value>}     # a match on declared attributes only
    then: <outcome>                  # a definition id, an audience, or a DECLARED terminal
```


## `terminals:` — where a terminal state comes from

**`then` may name a terminal, and until now nothing said where terminals COME FROM.** A definition
id resolves against `policy/workflows/`; an audience resolves against the audience list; a terminal
resolved against **nothing** — so a typo'd terminal was indistinguishable from a deliberate one,
and the reference seal had no choice but to skip it.

**A table DECLARES the terminals it may end at, and a typo'd terminal then fails like a typo'd
definition.** That is not new syntax on the rail — **it is totality applied to TARGETS**, the same
move `domain` makes for inputs. Both answer *"complete over what?"* from outside the rows.

    then: safety_acceptance_direct   ->  resolves in policy/workflows/
    then: risk_acceptance:HIGH       ->  resolves in the audience list
    then: timed_out                  ->  resolves in THIS TABLE'S `terminals:`
    then: timedout                   ->  RED, naming the declared list

**DECLARED PER TABLE, NOT GLOBALLY.** A global vocabulary would make every terminal available
everywhere, so a table could silently end in a state its own process has no meaning for. The cost
is repetition; the benefit is that the declaration is readable beside the rows that use it — and a
terminal nobody can reach from this table is a row that cannot fire.

**`timed_out` is the first one**, and it exists because `HumanAwaitStep.deadline` terminates
there: **a deadline with nowhere to land is a field that cannot be acted on.**

## Two invariants, and both are sealed

**TOTALITY — every attribute value an engine can emit has a row.** A table that is total for the
values someone thought of, and silent on the rest, does not fail: it **falls through**, and a
fall-through in a selection table means *no definition was chosen* at the moment a human decision
was due. `tests/test_a_decision_table_is_total_and_unique.py` fails the build instead.

**UNIQUENESS — no two rows match one input.** Two matching rows make the outcome depend on row
order, which is *not* a declared property of a YAML list. **The same defect as a phrase claimed by
two verbs**: each row is correct read alone, and the contradiction exists only between them
(R-035).

## What must NOT go in a table

**A condition on something no engine has measured is a VERB TO WRITE, not a formula to add.**
The moment a table computes — compares two numbers, derives a value — its rows stop being
reviewable as policy and become reviewable as code, **and the reviewer changes from a process
owner to a developer.** A verb that emits `deadline_missed: true` costs one measure and keeps the
reviewer. That is ADR-0034 in a sentence, and it is the whole argument for `matches` naming
declared attributes only.
