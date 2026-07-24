# PCN dashboard — the INSTANCES_BY_PROPERTY archetype (exhibit)

Built 2026-07-24. The last build window: a GENERIC "instances of a class, filtered by one property" table,
whose FIRST instance is the PCN parts-by-disposition-state dashboard. The whole point (schema doc + the
graph-derives-whole-stack ruling) is that the dashboard is an *instance of an archetype*, not a bespoke PCN
component — everything pcn lives in the payload values, nothing in the renderer.

## The generic / feeder split (so M2 touches the feeder ONLY)
- **RENDERER (cortex-ui, generic):** `src/components/InstancesByProperty/InstancesByPropertyView.tsx`
  (+ `types.ts`), registered in `SemanticInterpreter` (switch case + `isFullWidth` + `frontendCapabilities`).
  Draws `columns` as headers, `rows` as cells, `state_vocabulary` as filter tabs (active = `target.filter_value`),
  `row_identity` to shorten an IRI to its local name. It routes on the `archetype` string, so one case covers
  both the center answer pane and the pinned canvas card.
- **FEEDER (cortex-bff, the single pcn-aware surface):** `GET /pcn/parts_by_state?state=<disposition>` in
  `gateway.py` — pulls rows from engine-o `/pcn_parts_by_state` and wraps them in the INSTANCES_BY_PROPERTY
  payload, hand-setting `target/columns/state_vocabulary` (the pcn-specific values). The ONE grep-able pcn
  presentation surface; the M2 deletion test covers it, and M2 swaps it for a generic `/instances` +
  `rendersAs`-derived columns without moving the renderer.

## Acceptance — GENERIC by construction (not pcn-shaped in disguise)
The design rule: give the renderer a NON-pcn payload and it must draw a correct table. Proven three ways:
1. **Renderer code is domain-free.** `grep -iE 'pcn|disposition|mpn|qualification|sustainment|affected'`
   over `InstancesByPropertyView.tsx` (excluding the docstring) → **zero matches**. The genericity is
   structural — if someone later hardcodes a column name like "MPN", this check goes RED.
2. **Two distinct-domain payloads over ONE renderer** (mock scenarios, the repo's established fixture path):
   - `@instances` → PCN parts by `pcn:dispositionState` (`pcn:Component`, mirrors the feeder output).
   - `@instances-generic` → datasets by `idp:domain` (`idp:Dataset`, `DATA_ENGINEERING` — no pcn anywhere).
   Both build a `{components:[{archetype:"INSTANCES_BY_PROPERTY", …}]}` and render through the same switch
   case. The non-pcn one is the generic proof.
3. **Types are generic.** `InstancesByPropertyPayload` names `columns/rows/state_vocabulary/target/
   row_identity` — no pcn field. `tsc --noEmit` clean.

## Live feeder seal (composed path, live inputs)
The pre-seeded state from the loop + BFF windows means `/pcn_parts_by_state{dispatchQualification}` returns
real rows across two notices (IPCN25300X + PCNBFFSEAL01). The feeder wraps them into the archetype payload:
[SEAL RESULT APPENDED BELOW]

## Payload contract
`docs/plans/pcn-dashboard-payload-schema.md` — each field is the hand-assembled projection of a `rendersAs`
triple M3 will declare, so the payload IS that declaration hand-assembled. Renderer consumes the archetype
shape; feeder assembles it; M3 makes the assembly declarative from the graph.

## Follow-ups filed (not M1)
- **Parameterize-and-promote wake:** the SECOND view that wants an instances-by-property table must PROMOTE
  the feeder to a generic `/instances` (per `pcn-extraction-sort.md`), not copy it. Do not add a second
  bespoke feeder.
- **Interactive filter tabs:** the widget accepts an optional `onSelectFilter` (re-query for a tab's value);
  wired only when a host passes it. The live filter-switch round-trip (tab → re-fetch feeder) is a small
  follow-up; the tabs render display-only until then.
- **Feeder → canvas live path:** the feeder returns the payload; the pipeline delivering it as a
  `final_payload` component to the canvas is the same integration as any archetype (a routed answer), not
  built here — the mock scenario is the renderer's fixture, per repo convention.
