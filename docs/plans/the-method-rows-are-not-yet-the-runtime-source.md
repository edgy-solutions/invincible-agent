---
id:         the-method-rows-are-not-yet-the-runtime-source
status:     open
owner:
blocked-on: policy/measures/ COPY riding into a built agent image
repo:       invincible-agent
code-site:  agent_fleet/finance_agent/measures.py (EAC_METHODS, EAC_FORMULA), agent_fleet/finance_agent/method_registry.py, policy/measures/, .github/workflows/build-containers.yml (the COPY)
summary:    ADR-0053 section 2 wants EACMethod's values to be the rows that exist; the rows and their composer landed 2026-09-15 and the engine still reads the Literal. Deliberate sequencing, not an unfinished edit - the import would be at module scope with every verb behind it, so a COPY that slipped means a finance engine that does not boot while the suite stays green. Data and COPY in one release, the runtime depending on them in the next; a seal pins the COPY line so the second half cannot land against a missing first. Also records the one thing the rows still owe: derived_from.clause names each formula and does not number a clause.
---

# The method rows exist and the runtime still reads a `Literal`

**Filed 2026-09-15 — `lane/91`. Deliberate sequencing, not an unfinished edit.**

ADR-0053 §2 says *"slot vocabularies attach from the registry at registration — so `EACMethod`'s
three values stop being a `Literal` in a signature and become the rows that exist."*

`policy/measures/` now holds those three rows, `method_registry.py` composes them, and
`tests/finance/test_the_method_registry_rows.py` seals them. **The engine still reads the
`Literal`.**

## Why the switch was not made in the same commit

`policy/measures/` reaches a container through a per-file `COPY` in `.github/docker/Dockerfile.agent`
heredoc inside `.github/workflows/build-containers.yml`. That file's own comment says the
per-file COPY *"is itself the fragile part: the next shared-policy file will need"* it — and by
its own count this is the **fourth** time that sentence has come true.

If the COPY and the import landed together and the COPY were the half that slipped, the finance
engine would not boot. Not degrade — **not boot**, since the import is at module scope and every
verb is behind it. The suite here would stay green the whole time, because the repo has the
directory whether or not the image does.

> **The data and its COPY ship in one release; the runtime starts depending on them in the
> next.** Reversing that order is how a green suite ships an unstartable pod.

`test_the_policy_directory_is_COPIED_into_the_agent_image` seals the COPY line at CI time so the
second half cannot land against a missing first half.

## What the switch is, when it is made

In `agent_fleet/finance_agent/measures.py`:

- `EAC_METHODS` — from `get_args(EACMethod)` to the composed rows' ids.
- `EAC_FORMULA` — from a literal dict to the rows' transcriptions, with the `*` → `x` wire
  rendering that `test_the_wire_spelling_is_the_TRANSCRIPTION_with_one_declared_rendering`
  already pins. **Do not change the wire string**: a consumer fixture
  (`CompetingMeasures.test.tsx`) carries the `x` spelling.
- `EACMethod` stays. It is the value set declared **outside** the rows, and the seal that the two
  agree is only meaningful while neither is derived from the other.

And `fin_eac_calculation`'s refusal message keeps naming the methods, but from rows rather than
from the type.

## The one thing the rows still owe

`derived_from.clause` **names** each formula; it does not number a clause, and every row says
`citation: name-only`. These are public EVM formulations and the names are standard, but a
numbered reference needs the document in hand — and inventing one is exactly the defect §2a
exists to prevent: *a row that reads as provenance because it is precise.*

## Not in scope, and why the directory does not read as half-migrated

Five measure modules have no rows: `index_series`, `burn_series`, `funding_grid`,
`variance_driver_ranking`, `decomposition_policy`. **None of them has a slot that selects among
alternatives** — each verb uses one, and there is nothing to choose. They get rows when a second
implementation of one exists, which is the point at which "which method" becomes a question a
caller can ask. Stated in `policy/measures/README.md` so a reader counting six modules against
three rows does not conclude the migration stalled.
