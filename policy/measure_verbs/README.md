# `policy/measure_verbs/` -- a measure is an overlay row

A row here declares a finance MEASURE: the verb a user can ask for, the pure module that computes
it, the series it returns and the policy it ships under. The proposal is
[`docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`](../../docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md)
(Part 1); the loader is `agent_fleet/finance_agent/measure_verbs.py`.

**The platform seeds no measure.** The seven built-in finance verbs are code (`VERBS` in
`agent_fleet/finance_agent/main.py`); this directory exists so the seed layer of ADR-0036 has a
place, and so the image carries the path. Its row `fin_funding_status.yaml` is also a
**source-only row** for a built-in, besides its listing: with `FIN_DATASET_URN` set, funding keeps reading the notional
seed (`source: seed`, `reason: contract carries no funding lines yet`, `ratified_by: owner`)
until the EV contract carries funding lines (ruled 2026-11-09). A row naming a built-in may carry
only `measure_id`, `source`, `reason`, `ratified_by` and, together, `name` and `description`;
anything else is refused at load. `source` stays required on every such row (an overlay row replaces
the seed row whole, so a row that left it out would move funding off `seed`). `name` and
`description` list the built-in in the askable list (each a non-empty string, both or neither; a row
with no `name` is source-only and is not listed). `cells` and `synonyms` stay refused on a built-in's
row: it is not cell-gated, its listed cells are the engine's own `DOMAINS`, and its listed phrasings
are its routing synonyms (`VERBS`), so every phrasing offered routes to its own verb. This directory
carries one row per built-in. Under
the flag every other measure reads the asset (`source: asset` is the default). A deployment adds
rows in an overlay:

    MEASURE_VERB_OVERLAY_DIRS=/app/policy/overlays/sample/measure_verbs

(`os.pathsep`-separated, default empty). `MEASURE_VERB_POLICY_DIR` moves the seed. An overlay row
replaces a row of the same `measure_id` whole; `deleted: true` tombstones one. A malformed row set
refuses to boot the engine, naming the file.

A row cannot loosen program visibility: every finance measure is `can_view_program(program_id)`,
deny by default, and a `policy.visibility` key is refused at load.
