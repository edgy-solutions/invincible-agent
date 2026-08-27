# Trigger the seed by hand — tonight, while the routing gap is someone else's morning

**Date:** 2026-08-26 · **Lane:** 1 · **Why:** the phrase does not route yet (see
`finding-a-catalog-entry-is-not-a-registration.md`) and there is no button either. The ROUTE
works and is auth-gated. So drive it directly and stop waiting on the trigger.

**This separates two questions that are currently tangled:**

| question | answerable tonight? |
|---|---|
| does the canvas COMPOSE and PERSIST | **yes** — that is step 3's real content |
| does the PHRASE route to the seeder | no, and it is a different gap in a different lane |

---

## The call

Open cortex, log in as the demo viewer, open devtools → Console, paste:

```js
(async () => {
  const base = (window.__RUNTIME_CONFIG__ || {}).VITE_API_URL;
  const key   = Object.keys(sessionStorage).find(k => k.startsWith("oidc.user:"));
  const token = key ? JSON.parse(sessionStorage.getItem(key)).access_token : null;
  console.log("base:", base, "| token present:", !!token);
  if (!base || !token) return console.error("not logged in, or runtime config missing");

  const t0 = Date.now();
  const r  = await fetch(base + "/canvas/seed", {
    method:  "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body:    JSON.stringify({ canvas_type: "portfolio_planning" }),
  });
  const body = await r.json().catch(() => null);
  console.log("status:", r.status,
              "| minutes:", ((Date.now() - t0) / 60000).toFixed(1));
  console.log("artifact_ids (SLOT ORDER):", body && body.artifact_ids);
})();
```

Both values are discovered rather than hardcoded — `window.__RUNTIME_CONFIG__` is how the
container injects the API URL at runtime, and the OIDC key is scanned for rather than rebuilt
from realm + client id, so this keeps working if either changes.

**It will sit there for ~17 minutes.** Five governed asks, run sequentially on purpose. That is
the measured figure (5/5 in 17.7 min), not a guess.

---

## What you get, and what you do NOT

**You get:** five governed asks through the real funnel, five artifacts, and a **slot-ordered**
id list. That is the substantive part of step 3 and all of the wall clock.

**You do not get auto-composition.** `seedPortfolioCanvasFromServer()` composes the canvas by
calling the zustand store, and no store is exposed on `window` — I checked, there is no debug
global. So the console cannot place the cards.

**Compose by hand, in the returned order.** The response IS the slot order; drag the five onto a
canvas in exactly that sequence and the anchor lands first. Then **reload** — persistence is the
claim and only a reload proves it. Persistence runs through `/me/canvases` and is completely
unaffected by how the canvas got built, so a hand-composed canvas tests it just as well.

What a hand-composed canvas does NOT test is the seeder's own placement. That is fair to leave
open: it is the half cortex has not wired yet.

---

## If the request dies before it returns — the cards may still land

A 17-minute HTTP request has to survive every hop between the browser and the BFF. If an ingress
or proxy timeout cuts it, **the console shows an error and the asks keep running server-side.**
The artifacts still land and still arrive over Electric; only the id list is lost.

So: if the call errors, **do not assume the seed failed.** Watch the ANSWERS rail — five new
planning answers appearing over the following minutes means it worked and only the response was
lost. Recover the slot order from the questions themselves:

| slot | question | expected card |
|---|---|---|
| 0 | what is scheduled by initiative and phase | INTERVAL_TIMELINE ← anchor |
| 1 | what does spend look like per period | PERIOD_SERIES |
| 2 | which sites are overloaded | THRESHOLD_GRID |
| 3 | where is funding short by initiative | SHORTFALL_GRID |
| 4 | capability maturity by site versus target | MATRIX_GRID |

**And if it does get cut, that is a finding worth keeping** — it would break the wired-up version
identically, because the client calls the same route the same way. A feature whose happy path is
17 minutes long has an edge-timeout question nobody has answered yet.

---

## ⚠️ CHECK THIS BEFORE TRUSTING THE BOARD — a manual seed has the same silent hazard

`/canvas/seed` strips nulls, because the client's `for (const id of artifactIds)` cannot place a
hole. That re-shifts the slots the implementation deliberately aligned. **A partial seed composes
a board that is wrong and plausible:** every card real, every card rendering, nothing erroring,
and the cost curve sitting in the anchor slot.

Triggering by hand changes nothing about this — same route, same strip.

```bash
kubectl --context edge logs -n sandbox deploy/iagent-cortex-bff --tail=300 | grep -i "PARTIAL seed"
```

- **no output** → `seeded == total`, slot order is trustworthy
- **a line** → the board is mis-slotted; **draw no conclusion from which card is in which slot**,
  including "the anchor renders the timeline", which is a step-3 acceptance criterion

A quicker read from the console result: `artifact_ids.length === 5` and no nulls means a complete
seed. Fewer than five means it was compacted and the order is not what the template intends.

---

## While it runs

Steps 1, 2 and 4 are unaffected and take minutes. Run them in another tab rather than watching a
console spinner for a quarter of an hour.
