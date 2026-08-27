---
id:         sdk-discards-caller-identity
status:     open
owner:      human
blocked-on: 
closed-by:  
code-site:  iagent_mesh/core.py:180, iagent_mesh/core.py:440
repo:       iagent-mesh-sdk
summary:    THE DESTINATION IS AGENTS, NOT NOTEBOOKS — and per-user reads are impossible there today, INVISIBLY, because reading as the service works. MeshTool computes a CallerIdentity, logs it, and DISCARDS it (app-level dependency return values are dropped by FastAPI; execute() calls func(input_data) only), so a tool author cannot learn who invoked them and their only working option entitles every caller of that agent to everything the service can reach. Would otherwise have been found by an analyst promoting their first notebook to a tool — by which point the wrong pattern is written and copied. Carries the CortexDataClient resolution-order decision (explicit caller WINS over env; service identity opt-in only), recorded before tool authors invent the precedence backwards.
---

# A MeshTool cannot learn who invoked it

**Found 2026-08-26**, answering a question about what notebook code looks like once it becomes
an agent. The answer is that the correct version **cannot currently be written**.

## FIRST — THE DESTINATION IS AGENTS, NOT NOTEBOOKS

[[jupyter-user-token-data-access]] was scoped as though the endpoint of the journey were an
analyst in a notebook. It is not. **The notebook is where the analysis is prototyped; the
agent is where it lands** — that is what the SDK's own quickstart tells people to do
("when you are ready to turn your logic into an enterprise capability, you move out of the
notebook and into your IDE"). So the per-user property has to hold *there*, and today it
cannot.

**And it fails invisibly, which is what makes it urgent rather than merely open.** An agent
that reads as the service **works**. Rows come back. Nothing errors, nothing warns, no test
fails. The only symptom is that every user of that agent sees data entitled to the service —
which looks like success to the person who wrote it.

**The counterfactual discovery path is the argument for the reframing.** Absent this item,
this would have been found by an analyst promoting their first notebook to a tool — at which
point the wrong pattern is written, working, in the codebase, and probably copied into the
next three tools, because it is the only pattern the SDK permits. Finding it from *"where is
this actually going?"* rather than from an incident is the whole return on asking that
question before shipping the intermediate step.

This does not change [[jupyter-user-token-data-access]]'s value — notebooks are real and the
hub wiring is correct. It changes what "done" means: **per-user access is not delivered when
the notebook works. It is delivered when the agent the notebook becomes works.**

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

## "But they still have to pass `caller`" — and that is still a hole

Requiring `CortexDataClient(caller=caller)` means an author who **omits** it gets a bare
constructor, which resolves to the service and **works**. Same failure, reached by forgetting
rather than by inverted precedence — and forgetting is the more common way.

Making the author type it is not what produces safety. **A request-scoped variable is**, and
the SDK has none — `grep contextvars iagent_mesh/*.py` returns nothing.

The objection to env vars was never *"implicit is bad"*; it was **scope mismatch** — a
process-lifetime variable cannot express a per-request value. A `ContextVar` is scoped to the
request (isolated per asyncio task), so its scope matches the identity's scope exactly. The
same argument that ruled env vars out rules this in.

The auth dependency already runs per request and already computes the identity. It sets the
contextvar; the client reads it:

```python
# notebook, Dagster asset, AND agent handler — IDENTICAL, no variant at all
client = CortexDataClient()
```

Revised resolution order:

> 1. **explicit `caller=`** — an override, for tests and for a handler deliberately acting as
>    someone else. Wins over everything.
> 2. **the request-scoped contextvar** — set by the SDK. The agent case.
> 3. **`CORTEX_USER_TOKEN`** — a per-process user identity. The notebook case.
> 4. **service identity** — **opt-in only.**
>
> **And: if rung 2 is populated — i.e. we are inside a request — failure to resolve an
> identity RAISES. It never falls through to rung 3 or 4.** Being in a handler is precisely
> when reading as the service is wrong, so that is where the fallback must be refused.

Rung 2 above rung 3 preserves the property that mattered: `CORTEX_USER_TOKEN` set on an agent
pod stays harmless, because the request's caller outranks it.

`caller=` survives as an override, not as the thing standing between an author and a
cross-tenant read.

### The threading interaction — a second finding, and it is why FAIL-CLOSED beats the mechanism

`core.py:438` runs synchronous handlers **directly on the event loop**:

```python
if inspect.iscoroutinefunction(func):
    return await func(input_data)
return func(input_data)          # <- no threadpool
```

The SDK's own quickstart tells authors the opposite: *"Use standard `def` (Recommended): if
you are crunching Polars DataFrames (`df.collect()`), stick to standard `def`. **We will
execute it safely in a background thread.**"* **There is no background thread.** A recommended
sync handler doing `df.collect()` blocks the whole tool server — a live defect independent of
identity, and worth its own fix.

It also sets a trap for the contextvar design. When sync handlers *do* move onto a thread, the
mechanism decides whether identity survives: `asyncio.to_thread` copies the context,
`loop.run_in_executor` does **not**. Get that wrong and the contextvar reads `None` in exactly
the handler style the guide recommends — and without rung 2's fail-closed rule it would land
on the service identity, silently, in the most common case.

**Which is the point: the safety comes from refusing to fall back, not from the mechanism.**
The contextvar removes the boilerplate; fail-closed is what makes omission survivable.

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
| 1 | auth dependency sets a request-scoped `ContextVar` with the `CallerIdentity` | the blocker; nothing else can work without it |
| 2 | **fail closed inside a request** — populated contextvar + unresolved identity RAISES, never falls to env or service | the safety. Ships WITH step 1, not after: step 1 alone just relocates the silent fallback |
| 3 | `CortexDataClient` reads the contextvar; `caller=` becomes an override | the boilerplate removal, safe only once 2 exists |
| 4 | `execute()` also passes `CallerIdentity` to handlers whose signature asks | explicit access for tools that need the identity itself, not just a client |
| 5 | run sync handlers in a thread — `asyncio.to_thread`, which COPIES context | makes the guide's promise true; `run_in_executor` would break step 1 |
| 6 | documented snippet pair in the SDK's jupyter guide | see below — **does not precede step 1** |

**Steps 1 and 2 are one change, deliberately.** Shipping the contextvar without the
fail-closed rule moves the silent service-read from "author forgot `caller=`" to "contextvar
was empty for a reason nobody noticed" — the same defect with a longer causal chain.

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
