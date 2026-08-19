# Premise check — ADR-0017 "Hole 4", before commissioning the presentation-SPO enumeration

**2026-08-19.** Same check the M3 premise failed. **This one SURVIVES, with one correction.**

## Correction: Hole 4 is HALF closed, not open

The premise as stated: *"the capability publication carries the what-I-can-do (CHART_WIDGET
exists) but not the what-each-requires (`[{name, value: number}]`)."*

**The publication DOES carry a shape contract — field NAMES.** `FrontendCapability` in
`cortex-ui/src/registry/frontendCapabilities.ts`:

```ts
/** Field names this archetype expects to find in structured_data. */
expected_fields: string[];
```

```ts
{ archetype: "CHART_WIDGET", component: "ChartWidget",
  expected_fields: ["dataset_id", "metrics", "viz_type"], ... }
```

**What it does NOT carry is TYPES and CARDINALITY.** It publishes that a field named `metrics`
is expected; it cannot say `metrics` is an array of objects each with a numeric `value`. So the
`[{name, value: number}]` half of the contract is genuinely unpublished — the premise's
conclusion holds, its phrasing does not. `expected_fields` is the *names* half of Hole 4,
already closed; the *types/cardinality* half is open.

Note "Hole 4" appears nowhere in `ADR-0017-presentation-as-predicate.md` — it is conversational
shorthand. Anyone commissioning this should not expect to find it by grepping the ADR.

## The drift site is real, large, and self-documenting

`agent_fleet/presentation_agent/chart_normalizer.py` — **194 lines** whose purpose is to
reproduce, on the backend, a contract that lives in a React component. Its own docstring cites
the component's hardcoded keys and the charting library by name:

* line 8 — *"hardcodes `dataKey=\"name\"` and `dataKey=\"value\"` on its"*
* line 98 — *"a JSON-stringified array of `{\"name\": str, \"value\": number}`"*
* line 149 — *"because Recharts plots `value` on a numeric [axis]"*
* line 151 — records a REAL BUG this mirroring caused: `[{"name":"cage","value":"00000"}]`
  passed strings through untouched where numbers were required

That last line is the argument for the whole enumeration: **the hand-mirror already produced a
wrong render in production**, and the backend had to grow a 194-line normalizer to compensate
for a contract the frontend never published in machine-readable form.

## Verdict

**Commission it**, with the corrected premise: the enumeration's job is the TYPES and
CARDINALITY layer, not the names layer, and `expected_fields` is the existing seam to extend
rather than a gap to fill from scratch. Start the drift-site inventory at
`chart_normalizer.py`, which is the largest and best-documented instance.
