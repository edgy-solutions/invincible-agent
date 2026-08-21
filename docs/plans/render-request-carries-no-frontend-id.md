---
id:         render-request-carries-no-frontend-id
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/presentation_agent/main.py, src/iagent/gateway.py
repo:       invincible-agent
summary:    The multi-UI promise is proven in tests and unreachable in production. `select_presentation` filters a caller's REGISTERED menu by payload satisfaction, but `RenderRequest` carries no `frontend_id`, so nothing can name the calling client. Small plumbing — a request-model field plus the cortex-bff caller threading it. ⚠️ DO NOT wire it with frontend_id=None: that resolves every caller to the default menu and turns every answer into a KNOWLEDGE_DOCUMENT.
---

# The render request cannot name its caller

`capability_registry.select_presentation` is built, tested (10 cases) and **called by
nothing**. It is the half of the ADR-0017 amendment that makes the multi-UI ruling real:
filter the caller's registered menu by `output_uri`, keep only what the payload satisfies,
rank by the published persona/domain affinities.

It cannot run, because `RenderRequest` (`agent_fleet/presentation_agent/main.py`) has
`raw_data`, `output_uri`, `domain` and a persona — and **no client identity.** The registry
is keyed by `frontend_id`; the render path has no `frontend_id` to key with.

## ⚠️ The trap, recorded so nobody walks into it

**Do NOT wire `select_presentation(frontend_id=None, ...)` to "turn it on".** A `None`
frontend resolves to the labelled default menu, whose only universal archetype is
`KNOWLEDGE_DOCUMENT` — so every answer in the system would render as prose. That is a
regression dressed as progress: the call site would look complete, the tests would still
pass (they exercise the function directly), and the symptom would be "charts stopped
appearing" with nothing pointing back here.

The `None` path is correct BEHAVIOUR for a genuinely unregistered caller — a curl, a script,
a UI mid-onboarding. It is the wrong DEFAULT for a caller that simply forgot to identify
itself, and those two look identical from inside the function.

## What the seam requires

1. `frontend_id` on `RenderRequest` (optional, so existing callers keep working).
2. cortex-bff threading the value it already knows — it holds the registration
   (`CORTEX_UI_FRONTEND_ID`) and calls `/render_ui`.
3. `main.py` preferring `select_presentation` when a `frontend_id` is present and falling
   back to today's global `lookup_capability` when it is absent.

Step 3's fallback is what makes this shippable incrementally: an identified caller gets
menu-scoped selection, an unidentified one keeps current behaviour, and nothing regresses
while the callers migrate.

## Why it matters beyond tidiness

Until this lands, the backend can choose an archetype the calling UI never registered. Today
that is harmless because one frontend exists and its menu matches the global table. **The day
a second surface registers a different menu — OpenDDIL, mobile, a voice client — the global
table starts answering on behalf of clients that never advertised those capabilities**, which
is the union-that-lies the amendment rejected as a design and would reintroduce as an
accident.

## Definition of done

A request from a registered frontend selects from THAT frontend's menu, witnessed by two
surfaces with different menus receiving different archetypes for the same `output_uri` — the
case `test_two_frontends_get_DIFFERENT_answers_for_the_same_output_uri` already proves in
isolation.
