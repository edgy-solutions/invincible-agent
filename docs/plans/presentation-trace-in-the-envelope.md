---
id:         presentation-trace-in-the-envelope
status:     parked
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/presentation_agent/main.py, agent_fleet/presentation_agent/capability_registry.py
repo:       invincible-agent
trigger:    first post-demo capacity, OR the first time someone asks "why did it show me that?" about a card and answering requires reading presentation_agent logs
summary:    RULED in ADR-0043 (2026-08-22), build deferred. select_presentation already RETURNS its full evaluation (refusals with named reasons, candidates_considered/satisfied, selection_basis, frontend_id, registration_version) — render_ui drops it after logging TWO of eight keys. Carry it out as `presentation_trace` on the answer body; HUD renders it beside RoutingDecision in the ABOUT/ACTION idiom. NOT the one-field edit the design conversation assumed: presentation provenance does not cross to the client at all today (zero `presentation_source` in src/; only the coarse X-Presentation-Path header), so this is three hops incl. cortex-bff + cortex-ui. One additive change is MANDATORY per §6 — `_satisfies` only types CHART_WIDGET, so "satisfied" and "never evaluated" must not render alike or the panel's most confident row is its least true one.
---

# The presentation trace does not leave the selector

**Ruled, not open.** The decisions live in
[ADR-0043](../adr/ADR-0043-presentation-trace-the-card-explains-its-own-shape.md); this packet
exists so the board routes to them, and so the next person who half-remembers the conversation
greps and finds a document instead of a memory.

## What is true today (read 2026-08-22)

`capability_registry.select_presentation` returns a complete, structured evaluation —
`presentation_source`, `frontend_id`, `registration_version`, `archetype`, `selection_basis`,
`candidates_considered`, `candidates_satisfied`, `refusals` (each `{archetype, reason}`).

`main.py`'s `render_ui` consumes it with **one `logger.info` reading two keys**, then lets it go
out of scope. Nothing downstream ever sees it. `presentation_source` occurs **zero times** in
`src/`; the only presentation provenance on the wire is `X-Presentation-Path`, five coarse strings
pinned as alert/canary values.

## The build, in the order the ADR implies

1. **Return it.** `render_ui` carries `_sel_prov` into the response body as `presentation_trace`.
   Unrenamed (ADR-0038 discipline). The header is untouched.
2. **The §6 distinction — do this one WITH step 1, not after.** `_satisfies` dispatches by
   archetype and only `CHART_WIDGET` has a typed contract; everything else is *treated as*
   satisfied by an explicit migration policy. The selector must say which candidates were
   **not evaluated** so the panel cannot render an unchecked default as a verdict.
3. **cortex-bff passthrough.** Open whether it forwards untouched or re-shapes; untouched should
   have to argue less.
4. **The HUD section.** `cortex-ui`, beside `RoutingDecision`, same idiom and same governing
   sentence — *surface what the pipeline did; never synthesize or soften*. Slots: NOMINATED /
   SCOPED / DISPOSED / CHOSEN.

## The trap

**Nothing may branch on the trace** (ADR-0043 §3). A gate asserting on `presentation_source` /
`selection_basis` *as the selector returns them* is unchanged and fine — that is reading the
selector. Behaviour keyed on the rendered trace object is a second API, and it will drift from
the thing it describes.

## Why it is parked rather than open

Not on the demo's critical path — Lane 1's verb and Lane 2's voice are. It is small, it touches
files no lane holds, and it is the demo's best differentiator beat once it exists (*every card can
show you why it looks the way it does*). The demo foreshadows it with the two fields already
gating; this is the week-after work that makes them visible.
