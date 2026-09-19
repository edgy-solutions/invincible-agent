# `policy/measures/` — method rows (ADR-0053 §2)

One file, one method, keyed by `method_id`. Shaped like `policy/graphs/`, composed by
`iagent_mesh.declarations.compose_rows`, and loaded by
`agent_fleet/finance_agent/method_registry.py`.

**A module on disk with no row here is invisible.** Inherited verbatim from
`policy/graphs/fin_program_brief.yaml`, and it is what makes ADR-0053 §3's refusals structural
rather than disciplinary.

## Scope, stated so the directory does not read as complete

These three rows cover **the EAC methods** — the one slot in this engine whose vocabulary is a
user's choice among ratified algorithms, and the verb ADR-0053 §2a was written from. The other
five measure modules (`index_series`, `burn_series`, `funding_grid`, `variance_driver_ranking`,
`decomposition_policy`) have **no rows yet** and no slot that selects among alternatives: each
verb uses one, and there is nothing to choose. They get rows when a second implementation of one
of them exists, which is the point at which "which method" becomes a question a caller can ask.

Recorded here rather than left to a reader counting six modules against three rows and
concluding the registry is half-migrated.

## The transcription, and what its citation can and cannot claim

§2a requires every row to carry an **absolute transcription seal** against the clause its
provenance cites. Each row carries `derived_from.transcription` — the formula written as the
standard states it — and `tests/finance/test_the_method_registry_rows.py` **parses that string
and evaluates it**, asserting the module computes the same number.

That is the seal §2a asks for: it is not a string compared against another copy of itself, which
would pass while both were wrong. It is the transcription **run** against the code.

⚠ **`derived_from.clause` NAMES the formula; it does not number a clause.** These are public EVM
formulations and the names are standard, but a numbered clause reference would need the document
in hand, and **inventing a number is exactly the defect §2a exists to prevent** — a row that
reads as provenance because it is precise. `citation: name-only` says so on every row rather
than leaving the absence to look like an oversight or, worse, like a verified reference.

Filling those in against the document is the one thing these rows still owe.

## Adding a fourth method

1. A module with a manifest (`VERSION`, no engine imports) — ADR-0053 §1 and §3.
2. A row here, with its transcription.
3. The value in `EACMethod` in `agent_fleet/finance_agent/entities.py`.

**Step 3 is not redundant.** The seal asserts the row set and the `Literal` agree, and the
`Literal` is declared **outside** these rows on purpose: a vocabulary enumerated from the rows
it is checking would be complete by construction, and a row added without a type value — or a
type value with no row — would both pass. Two independent declarations that must match is the
only arrangement in which either can be wrong.
