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
domain:                              # every value an engine can EMIT for each attribute
  <attribute>: [<value>, ...]
rows:
  - when: {<attribute>: <value>}     # a match on declared attributes only
    then: <outcome>                  # a definition id, an audience, a terminal state
```

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
