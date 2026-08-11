---
id:         cortex-ui-transport-idiom
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  cortex-ui/src/api/client.ts
repo:       cortex-ui
summary:    DESIGN READ (2026-08-11) for repo 5 of 5. cortex-ui is a static SPA behind nginx — there is NO server-side origin, so the "unminted caller" frame does not apply and the sweep population is browser call sites only. One confirmed defect: NodeInspector sends no token AND bypasses runtime config, two defects on one line where the outer masks the inner.
---

# cortex-ui — what a call site is, and what "minted" means in a browser

**Read before sweeping, as instructed**, because the method that carried the platform, dag-tools
and doc-tools does not transfer here. It turns out it does not transfer for a *stronger* reason
than "JS is harder to grep": **the category the sweep counts does not exist in this repo.** That
is the first thing to say, because it determines what the sweep is even counting.

---

## THE OPENING DISTINCTION — browser-originated vs server-originated

The transport-auth question is: *does this call carry an identity, and whose?* It has two
completely different answers depending on where the call originates, and conflating them
produces a large number of rows that look like findings and are not.

| origin | identity it carries | is "unminted" a defect? |
|---|---|---|
| **browser** | the **human's** OIDC access token, verified at the gateway | **No — that is the design.** A browser call carrying the user's bearer is *correctly* identified. |
| **server-side** (route handler, server action, SSR, middleware, build step) | the **service's** identity, or none | **Yes** — this is the same class as `review_composer`: a call acting on its own behalf with nothing attached. |

So the sweep's real population is **server-side call sites**. Browser call sites are out of scope
**by category, not by absence of a credential** — and that distinction has to be stated in the
frame, not the margin, because otherwise every `fetch()` in a React component reads as a row.

### And in this repo the server-side population is EMPTY BY CONSTRUCTION

Not "empty because I looked and found none" — **empty because there is no server.** Four
independent facts, each read:

1. **`package.json`** — no `next`, no server framework. `"build": "tsc && vite build"`. Vite
   emits static JS/CSS/HTML.
2. **`Dockerfile`** — two stages. Stage 1 builds with node; **stage 2 is `nginx:1.25-alpine`**
   and copies only `/app/dist`. **Node is not in the runtime image.** The `"start": "serve dist -s"`
   script exists but is a local convenience; the image runs `nginx -g "daemon off;"`.
3. **`nginx.conf`** — read in full. `try_files`, `expires`, `add_header`. **There is no
   `proxy_pass` anywhere.** The nginx pod serves files and makes zero outbound calls.
4. **`docker-entrypoint.sh`** — the only runtime "logic" writes `window.__RUNTIME_CONFIG__` into
   `config.js` and execs nginx. It reads env; it calls nothing.

**cortex-ui has no server-side origin, therefore no unminted-caller population, therefore repo 5
cannot produce a row of the kind repos 1–4 produced.** That is a real finding, not an absence of
one, and it is the answer to "does the method transfer": *the method does not transfer because
the phenomenon is not present.*

### Which makes the honest question a different one

Restating what cortex-ui's relevant question actually is:

> **Does it forward the user's token, and is anything calling on its own behalf?**

Two different failure modes, and they are not the same severity:

- **A browser call that loses the user's token** degrades to unauthenticated. Against a *gated*
  route that is a **broken feature** — a 401, a dead panel. Against an *ungated* route it is an
  unauthenticated read.
- **A server-side call with no identity** is the `review_composer` class — an actor with no name.
  **None exist here.**

---

## Q4 FIRST — the axis-2 endpoint enumeration (it bounds everything else)

Run first, as ruled, because if cortex-ui only talks to cortex-bff the idiom problem shrinks to a
single wrapper read. **It very nearly does.**

Every configured endpoint, from `src/config.ts` — the one module that resolves runtime config:

| config key | resolves to | is it a platform service? |
|---|---|---|
| `VITE_API_URL` | cortex-bff | **yes — the only one** |
| `VITE_KEYCLOAK_REALM_URL` | Keycloak | no — it is the **issuer**; oidc-client-ts talks to it to *obtain* the token |
| `VITE_KEYCLOAK_CLIENT_ID` | — | not an endpoint |
| `VITE_NO_AUTH` | — | not an endpoint (see the flag note below) |
| `VITE_ELECTRIC_URL` | **dead** | declared, defaulted, and **not used by the code that names it** — see below |

**One platform endpoint. Everything that matters goes to cortex-bff.** The sweep is bounded from
above by a four-line config module, and "did I grep enough call sites?" does not arise — the same
property that made doc-tools trustworthy at one row.

