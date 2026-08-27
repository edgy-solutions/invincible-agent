---
id:         sdk-discards-caller-identity
status:     open
owner:      human
blocked-on: 
closed-by:  
code-site:  iagent_mesh/core.py:180, iagent_mesh/core.py:440
repo:       iagent-mesh-sdk
summary:    BLOCKER on every agent doing per-user data reads. MeshTool computes a CallerIdentity, logs it, and DISCARDS it — app-level dependency return values are dropped by FastAPI, nothing reaches request.state, and execute() calls func(input_data) only. A tool author cannot learn who invoked them, so their only working option is to read as the SERVICE, entitling every caller to everything that service can reach. Carries the CortexDataClient resolution-order decision (explicit caller WINS over env; service identity opt-in only) — file it before tool authors invent the precedence backwards.
---

# A MeshTool cannot learn who invoked it

**Found 2026-08-26**, answering a question about what notebook code looks like once it becomes
an agent. The answer is that the correct version **cannot currently be written**.

## The evidence

`iagent_mesh/core.py:180` registers the auth dependency at APP level:

```python
dependencies=[Depends(make_transport_auth_dependency(component=name))],
```

`make_transport_auth_dependency` does the right thing — it returns a `CallerIdentity` whose
`authz_id` is documented as *"the ONLY field an authorization decision may key on."* But an
app-level dependency's **return value is discarded by FastAPI**. It is not injectable into a
route, it is never written to `request.state`, and the route handler does not ask for it.

Then `core.py:440`:

```python
return func(input_data)
```

The handler receives the validated input model and nothing else.

**So the caller is computed, logged, and thrown away.** The one fact a multi-tenant handler
needs in order to read data on the right person's behalf is produced and dropped one frame
before anyone could use it.

## What that forces

A tool author writing a data-reading agent has nothing to put here:

```python
client = CortexDataClient(originator_email=???)
```

Their only working option is to construct the client bare, which resolves to the service
identity — so **every user of that agent reads with the service's entitlements**. That is the
confused deputy the chart's own comment on `CORTEX_CLIENT_ID` warns about:

> DA serves every caller, so entitling the service entitles every caller to whatever it can
> reach — a confused deputy at the data plane.

**Engine DA is the existence proof.** It does not get the caller from the SDK; it pulls
`user_email` off the request payload (`agent_fleet/data_analyst/main.py:271`) because the
supervisor threads it manually. The one agent that does per-user reads correctly had to route
around the SDK to do it. See [[da-sends-no-user-token]] for what else that workaround costs.

## The principle underneath

> **The environment carries DEPLOYMENT CONTEXT. The request carries IDENTITY.**

Which gateway, which realm, which broker, dev-vs-prod: identical for every caller, fixed for
the process lifetime, correctly environmental. `CortexDataClient()` should read all of that
from the environment and run unchanged everywhere.

Identity is different, and the reason is **pod shape**, not API taste:

| context | pods : users | is the process's identity the right identity? |
|---|---|---|
| Jupyter notebook | one pod per user | **yes** — the process *is* the user for its whole life |
| Dagster asset | one pod per run, no user | **yes** — it reads as itself, with its own entitlements |
| Agent handler | one pod, **many users, concurrently** | **no** — identity changes per request; the environment cannot express a per-request value |

An env var in an agent names one identity for every caller. Not a bad design — a **scope
mismatch**.

## The decision to record BEFORE tool authors invent it

Everyone writing this by hand will reach for a helper like:

```python
def get_caller(caller):
    return os.environ['CORTEX_USER_TOKEN'] if 'CORTEX_USER_TOKEN' in os.environ else caller
```

**That inverts the safety.** It works in all three contexts today — and only because
`CORTEX_USER_TOKEN` happens to be unset on agent pods. Set it once (debugging, a dev
deployment, helm values copied from the hub) and **every request silently reads as that one
user**, with code that still looks correct. The confused deputy arrives via a *config* change,
with no code change to review and nothing that reports it.

So the client owns the resolution, and the precedence is the decision:

> **`CortexDataClient` resolution order:**
> 1. **an explicitly passed `caller`** — an actual invoker was named. **Wins over everything;
>    nothing may override it.**
> 2. **`CORTEX_USER_TOKEN`** — a per-process user identity (the notebook case).
> 3. **service identity** — **opt-in only** (`identity="service"` or an env flag that says so).
>    Never fallen into.

**Explicit-caller-first is the whole point.** With that ordering, `CORTEX_USER_TOKEN` on an
agent pod is *harmless* — the handler passes a caller and it takes priority. With the ordering
reversed it is a silent cross-tenant read. One ordering choice is the difference between safe
in every deployment and safe by luck.

**And rung 3 must be loud.** Today a bare `CortexDataClient()` quietly resolves to M2M, which
is the wrong default for a multi-tenant process: the mistake should be an error, not a
convenience. Bare construction in a handler that was given a caller should fail closed.

## The target shape — one line, and only the agent differs

```python
# notebook, and Dagster asset — IDENTICAL
client = CortexDataClient()

# agent handler — the only variant
client = CortexDataClient(caller=caller)
```

Notebook and pipeline are the same line because in both the process's identity *is* the right
identity. The handler names the caller because it must — and that difference **should be
visible in the code**, because it is the difference between "read as me" and "read as whoever
invoked me." Hiding it would be the confused deputy wearing convenience.

Full handler, once the SDK stops discarding the identity:

```python
from iagent_mesh.core import MeshTool
from iagent_mesh.transport_auth import CallerIdentity
from dag_tools.cortex_data.client import CortexDataClient

@app.execute()
def detect_anomalies(data: AnomalyInput, caller: CallerIdentity) -> AnomalyOutput:
    client = CortexDataClient(caller=caller)      # reads as the INVOKING user
    lf = client.get_dataframe(data.dataset_urn)
    ...
```

`authz_id` already honours `USER_ENTITLEMENT_CLAIM`, so agents get `preferred_username`
handling for free — the same claim the gateway now reads.

## Order of work

| # | step | why this position |
|---|---|---|
| 1 | `execute()` passes `CallerIdentity` to handlers whose signature asks for one | the blocker; opt-in by signature, so existing tools are untouched |
| 2 | `CortexDataClient(caller=...)` with the resolution order above | the API decision, recorded before authors invent it |
| 3 | bare construction fails closed where a caller was available | the silent-service-read default |
| 4 | documented snippet pair in the SDK's jupyter guide | see below — **step 4 does not precede step 1** |

## Why the guide is NOT updated yet

The obvious next move is to document the notebook→agent pair in
`iagent-mesh-sdk/docs/jupyter_guide.md`. **Deliberately not done**, because the agent half does
not work: documenting it would publish a capability that does not exist, and the guide is
exactly where a tool author would trust it. Same shape as
[[a catalog entry does not create a routable capability]] — a described capability is not a
routable one.

The snippet pair above is the specified target. It moves into the guide when step 1 lands, not
before.

## Acceptance

- A tool handler can name its invoker, and a read performed inside it is authorized as **that
  person**, not as the service.
- Two different users invoking the same agent against the same asset get **different rows**.
- `CORTEX_USER_TOKEN` set on an agent pod changes nothing, because the passed caller wins.
- Reading as the service requires saying so.

## The ADR-shaped sentence underneath

> **The environment carries deployment context; the request carries identity. A process that
> serves many callers cannot take its authorization subject from its own environment.**
