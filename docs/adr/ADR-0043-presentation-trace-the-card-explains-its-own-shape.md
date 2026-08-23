# ADR-0043 — The presentation trace: a card carries the evidence for its own shape

**Status:** Proposed — decision recorded 2026-08-22, **build deferred behind demo-critical work** (Lane 1's verb and Lane 2's voice own the critical path; this is not on it). **Trigger:** the first post-demo capacity, OR the first time someone asks *"why did it show me that?"* about a card and the answer requires reading `presentation_agent` logs. Either fires it. Recorded as a trigger rather than a hope because a Proposed ADR with no wake condition is how a parking lot fills with documents nobody revisits.
**Date:** 2026-08-22
**Deciders:** Platform team
**Related:**
  - [ADR-0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) §2 — the card declares WHAT it is and `select_presentation` disposes; presentation became a genuine select-from-authorized-set resolution with its own provenance vocabulary. **This ADR surfaces the evidence that ruling produces**; it adds no decision to the selector.
  - [ADR-0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) §5 **and its 2026-08-21 amendment** — `presentation_source` is asserted, not assumed; then `presentation_source` alone proved insufficient and `selection_basis` joined it. That amendment is this ADR's direct parent: it established that the *discriminating* fields already exist and that a gate reading too few of them passes wrongly.
  - [ADR-0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) §6 — the renderer's refusal vocabulary is **published**, converting honest-empty from a rendering convention into a contract clause. The trace is where that vocabulary finally meets a human reader, which is arguably what it was published for.
  - [ADR-0017](ADR-0017-presentation-as-predicate.md) + its **2026-08-20 amendment** — capability registration is the transport, the component is the home. The trace reports the registration's identity (`frontend_id`, `registration_version`); it does not become a second registration surface.
  - [ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md) — the artifact is born complete and carries **provenance-at-creation**. The trace is provenance-at-creation, which is precisely the category ADR-0023 permits on the artifact; it is emphatically NOT generation-state, and §3 below is what keeps it on the right side of that line.
  - [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — cards carry SPO provenance from v1. This is the presentation half of the same promise.
  - [ADR-0038](ADR-0038-telemetry-as-provenance-projection-langfuse-standard.md) — provenance fields are projected **by their existing names, never renamed for the consumer**. §1 applies that rule verbatim to a UI consumer instead of an observability one.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — provenance is a **field, never a join**. The trace rides the answer; it is not a side table a UI could look up later.
  - [`principles/a-green-check-proves-only-its-scope.md`](../principles/a-green-check-proves-only-its-scope.md) — the general form of the same-observation-opposite-reasons defect §4 tabulates.
  - [`plans/render-request-carries-no-frontend-id.md`](../plans/render-request-carries-no-frontend-id.md) — closed by `e947069`, the union-menu inversion that made the failure silent. The receipt this ADR is written against.

## Context

**The routing half of a card's story is already told.** `cortex-ui`'s [`RoutingDecision.tsx`](../../../cortex-ui/src/components/HUD/RoutingDecision.tsx) surfaces three slots — **ABOUT** (`/resolve` subject + confidence), **ACTION** (`/classify_predicate` verb + confidence + `classify_called`), **HANDLED BY** (the verb edge's provider) — under a governing principle stated in the component's own docstring: *"surface what the pipeline did; never synthesize or soften."*

**The presentation half is not told at all**, and as of ADR-0042 it is the same *kind* of thing: an `output_uri` nominates, the caller's registered menu disposes, the payload's satisfaction of published contracts decides, affinity ranks. A card's shape is now a resolution with evidence — and the evidence stops at a log line.

### What the drafting conversation got wrong, verified against the code 2026-08-22

Three claims shaped the original packet. Two are wrong, and both errors ran in the direction of under-scoping. Recording them because the corrected version is the reason this ADR is cheap-but-not-free.

**1. "`select_presentation` builds the candidate evaluation and throws it away after the verdict."** It does not. It **returns** it. Every winner-path return carries `presentation_source`, `frontend_id`, `registration_version`, `archetype`, `selection_basis`, `candidates_considered`, `candidates_satisfied`, and `refusals` — the last being a list of `{archetype, reason}` naming what each losing candidate failed. The unrenderable path returns the same `refusals`. The evaluation is complete, structured, and already crossing the function boundary.

**2. "The envelope carries the verdict; the evidence trail died in engine-f's logs."** The first half is false: **the envelope carries nothing.** `presentation_source` does not occur anywhere in `src/` — zero hits. What crosses the wire today is `X-Presentation-Path`, a deliberately coarse five-value response header (`deterministic-document`, `archetype-hardened`, `fallback-designui`, `fallback-no-output-uri`, `declared-ungrounded`) whose strings are pinned as alert/canary match values. The gates that read `presentation_source` and `selection_basis` do so by **calling the selector directly in unit tests** ([`tests/planning/test_presentation_seam.py`](../../tests/planning/test_presentation_seam.py)), not by reading an answer.

So the precise location of the loss is one line, not a subsystem: in `render_ui`, `_sel_prov` is consumed by a single `logger.info` that reads **two of its eight keys**, and the dict then goes out of scope (`agent_fleet/presentation_agent/main.py`, the `_select_presentation` call site, read 2026-08-22). The data exists, fully formed, immediately before it is dropped.

**Why this correction changes the build rather than just the prose.** "One field added to the envelope" implies widening something that already crosses a seam. It does not cross. This is **presentation provenance crossing to the client for the first time**, which means a response-body field, a cortex-bff passthrough, and a HUD section — three hops, one of them cross-repo. Still small. But the original scoping omitted exactly the hop that costs the most, and a builder who inherited it would have discovered that at the worst moment.

**3. "Zero new computation."** Nearly true, and §6 rules on the one place it is not — which turns out to be the clause that keeps the panel honest.

## Decision

**The selector's evaluation reaches the client as a `presentation_trace` on the answer, and the HUD renders it beside the routing decision. It is evidence, never input.** Seven parts.

### 1. The trace IS what the selector already returns — verbatim, unrenamed

The `presentation_trace` is the provenance dict `select_presentation` returns today, carried out instead of logged away. **No field is renamed for the UI, and no field is computed for it.** This is ADR-0038's discipline pointed at a different consumer: a HUD panel and a decision record should say `selection_basis` in the same words, or the vocabulary forks and the grep stops working.

A consequence worth stating because it is the cheap part: the refusal strings the chart validator already produces — `"no rows"`, `"no numeric column"`, `"no categorical column"`, `"scatter requires 2 numeric columns (x and y)"` — are **already human-readable**. The demo beat *"CHART_WIDGET was a candidate and refused because rows carry no numeric column"* is a rendering of data that exists right now.

### 2. It rides the answer, not the header and not a side table

The trace goes in the response **body**, onto the artifact, as provenance-at-creation (ADR-0023's permitted category). Not the header: `X-Presentation-Path` stays exactly as it is — its five strings are canary match values and structured evidence does not belong in a header anyway. Not a side table: ADR-0035's field-never-a-join rule applies unchanged, and a trace you have to go *fetch* is one that stops being fetched.

### 3. The trace is EVIDENCE, never INPUT — binding

**Nothing downstream may branch on the trace.** Not the renderer, not the canvas, not a gate, not a future agent reading its own answer. The moment something branches on it, it is a second API with a second contract, and it will drift from the selector it was supposed to describe.

The distinction that keeps this enforceable: a gate asserts on `presentation_source`/`selection_basis` **as the selector returns them** (ADR-0042 §5 and its amendment, unchanged) — that is reading the selector's output, which is what gates have always done. What is forbidden is *behaviour keyed on the rendered trace object*: no component that changes shape because `refusals` is non-empty, no retry that fires on `candidates_satisfied == 0`. Read it, show it, do not steer by it.

This is also what keeps §2 honest against ADR-0023: provenance-at-creation that nothing consumes as state stays provenance. Provenance something branches on has become state wearing provenance's name.

### 4. It is built to discriminate five futures that currently look identical

The motivating defect is **same-observation-opposite-reasons**, and it is not hypothetical — the union-menu change (`e947069`) converted a loud failure into a silent one *while ADR-0042 was being written*. A `KNOWLEDGE_DOCUMENT` on screen is today ambiguous across five real states, all reachable in the current code:

| what happened | `presentation_source` | what disambiguates it |
|---|---|---|
| the caller's own menu had it, payload satisfied the contract | `registered` | `selection_basis == "output_uri+payload"` |
| the caller's menu was searched, `output_uri` matched nothing, payload absorbed by something else | `registered` | `selection_basis == "payload-only (…)"` — **the amendment's finding** |
| anonymous caller, chosen from the derived union of everyone's menus | `default-menu` | `candidates_considered` > 0 |
| anonymous caller, **empty registry** (post-restart) — the universal floor | `default-menu` | `presentation_menu` present, no candidates |
| the menu was searched and nothing could draw it | `unrenderable` | `refusals` names each miss |

**Note rows three and four share a `presentation_source` value.** `default-menu` does not distinguish *"chosen from the union"* from *"the registry is empty because nothing has re-registered since restart"* — two states with entirely different first questions. That is the §5 amendment's lesson recurring one field over, and it is a direct argument for carrying the whole dict rather than a chosen subset: **every time we have picked a subset of this provenance, the subset has proven too small.** Twice now.

(A sixth state exists and is deliberately outside the table: `presentation_source: "refused"` with `refusal_code: "live_view_requires_registration"` — ADR-0042 §9. It is unambiguous on its own and needs no discriminant.)

### 5. The HUD renders it in the routing-card idiom

A second section beside `RoutingDecision`, same visual grammar, same governing sentence — *surface what the pipeline did; never synthesize or soften.* The routing card's ABOUT/ACTION/HANDLED BY slots are the precedent; the presentation section's slots are **NOMINATED** (`output_uri` and what it matched), **SCOPED** (`frontend_id` + `registration_version` — whose menu), **DISPOSED** (satisfied/refused with named reasons), **CHOSEN** (archetype + `presentation_source` + `selection_basis`).

Expansion behaviour follows the existing card: collapsed by default, click to expand to the underlying URIs. The trace is for the person who asks; it is not a permanent wall of provenance.

### 6. "Satisfied" and "not evaluated" must not render as the same thing — the one additive change

**This is the clause that stops the panel from manufacturing confidence, and it is why "zero new computation" is not quite true.**

`_satisfies` dispatches by archetype and **only `CHART_WIDGET` has a typed contract today**. Every other archetype is returned as satisfied, by an explicit and correct migration policy: *"An archetype with no typed contract is treated as SATISFIED: migration is row-by-row, and refusing the nine not-yet-converted rows would make slice 4 a regression for every archetype except the one that happens to be finished."*

Correct for the selector. **Fatal for a display**, if rendered naively: the panel would show *"CHART_WIDGET refused — no numeric column; 4 others satisfied"* when those four were **never checked**. That is an unchecked default presented as a verdict — the laundering shape ADR-0041 §3 named, arriving through a UI instead of a query.

**Ruling:** the trace must distinguish `satisfied` from `not-evaluated (no typed contract)`, and the selector must supply that distinction rather than the UI inferring it. It is a small addition — `_satisfies` already knows which branch it took — and it is **not optional**: without it the panel's most confident-looking row is its least true one. The honest rendering is *"4 candidates carry no typed contract and were not evaluated"*, which doubles as visible pressure to finish the contract migration.

### 7. Scope: display of existing data, with §6's distinction added and one extension deferred

Everything else the panel could want, it already has. **One thing it does not, and it stays out of v1:** the satisfied-but-not-chosen candidates are only **counted** (`candidates_satisfied`), never named, and the affinity scores that ranked them are discarded inside the `max()` call. So *"which other archetypes could have drawn this, and why did this one win?"* is unanswerable from today's dict.

Deferred deliberately: it answers a **different question** (tie-break rationale) from the one this ADR is for (why this shape, why not the others), and it requires the selector to retain what ranking currently throws away. Named here so it is a known gap rather than a surprise.

## Non-goals

- **Not a debugging API.** It is the evidence a card carries about itself. If something needs to query traces across answers, that is a different artifact with a different lifetime.
- **Not persisted history.** The trace rides the answer and lives exactly as long as it does. No trace store, no retention policy, no "presentation audit" surface.
- **Not a replacement for the routing HUD.** Two sections, one idiom, different resolutions — the answer's SPO and the presentation's SPO are genuinely different decisions and collapsing them would hide which one went wrong.
- **Not LLM reasoning text.** Per the workshop plan's **Harmony-format rule** (gpt-oss emits reasoning in a channel separate from the final answer; reasoning-channel text never reaches a card, the canvas, or a demo-visible log), the trace carries the **selector's structured evaluation only**. The selector is deterministic Python; there is no model output in this path and none may be added to it. The trace is not a hole through which reasoning text reaches a card.

## Open at build time

1. **The cortex-bff hop.** The bff already records `X-Presentation-Path`; whether it passes the body trace through untouched or re-shapes it is undecided, and "untouched" should have to argue less.
2. **Anonymous callers.** The trace is *most* informative exactly when `presentation_source` is `default-menu` — i.e. for the caller that cannot register. The union-menu rationale already argues that presentation metadata is part of the answer's truth for script consumers, so the lean is send it; not ruled.
3. **Are the refusal strings a published vocabulary or free text?** ADR-0042 §6 says the vocabulary is published. Today's chart strings are short free-text literals in `capability_validator.py`. The moment they render to humans they become UI copy by accident, and copy that changes is a contract that changed silently.
4. **Does the trace belong on the artifact or only on the render response?** §2 says the answer; whether it survives into a canvas card's persisted form is an ADR-0028 question this does not settle.

## Indicators for revisiting

- **Something branches on the trace.** §3 is violated and the trace has become a second API — reopen before it grows a consumer.
- **The panel is built and nobody expands it.** Then the evidence people wanted was the two-field verdict, not the trail, and the HUD section should shrink to match.
- **A sixth ambiguous state appears** in the `presentation_source` table. The pattern of subsets proving too small (twice now) would be three times, and the answer stops being "carry more fields" and starts being "the vocabulary is wrong."
- **The contract migration finishes** — every archetype typed. §6's not-evaluated distinction becomes dead weight and should be retired rather than left to imply a distinction that no longer exists.
- **`select_presentation` grows a second caller** that needs the evaluation. Then the trace is not a display concern and this ADR is scoped one seam too narrowly.