### The Electric entry is a live example of config drift

`VITE_ELECTRIC_URL` is declared in `RuntimeConfig`, defaulted to `http://localhost:3000`, injected
by `docker-entrypoint.sh` — and `src/lib/electric.ts:184-190` deliberately does **not** use it:

```
// Use the cortex-bff base URL (VITE_API_URL) + /electric/shape.
// The legacy VITE_ELECTRIC_URL pointed straight at Electric (which
// had no user_id filter, hence the over-sharing the proxy fixes).
const base = config.VITE_API_URL;
```

The fix was made correctly — the subscription now goes through cortex-bff's proxy so the WHERE
clause is server-injected from the verified JWT `sub` (`gateway.py:4469 electric_shape_proxy`) —
but **the config surface still advertises the retired direct path**, including in the deployed
`config.js`. Nothing reads it, so nothing breaks; it is a **stale affordance**, and it is the
same shape as the `-backend-config` orphan below. Cleanup, not a defect.

---

## Q1 — what a call site looks like here

The full transport census of `src/`, by idiom:

| idiom | count | where |
|---|---|---|
| `axios` instance (`api`) | 1 instance, all REST | `src/api/client.ts:59` |
| direct `axios.get` (bypasses the instance) | **1** | `client.ts:52` `fetchEntitlements` |
| `fetchEventSource` (SSE) | 1 | `client.ts:335` `/interview/stream` |
| `ShapeStream` (Electric) | 2 | `lib/electric.ts`, `lib/electricHumanTasks.ts` |
| raw `fetch()` in components | **4** | see table below |
| `WebSocket` / `sendBeacon` / `XMLHttpRequest` | **0** | — |

**Eight transport sites in the entire application.** No generated client, no framework data
loader, no service worker. This is why the design read *is* effectively the sweep: enumerating
eight sites was cheaper than designing a method to sample them, and I read all eight.

---

## Q3 — is there a wrapper that centralizes it? YES

`src/api/client.ts:59` — `axios.create({ baseURL: API_URL })` with a request interceptor at `:79`:

```
api.interceptors.request.use((cfg) => {
  const token = getOidcToken();
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  cfg.headers["X-Trace-Id"] = crypto.randomUUID();
  cfg.headers["X-Session-Id"] = getSessionId();
  return cfg;
});
```

**This is the minting point, and it is correct.** Bearer from the OIDC session, plus the two
correlation headers ADR-0038 relies on. Anything routed through `api` is identified and traceable
by construction.

**So the sweep's real question in this repo is not "which calls are minted" but "which calls
bypass the interceptor" — and the answer is five of eight.** Not all five are defects; the
distinction is what each one loses.

---

## Q2 — the population, read: five interceptor bypasses, ranked by what they lose

| site | token? | trace/session headers? | verdict |
|---|---|---|---|
| `client.ts:52` `fetchEntitlements` — direct `axios.get` | **yes** (hand-rolled header) | **no** | idiom drift — loses correlation only |
| `client.ts:335` `/interview/stream` — SSE | **yes** | `X-Trace-Id` yes, `X-Session-Id` **no** | idiom drift — SSE cannot use the axios interceptor; header set by hand and one was missed |
| `lib/electric.ts`, `electricHumanTasks.ts` — ShapeStream | **yes** | n/a | correct — different transport, deliberate, proxied through bff |
| `InlineFigures.tsx:139`, `FiguresSlideIn.tsx:74`, `FederatedImage.tsx:54` | **yes** | no | acceptable — all three read `auth.user?.access_token` and set the header |
| **`NodeInspector.tsx:19`** | **NO** | no | **CONFIRMED defect — see below** |

Note the shape of that table: **four of the five bypasses still carry the user's token.** A
grep-driven sweep that flagged "not using the api instance" would have produced five rows, four
of them noise. The interceptor is a *convenience*, not the only path to an identity — which is
exactly why the frame had to be settled before counting.

---

## THE ONE CONFIRMED ROW — `NodeInspector.tsx`, and it carries TWO defects on one line

```
src/components/AgenticCanvas/NodeInspector.tsx:6
  const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
src/components/AgenticCanvas/NodeInspector.tsx:19
  fetch(`${API_URL}/graph/node/${encodeURIComponent(inspectedNodeId)}`)
```

No second argument. **No headers. No `useAuth` import anywhere in the file.**

Held to the four-fact standard used for repos 1–4:

1. **The route is real and gated.** `gateway.py:3746` —
   `@app.get("/graph/node/{node_id}")`, `current_user: User = Depends(get_current_user)`.
