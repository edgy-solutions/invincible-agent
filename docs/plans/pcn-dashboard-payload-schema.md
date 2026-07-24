# Dashboard payload schema — the `INSTANCES_BY_PROPERTY` archetype (pre-work for the dashboard window)

**Read this BEFORE the dashboard session opens.** The schema below is the ONE thing that must be
designed up front, because it is the contract nobody was assigned: the interface between the GENERIC
renderer (cortex-ui, knows the archetype shape) and the HAND-FED feeder (backend, knows pcn today).
Designed under demo pressure it becomes an accident `rendersAs` later has to contort to match. Designed
now as the PROJECTION of what `rendersAs` will declare, it makes the M2 feeder-swap and the M3
declaration layer mechanical. See [[feedback_graph_derives_whole_stack]] + `pcn-extraction-sort.md`.

## The principle: the payload is the hand-assembled `rendersAs` declaration

The generic archetype is "a table of INSTANCES of class C in domain D, FILTERED by property P" — the pcn
"parts by disposition state" dashboard is its FIRST instance, not a feature. Everything pcn about it
lives in the payload's VALUES, never the renderer. Each field of the payload corresponds to a triple
`rendersAs` will someday declare, so the payload is that declaration, hand-assembled:

| payload field | future `rendersAs` triple (M3) | today's feeder source |
|---|---|---|
| `target.{domain,class,filter_property}` | the class + a `rendersAs:filterableBy` property | hand-set (SUSTAINMENT / pcn:Component / pcn:dispositionState) |
| `columns[]` | `pcn:Component rendersAs:tableColumns (…)` — the class declares its columns | hand-set from the known `/pcn_parts_by_state` shape |
| `row_identity` | `rendersAs:rowIdentity` (which column is the stable key) | the instance IRI |
| `state_vocabulary` | the `filter_property`'s value enumeration | hand-set (the 4 dispositions) |
| `rows[]` | — (always data, from `/instances`) | hand-assembled from `/pcn_parts_by_state` now |

## Schema

```jsonc
{
  "archetype": "INSTANCES_BY_PROPERTY",        // cortex-ui renders THIS shape; adds a new archetype
                                               // to the existing GROUPED_REVIEW / WORKFLOW_OBSERVATION
                                               // set. UI-COMPONENT-NOT-FOUND if the renderer lacks it.
  "title": "Parts by disposition state",       // display only

  // WHAT to query — the future /instances params (generic endpoint, Pile-1 parameterize-and-promote).
  // The feeder ignores this today and fills rows itself; /instances consumes it tomorrow. Same shape.
  "target": {
    "domain": "SUSTAINMENT",
    "class": "pcn:Component",
    "filter_property": "pcn:dispositionState",
    "filter_value": "dispatchQualification"    // the selected state; drives the query + the active tab
  },

  // COLUMNS — the class's declared table columns (rendersAs: class -> columns). Each maps a property
  // to a display key/label. The renderer draws these headers; it knows nothing of "parts" or "MPN".
  "columns": [
    { "key": "instance", "label": "Part",        "from": "row_identity" },
    { "key": "state",    "label": "State",        "from": "pcn:dispositionState" },
    { "key": "ref",      "label": "Resolution",   "from": "pcn:dispositionRef" },
    { "key": "ruleset",  "label": "Policy",       "from": "pcn:proposedByRuleset" }
  ],

  // ROW IDENTITY — which column is the stable key (selection, deep-link, "act on this row"). It is the
  // instance IRI; the display value is its MPN local-name, but identity is the IRI.
  "row_identity": { "key": "instance", "iri": true, "display_from_local_name": true },

  // STATE VOCABULARY — the filter property's value set, for the filter tabs/dropdown. Enumerated now;
  // derived from the ontology (the property's range / registered dispositions) once rendersAs lands.
  "state_vocabulary": ["dispatchQualification", "dispatchLTB", "dispatchAltSourcing", "archive"],

  // ROWS — the data. Hand-assembled by the feeder from /pcn_parts_by_state TODAY; returned by the
  // generic /instances endpoint after M2. Keys match columns[].key.
  "rows": [
    { "instance": "http://internal/components/NSR01L30NXT5G",
      "state": "dispatchQualification",
      "ref": "IPCN25300X:NSR01L30NXT5G",
      "ruleset": "rules@2915ddb229e4" }
  ]
}
```

## The generic / feeder split (so M2 touches the feeder ONLY)

- **RENDERER (cortex-ui, GENERIC, built this week):** consumes `INSTANCES_BY_PROPERTY` — draws
  `columns` as headers, `rows` as cells, `state_vocabulary` as filter tabs, uses `row_identity` for
  selection/nav. ZERO pcn knowledge, zero hard-coded column names (the `/pcn_parts_by_state` UI mistake
  the sort flags). A different domain's instances-by-property table reuses it with a different payload.
- **FEEDER (backend, SPECIFIC, temporary):** assembles the payload for THIS dashboard — sets `target`,
  `columns`, `state_vocabulary` (hand-set), and fills `rows` from `POST /pcn_parts_by_state`
  (`{part, ref, ruleset}` per the existing `build_parts_by_state_query`). This is the ONLY pcn-aware
  piece; M2 replaces it with `/instances` + `rendersAs`-derived columns, and the renderer does not move.

## Acceptance for the dashboard window
- Renderer takes ONLY the archetype payload; give it a NON-pcn payload (any class/columns) and it draws
  a correct table → proves generic-by-construction (not pcn-shaped in disguise).
- The feeder is the single grep-able pcn surface; the M2 deletion test covers it.
- The second view that wants an instances-by-property table triggers the presentation
  parameterize-and-promote wake (`pcn-extraction-sort.md`) — do NOT copy the feeder; promote it.
