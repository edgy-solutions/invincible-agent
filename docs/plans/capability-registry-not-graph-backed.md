---
id:         capability-registry-not-graph-backed
status:     open
owner:      agent
blocked-on:
closed-by:
diverges-from: ADR-0017-presentation-as-predicate
code-site:  agent_fleet/presentation_agent/capability_registry.py, src/iagent/gateway.py, agent_fleet/utils/mesh_registration.py
repo:       invincible-agent
summary:    ⚠️ LIVE DEFECT, found by the 2026-08-21 redeploy. The frontend capability registry is a MODULE-LOCAL DICT, and registration and selection run in DIFFERENT PODS — `/register_frontend_capabilities` is served by cortex-bff, `/render_ui` by presentation-agent. Registration can therefore NEVER reach the selector: every caller is anonymous from engine-f's view, the union is always empty, and every answer falls to the labelled floor. CHART_WIDGET is currently unselectable in production for anyone. ADR-0017's own mechanism (rendersAs triples in the shared Predicate collection, read via /search_predicates) was always the design; the in-memory dict was scaffolding that was never written down as a divergence.
---

# The registry cannot be read where it is written

**Witnessed 2026-08-21**, first time the real topology ran with anyone watching. Engine F's
own log, with a `frontend_id` supplied and the seam executing correctly:

```
render_ui: menu-scoped selection frontend_id=cortex-ui-desktop
           source=default-menu  basis=None  -> no frontend has registered — union is empty
```

## The mechanism

| endpoint | workload | image |
|---|---|---|
| `/register_frontend_capabilities` -> `capability_registry.register()` | **cortex-bff** | `cortex-bff:latest` |
| `/render_ui` -> `capability_registry.select_presentation()` | **presentation-agent** | `presentation-agent:latest` |

`_REGISTRY` is a module-level dict behind a `threading.Lock`. Process-local. Two pods, two
processes, two registries — the writer's is populated and never read; the reader's is empty
and never written.

## Why three reviews missed it

1. **An untested topology assumption.** 71 tests exercise the registry IN ONE PROCESS. They
   prove the logic and say nothing about where it runs. A passing suite actively discouraged
   the question — [[a-green-check-proves-only-its-scope]] at arc scale.
2. **An acceptance that named artifacts, not the deployed claim.** The arc closed on
   contracts derived, seam threaded, tests green, files deleted — all real, none of them the
   claim, which was "menu-scoped selection is live."
3. **A known divergence that never became an indexed item.** Slice 2b's docstring flagged the
   registry as runtime state needing a runbook line. That flag described EPHEMERALITY ("empties
   on restart") when the truth was REACHABILITY ("never populated across the boundary"). It
   lived in a module docstring, which is where this project's own doctrine says claims go to
   be forgotten. **This packet is the line that should have existed.**

Also worth recording: the seam packet pre-recorded the `frontend_id=None` trap in detail. The
actual regression came through a door nobody listed — the guard was written for the wrong
failure.

## The repair: converge with the ADR that named it

`register_presentation_to_mesh` (`agent_fleet/utils/mesh_registration.py:394`) already emits
`(subject_uri, mesh:rendersAs, object_uri)` triples into the shared Weaviate `Predicate`
collection, retrieved by `/search_predicates`. Its own docstring states the intent: *"Engine F
(and any other component that knows how to render a shape) advertises its capabilities through
this helper."* That is graph state — it crosses pods because it is not in any pod.

The in-memory dict was scaffolding. Converging removes the divergence AND the defect in one
move, rather than bolting a shared store beside an ADR that already specified one.

Open design questions for the build, not assumed:
* how the triple carries `frontend_id` (a discriminator the current helper has no field for);
* how it carries the TYPED CONTRACT (the helper takes `expected_fields` — names only, which is
  the exact gap the contract work closed);
* freshness/staleness — a graph row outlives a pod, so re-registration must overwrite rather
  than accumulate, and the registration version needs to reach the decision.

## Definition of done — a DEPLOYED witness, not a green suite

**The rule this packet exists to enforce:** an arc whose claim is about deployed behaviour
closes on a deployed witness. Item 1 waited for the live UI witness; this arc did not, because
the suite was thorough enough to feel like enough — thoroughness on one axis hiding absence on
another.

So: **a TWO-PROCESS witness.** cortex-ui registers through cortex-bff; a `/render_ui` call to
presentation-agent selects from that menu and reports `presentation_source: "registered"` with
a `selection_basis` of `output_uri+payload`. Both fields, per ADR-0042 §5 — `presentation_source`
alone says a menu was consulted, not that your output type was found on it.