2. **The caller is live.** `Layout.tsx:4` imports it, `Layout.tsx:76` mounts `<NodeInspector />`
   unconditionally — not behind a flag, not dead code.
3. **Credentials are demonstrably available.** Three sibling components in the same tree read
   `auth.user?.access_token` and set the header; `client.ts` has `getOidcToken()`. This is not a
   call that *couldn't* be identified — one that *wasn't*.
4. **It fails quietly, as content.** `fetch` does not reject on 401. `res.json()` parses
   FastAPI's `{"detail": "Not authenticated"}` and `setNodeData(data)` renders it verbatim into
   a pane captioned **"Raw Graph Node"**, styled as JSON. The user sees an error body dressed as
   graph data.

### The second defect, and why it MASKS the first

Line 6 reads `import.meta.env.VITE_API_URL` directly — **bypassing `src/config.ts`**, the module
that exists precisely because Vite bakes `import.meta.env` at **build** time while the container
supplies config at **runtime**. Every other call site uses `config.VITE_API_URL`.

The CI image is built by the `Dockerfile` with **no `VITE_API_URL` build arg and no tracked
`.env`** (`.env.example` is tracked; `.env` is not). So in the deployed image line 6 evaluates to
`http://localhost:8000`, and the request never leaves the browser's loopback.

**Which means the outer defect hides the inner one.** Today the panel fails at the network layer
→ `.catch` → renders `{"error": "Failed to connect to backend"}`. Nobody sees the missing-token
bug, because the request never reaches cortex-bff to be refused.

> **Fix the config bypass alone and the panel starts reaching the bff — and starts rendering
> `{"detail": "Not authenticated"}` as graph data.** The two defects must be fixed together, and
> the seal must assert **both**: that the URL comes from runtime config *and* that the request
> carries a bearer.

That is the whole value of this row. A one-line "use `config`" fix looks like an improvement and
converts a visible failure into a plausible-looking one.

### Also worth recording: this is why it survived

There is **no `.dockerignore`**, and the Dockerfile does `COPY . .`. A *local* `docker build`
copies the untracked `.env` into the build context and bakes real values in; **CI does not.** So
the defect is invisible in a local build and present in every CI-built image. A
build-environment divergence, in the direction that hides the bug from whoever is most likely to
look for it.

---

## FALSE POSITIVES FOUND — the "data the repo publishes" mechanism, twice more

The mechanism catalogued yesterday from doc-tools recurs here, and it is now the most productive
entry in the catalogue:

- **`hooks/useCompileWorkflow.ts:54`** — `agent_endpoint: \`http://restate-agent-svc:8081/${n.id}\``.
  A hostname grep flags cortex-ui as a caller of the Restate service. Reading shows it is a
  **field in the BPMN payload the UI POSTs to cortex-bff** — a value it *publishes*, and one the
  browser could not reach anyway (`restate-agent-svc` is in-cluster, cortex-ui runs in a browser).
- **`lib/mockGroundingEmitter.ts`** — ~14 in-cluster URLs (`iagent-engine-a:8081/analyze`,
  `iagent-engine-w:8088/query_knowledge`, `iagent-engine-e:8086/query_graph`, …) inside **mock
  provenance fixtures**. Every one is a hostname in source that is neither called nor reachable.

**This is the only one of the false-positive mechanisms a human reader would also plausibly get
wrong at a glance** — the other four were tool artifacts. A hostname in source is ambiguous
between *an address this code dials* and *a string this code carries*, and only reading resolves
it. In this repo the ambiguous strings outnumber the real call sites **roughly two to one.**

---

## CANDIDATE — an orphaned ConfigMap declaring three platform endpoints

`helm/cortex-ui/templates/configmap.yaml` renders `{{ .Release.Name }}-backend-config` with
`ONTOLOGY_SERVICE_URL` (engine-o), `DATAHUB_SERVICE_URL` (engine-d), `DAGSTER_WEBSERVER_URL`.

**Nothing consumes it.** No `envFrom`, no `configMapRef`, no volume mount anywhere in the chart —
the frontend deployment takes env from `.Values.frontend.env` only. It is a leftover from when
this chart shipped a backend.

Not a caller — nothing reads it, so it dials nothing. Filed as a **candidate cleanup** because it
is a third artifact *declaring* platform endpoints that no workload uses, and it is the sort of
thing that makes a future hostname sweep produce phantom rows.

*(Unverified in this read: `values.yaml` sets no `frontend.env` at all, so the deployed
`VITE_API_URL` must come from an overlay outside this repo. Stated as unverified rather than
assumed.)*

