---
id:         render-request-carries-no-frontend-id
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/presentation_agent/main.py, src/iagent/gateway.py
repo:       invincible-agent
summary:    ACCEPTANCE GREW 2026-08-20: the seam and the retirement of agent_fleet/presentation_agent/capabilities.py are ONE change, because the seam is what makes the registered menu AUTHORITATIVE. The multi-UI promise is proven in tests and unreachable in production. `select_presentation` filters a caller's REGISTERED menu by payload satisfaction, but `RenderRequest` carries no `frontend_id`, so nothing can name the calling client. Small plumbing — a request-model field plus the cortex-bff caller threading it. ⚠️ DO NOT wire it with frontend_id=None: that resolves every caller to the default menu and turns every answer into a KNOWLEDGE_DOCUMENT.
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

## The backend copy retires WITH this seam, not before

`agent_fleet/presentation_agent/capabilities.py` is now PROVABLY REDUNDANT: as of `f45a7b9`
all 14 capability rows are derived from component contract exports, so every row the backend
copy holds is one the UI now publishes from its own components.

**It is still not deletable on its own.** Deleting it while nothing threads the caller's
identity would leave the decision reading a registry that CANNOT YET BE SCOPED TO WHO IS
ASKING — the global table would be gone and the per-caller menu would be unreachable, so the
render path would have no capability source at all. The deletion and the seam are one change:
the menu becomes authoritative and its shadow retires in the same commit.

This is the same ordering rule slice 2c ran on -- do not remove the compensation before the
thing that replaces it exists. There, the validator had to cover the normalizer's legitimate
job first; here, `select_presentation` has to be REACHABLE first.

## Definition of done

Three things in one commit:

1. **`frontend_id` threaded** — optional on `RenderRequest`, supplied by cortex-bff, which
   already holds `CORTEX_UI_FRONTEND_ID` because it performs the registration.
2. **`select_presentation` wired live** — preferred when a `frontend_id` is present, with
   today's global lookup as the fallback while callers migrate. That fallback is what makes
   this shippable incrementally rather than as a flag day.
3. **`capabilities.py` deleted** — its rows are derived on the UI side and its consumers move
   to the registry.

Witnessed by two surfaces with different menus receiving different archetypes for the same
`output_uri` — the case `test_two_frontends_get_DIFFERENT_answers_for_the_same_output_uri`
already proves in isolation and cannot prove in production until step 1 lands.