---

## NOTED, NOT SWEPT — `VITE_NO_AUTH`

`config.ts:52` defaults it to `"false"`; `auth/RequireAuth.tsx:13` and `components/UserMenu.tsx:14`
read `config.VITE_NO_AUTH === "true"` and disable the auth requirement.

It is **runtime**-injectable via `docker-entrypoint.sh`, so it is a deployed-image toggle, not a
build-time one. It does not create an unminted *caller* — with no session, calls simply carry no
token and the gated bff refuses them. Recorded because it is the one switch in this repo that
changes whether identity exists at all, and `enable-agentic-auth-flip` should know it exists.

---

## What this means for the flip

**Repo 5 of 5 read. The cross-repo enumeration is complete**, and cortex-ui contributes **zero**
rows to the unminted-caller population — for a structural reason, which is a stronger result than
a zero from searching:

> **A static SPA cannot have an unminted server-side caller. There is no server.**

The two CONFIRMED unminted callers remain the ones from repos 3 and 4, both server-side, both
hitting engine-o. cortex-ui's defect is a **different failure mode** and should not be counted in
that population: a browser call that drops the user's token against a gated route is a broken
panel, not an unauthenticated actor.

---

## The work — DONE 2026-08-11, cortex-ui `2c3b8a9`

1. ~~**Fix both defects on `NodeInspector.tsx` together.**~~ **DONE** — `config.VITE_API_URL`,
   `useAuth()` bearer, and the missing `!res.ok` check, in one commit with the reasoning recorded
   inline so a future bisect does not split them.
2. ~~**Seal it in a shape that can fail.**~~ **DONE, in the durable form instead** — rather than
   a per-component assertion, the guard below enforces the class. Four controls verified
   break-on-purpose, each RED, restored byte-identical.
3. ~~**Handle `!r.ok` before `.json()`.**~~ **DONE.** Checked as a class: the three sibling fetch
   sites already had it; this was the only site missing it.
4. ~~**Consider a lint rule rather than more sweeps.**~~ **DONE — `scripts/check-transport-declarations.mjs`.**
   Every outbound call routes through `src/api/client.ts` or carries
   `// transport-exception: <why>`. **Wired into `npm run build`**, because this repo has no test
   framework and CI builds the image via the Dockerfile, which runs `npm run build` — the one
   command that must succeed for an image to exist. A guard anywhere else executes nowhere.
   `scripts/redproof-transport-guard.mjs` plants an undeclared `fetch`, asserts RED naming the
   file, removes it, asserts GREEN returns.

   **The five existing bypasses are declared, not exempted** — four of the five already carried
   the user's bearer, so a sweep on "doesn't use the api instance" would have produced five rows
   and four false positives. Each declaration now states what identity the call carries.

   The guard **asserts its own scope is inhabited** — missing scan root, absent allowlisted
   wrapper, an allowlisted wrapper containing no sites, or a site count below the census floor
   all fail loudly. That is `legacy-dns-guard-phantom-scope`'s lesson applied at birth rather
   than after a month of green. Comments are blanked before matching so it cannot trip on its
   own prose, which is the *other* sibling-guard failure.

### Two design corrections found while building it — both recorded because they nearly shipped

- **A fixed line-count lookback silently invalidates the longest declarations.** The first draft
  accepted a marker within 3 lines above the call; the two most thorough declarations (5 and 6
  lines, explaining the proxy and the blob-vs-JSON constraint) were reported as violations. The
  window is now *the contiguous comment block*, which is what "attached to this call" actually
  means. A guard whose annotation format penalises thoroughness trains people to write thin
  annotations.
- **Fixing the config bypass alone would have made things worse**, which is the finding above
  proving itself in the repair: `fetch` does not reject on 4xx, so the panel would have started
  rendering `{"detail": "Not authenticated"}` as graph data.

5. **Cleanup (low) — NOT done, deliberately.** `VITE_ELECTRIC_URL` and the orphaned
   `-backend-config` ConfigMap are legibility work on code that behaves correctly. Left as
   separate items so this commit stays a security fix plus its guard.

## Related

- `unminted-caller-enumeration` — repos 1–4; this read closes repo 5 with a structural zero.
- `enable-agentic-auth-flip-packet` — the cross-repo precondition this completes.
- `legacy-dns-guard-phantom-scope` — same week, same lesson: a scan's scope is a claim, and here
  the scope claim ("cortex-ui might have unminted callers") turned out to be false for a reason
  no amount of grepping would have surfaced.
