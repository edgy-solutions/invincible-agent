# ADR-0046 — A LangGraph graph is registered as a mesh verb: one graph, one verb, full contract

**Status:** Proposed (2026-09-01). **Not started, and deliberately not next.** This ADR exists to
make the wrong build refusable before anyone starts the right one. The tempting build —
`run_any_graph` — is refused by name in §2.
**Date:** 2026-09-01
**Deciders:** Architect
**Related:**
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — the `direct_call` ruling
    (*"the model MUST NOT contain a permanently-ungated step kind"*) and Decision 5's
    pre-resolved-step seam. **This ADR is that ruling one level up**: `direct_call` refuses an
    ungated step *kind*; this refuses an ungated *engine*.
  - [ADR-0045](ADR-0045-engine-f-finance-verbs-over-standard-ontologies.md) — the engine template,
    stamped once. Engine F is the proof that an engine can be born declaring; a hosted graph is the
    next thing that must be.
  - [ADR-0030](ADR-0030-verb-output-is-a-fixed-type.md) — a verb's output is a fixed type. A graph
    whose output shape varies per run cannot be a verb.
  - [ADR-0038](ADR-0038-telemetry-as-provenance-projection-langfuse-standard.md) — the graph's
    internal steps are telemetry, not provenance. See §6.
  - [`docs/runbooks/adding-an-engine.md`](../runbooks/adding-an-engine.md) — §0–§10 is the cost this
    ADR proposes to collapse into a manifest, and the honest measure of what "pluggable" must beat.

---

## Context

### What exists today — read 2026-09-01, cited, and it is not what the dispatch assumed

**Engine B exists, is deployed, and is invisible to the mesh.** The read corrected three premises,
and the corrections are load-bearing rather than pedantic — each changes what the build is.

**CORRECTION 1 — Engine B is not wrapped in Restate, and importing Restate into it is explicitly
forbidden.** [`agent_fleet/langgraph_support/main.py:11-13`](../../agent_fleet/langgraph_support/main.py)
says so in its own docstring: *"This service is an entirely isolated K8s pod. Do NOT import Restate,
Dagster, or any Engine A dependencies here."* It is a plain FastAPI service on port 8082. **Restate
is Engine A** (`agent_fleet/restate_analyst/main.py:2`, *"Engine A — Restate + Smolagents Durable
Analyst Microservice"*, port 8081). The two are different engines on different substrates. Every
inherited claim about "the LangChain engine wrapped in Restate" describes a service that does not
exist, and §5 rules what follows from that.

**CORRECTION 2 — the graph is a placeholder, not an implementation.** Two nodes, both stubs that say
so: `triage` is a keyword heuristic (`main.py:86-101` — *"In production this would call an LLM or a
rules engine. For now it applies a simple keyword heuristic as a placeholder"*) and `respond`
returns an f-string (`main.py:104-125` — *"In production this would invoke an LLM chain. For now it
returns a templated summary so the wiring is testable end-to-end"*). There is no LLM in Engine B.

**CORRECTION 3 — Engine B registers nothing.** It calls `register_engine_to_mesh` **zero** times;
eight other engines call it (`data_analyst`, `datahub_wrapper`, `finance_agent`, `neo4j_expert`,
`ontology_service`, `planning_agent`, `restate_analyst`, `weaviate_expert`). It has transport auth
(`_announce_transport_auth(component="engine-b")`, `main.py:183`) and a `/health` probe, and beyond
that the mesh cannot see it: **no verbs, no Contract D ends, no slots, no subject, nothing for
entitlements to scope.** It is a pod with a URL.

*Reachability note:* the call sites below are cited from source. **No live call was made** — Engine
B is `enabled: false` on the cluster this project measures against, so nothing here is a runtime
observation.

### Why it exists — the long-term-memory intent, and the four ways it short-circuited

The intent is recorded in the caller, not in Engine B: `synthesize_stateful`
(`src/iagent/defs/dynamic_supervisor.py:2357-2392`) *"Fans-in the results from all parallel
sub-tasks and forwards them to Engine B (LangGraph Support) to maintain conversational memory."*
Everything the supervisor produced was to flow through Engine B so the system would remember it.

**The memory machinery is real.** `AsyncPostgresSaver.from_conn_string(POSTGRES_URI)`
(`main.py:158`), compiled into the graph as its checkpointer (`main.py:161`), keyed by `thread_id`
(`main.py:244-250`). That is durable, per-thread state in PostgreSQL, and it works.

**It short-circuited in four independent places, and each one alone is sufficient:**

| # | the short-circuit | citation |
|---|---|---|
| 1 | **Nothing ever reads the memory back.** Neither node consults prior state: `triage` reads only `task_description`, `respond` reads only `triage_category` / `dataset_id` / `task_description`. `messages` is written into state and read by no node. No endpoint retrieves a checkpoint. The store accumulates and is never consulted — **write-only memory** | `main.py:86-125`, `main.py:215-262` |
| 2 | **The one caller discards the result.** `synthesize_stateful(results=collected_results)` — the return value is bound to nothing, and no downstream op depends on it | `dynamic_supervisor.py:2586` |
| 3 | **Failure is swallowed by design.** `ConnectionError` and `HTTPError` are caught and become `{"status": "skipped"}` with a log warning, explicitly so *"a failure here must not poison an otherwise-successful pipeline"* | `dynamic_supervisor.py:2380-2391` |
| 4 | **It is off where the project measures.** `engineB: enabled: false  # LangGraph support — Phase 3 (stateful sessions)` in sandbox; `enabled: true` in the default values | `values-sandbox.yaml:31-32`, `values.yaml:313-314` |

Layers 3 and 4 compose into this repo's most-cited failure shape: **the memory hop is skipped, the
pipeline is green, and nothing reports a difference between "remembered" and "did not run."** The
intent was never abandoned by decision; it was disabled by default and forgotten, and the design
that would have made forgetting visible was never built.

**Two defects found by this read. FILED, NOT FIXED** — they belong to whoever owns Engine B, and
this ADR's fences are `docs/adr/` only:

- **The Dagster trigger asset cannot succeed.** `trigger_langgraph_support()`
  (`src/iagent/defs/agent_routers.py:110-116`) POSTs with **no JSON body**, while
  `SupportRequest.thread_id` (`main.py:202`) is required with no default — so the request is a
  422 before the graph is reached. The asset has a metadata card describing an endpoint it cannot
  call successfully.

  > **AMENDED 2026-09-02 — THE CLASS WAS THREE, NOT ONE, AND IS NOW FIXED.** This bullet filed
  > Engine B's instance. Reading its neighbours found that **three of the six trigger assets sent
  > no body**, each failing differently: Engine B → 422 (`thread_id`); **Engine C `/scrape` → 422**
  > (`ScrapeRequest` requires `task_description` *and* `dataset_id`); **Engine A `/analyze` → 502
  > reading `Restate proxy call failed`**, because `analyze_proxy` takes a raw Starlette `Request`
  > and its `await request.json()` raised inside a bare `except Exception` — **a caller defect
  > wearing a downstream outage's clothes**, which sends the next reader to debug Restate.
  >
  > **The one-of-three filing was itself load-bearing.** The other three assets carry hand-written
  > `# Dummy payload for now` comments, so the set *reads* as if somebody decided which engines
  > needed a body — when the three without were simply the three nobody ran. Fixing only Engine B's
  > would have left that reading intact and made it more convincing.
  >
  > All three now send a body; Engine B's `thread_id` is run-scoped (`dagster-{run_id}`) because it
  > is the `AsyncPostgresSaver` checkpoint key and a constant would fold every Dagster run into one
  > conversation forever. `analyze_proxy` now returns **400 naming the body** for a parse failure,
  > leaving 502 to mean Restate. Guarded by
  > `tests/test_agent_router_triggers_send_a_body.py`, which reads both sides as source via `ast`
  > (no engine imports) and was **proven to bite** — each guard broken on purpose, red for its own
  > reason, restored. **The second defect below is NOT fixed**: it needs an output `owl:Class` and
  > a prime, which is §1 work.
- **Engine B borrows Engine A's response shape.** It returns BAML `AgentResponse`, whose graph class
  `mesh:AgentResponse` is documented as *"The final output of a smolagents CodeAgent run"*
  (`setup/ontologies/mesh_system.ttl:109-112`) — Engine A's loop, not Engine B's graph. Engine B has
  no output type of its own, so even the Contract D output end it would need does not describe it.

### The question this ADR answers

Teams building on LangGraph have the ecosystem, the hiring pool and an afternoon to first demo, and
no governance. This mesh has the governance and an onboarding cost measured by
`adding-an-engine.md`'s §0–§10. The hybrid dissolves the choice — **build the graph in LangGraph,
register it in the mesh** — but only if the pluggable unit is contract-shaped. Get that wrong and
the mesh acquires a hole exactly the size of every graph anyone ever plugs into it.

---

## §1 — THE DECISION: the unit of registration is one graph, one verb

**A LangGraph graph is admitted to the mesh as a registered verb, with the same contract every
other verb carries.** Not as a runner, not as an engine-shaped escape hatch, not as a capability
that takes a graph name as a parameter. One graph = one verb (or a small **declared** set of verbs
per hosted graph; see the open question in §8).

To be registered, a graph declares — in a manifest, authored once per graph:

| what it declares | derived from | why it cannot be skipped |
|---|---|---|
| **input slots** with name, type, mandatory-ness, defaults | the graph's input schema (its `TypedDict` / Pydantic state), by inspection | without slots the router cannot know a slot is missing — only that nothing cleared threshold, which surfaces as `NO_VERB_CLASSIFIED`: an information gap wearing a threshold gap's clothes (`agent_fleet/finance_agent/slots.py:1-12`) |
| **slot KIND** — `spoken-mandatory` / `spoken-optional` / `handle` / `ceremony` | **hand-annotated**, never inferred | two `str` parameters can have opposite provenance and no type system tells them apart (`slots.py:32-36`). §7 refuses auto-derivation as a non-goal |
| **arity** — does the question have to name one instance? | signature-derived: a slot both required and a referent ⇒ `single` (`planning_agent/slots.py:271-300`) | the eligibility gate drops a `single` verb from a set-shaped question; without arity the question routes to a verb that cannot answer it and 400s two hops later |
| **its subject** (`input_uri`) and **its output** (`output_uri`), both real `owl:Class` nodes | authored in an ontology extension, ridden in on the prime manifest | Contract D refuses atomically if either end is absent; there is no exemption for graphs |
| **identity requirements** | declared | the graph runs under a caller, or it runs under no one and is unauditable |
| **its refusal contract** | declared | §3 |

**The output class is declared `rdfs:subClassOf mesh:Response`,** and that single line buys the
graph a fix it did not have to know about: response shapes are excluded from Engine O's grounding
pool at the write site, so a graph's output can never compete with its own input subject for the
question that invokes it (`tests/routing/test_response_shapes_are_not_groundable.py`). **A hosted
graph inherits the platform's fixes rather than re-earning them** — which is the whole argument for
plugging in rather than bolting on, made concrete.

**Why a verb and not an engine-shaped special case.** ADR-0029 Decision 5 established that a
declared step invokes **stage 2, the structural eligibility gate, as a verifier**, then dispatches —
enforcement is literal at the dispatch seam. A registered graph-verb inherits that seam unchanged.
An engine-shaped special case would need its own enforcement, which is a second decider, which is
the bypass class the model exists to eliminate.

---

## §2 — REFUSED BY NAME: `run_any_graph`

**The tempting build is a generic verb that takes a graph identifier and an opaque payload. It is
refused, and it is refused here rather than in a review comment, because it is the thing most
likely to be built by accident** — it is one afternoon's work, it demos beautifully, and it is the
eligibility system's antithesis.

A `run_any_graph(graph_id, payload)` verb has:

- **no slots to declare** — the payload is opaque, so the filler has nothing to fill, the elicitation
  machinery has nothing to ask about, and a missing mandatory input is discovered inside the graph
  (or, worse, defaulted inside it) rather than refused at the boundary;
- **no arity** — every question is set-shaped to the gate, so a graph needing one named instance is
  routed questions that name none;
- **no subject** — one `input_uri` for all graphs means grounding cannot discriminate between them,
  and the capability answer ("what can I ask about X?") degrades to "there is a graph runner";
- **one output type for all graphs**, which either violates ADR-0030 or is `Any`, which is the same
  violation spelled differently;
- **nothing for entitlements to scope.** This is the sharpest one: entitlement is per
  `(persona, domain)` against a *verb*. One verb for all graphs means **one grant for all graphs** —
  entitlement to the runner is entitlement to everything anyone ever plugs in, including graphs
  authored after the grant was made.

**The precedent is exact.** ADR-0029 admitted `direct_call` as **TRANSITIONAL — escapes the verb
ontology, NOT the gate**, still gated on `can_invoke(caller, capability)`, and explicitly a
*promotion candidate*: *"The model MUST NOT contain a permanently-ungated step kind (that is the
bypass class — in-code fallbacks / second deciders / ungated paths — the model exists to
eliminate)."* `run_any_graph` is that bypass class one level up: not an ungated step kind but an
ungated **engine**, and unlike `direct_call` it has no promotion path, because there is nothing to
promote it *to* — it is already the terminal shape.

**If a transitional escape is ever genuinely needed**, it inherits `direct_call`'s full terms and
not a softer set: capability-gated on a *per-graph* capability (never one capability for the
runner), declared transitional at registration, and closed by promotion to a declared verb. A
per-graph capability is most of the manifest's work anyway, which is the argument for skipping the
escape hatch entirely.

---

## §3 — What the boundary provides, and what the graph's author owes

Two lists, explicit, because "pluggable" is only meaningful if the split is stated. **The graph
itself is not modified.** The shim sits at the engine boundary, in front of `ainvoke`.

**Provided — the author writes none of this:**

1. **Slot validation, and a 422 that names the vocabulary** on a missing mandatory slot — not a
   Python `TypeError` reaching a person as *"missing 1 required keyword-only argument"*
   (`docs/plans/a-missing-mandatory-slot-is-a-400-not-an-ask.md`).
2. **Elicitation inheritance** — the ask-card, the enumerated menu from the declared vocabulary, the
   ADR-0033 disambiguation grammar. The author declares an enum; the machinery is inherited.
3. **Identity threading** — the caller's identity reaches the graph's execution and the audit line,
   under ADR-0044's per-request minted ticket.
4. **Entitlement scoping** — the graph-verb appears in a caller's eligible set or it does not, by
   the same `(persona, domain)` walk as every other verb.
5. **Registration and Contract D** — the manifest is converted to a registration; both ends are
   pre-verified so a partial set cannot land.
6. **Grounding-pool exclusion of the output shape** — free, from the `subClassOf mesh:Response`
   declaration (§1).
7. **Disclosure and the audit line** — what was asked, how it was interpreted, which verb ran, under
   whose identity.

**Owed by the graph's author — and each of these is a judgment a tool cannot make:**

1. **The manifest** — the declarations in §1's table.
2. **The slot kinds** — hand-annotated (§7).
3. **Honest subject and output definitions.** The `rdfs:comment` **is** the recall signal, written
   for the class and never for a query, with no sibling-name bleed
   (`adding-an-engine.md` §1). A definition that describes *the ask* rather than *the thing*
   attracts the ask — which is exactly how a response shape came to out-compete its own input
   subject, measured at 12/20.
4. **A refusal contract**, stated: what the graph refuses, and on what grounds. **A graph that
   defaults a missing input internally cannot be registered** — that is the one behaviour the shim
   cannot paper over, because by the time control reaches the graph the boundary has already
   passed. This is the price of admission and there is no version of this ADR where it is optional.
5. **Determinism, or declared non-determinism.** A graph free to vary its output *shape* per run
   cannot satisfy ADR-0030. Varying *values* is fine; varying *type* is not.

### §3.1 — The registration route: three options, and what the SDK can and cannot carry today

**Added during drafting, in answer to a direct question. The first draft evaluated the substrate
(§5) and the unit (§1) and skipped the route — how a graph's declarations actually reach the
registrar. There are three, they are not equally available, and the difference is measured by two
open defects rather than by preference.**

| route | what it means | status |
|---|---|---|
| **A — manifest + platform shim** | the author writes declarations; the platform converts them to a registration and enforces the boundary in front of `ainvoke` | what §1–§3 assume; **nothing blocks it** |
| **B — SDK self-registration** | the hosting service imports the mesh SDK and calls `register_engine_to_mesh` at boot, exactly as the eight registering engines do | **proven** — this is how every live engine registers |
| **C — graph plugs into a hosting engine as a `MeshTool`** | a graph author writes a tool against `iagent_mesh.core.MeshTool` and the hosting engine exposes it | **REFUSED TODAY** — see below |

**A and B are not rivals, and the synthesis is the likely build:** the manifest (A) is the authoring
surface, and what it *emits* is a B-shaped registration. B is the proven mechanism; A is the thing
that removes the per-graph registration code. Nothing here requires a new registration path.

> #### UPDATED 2026-09-01, hours after drafting — the SDK lane landed the fixes, and route C is still refused
>
> **Both defects were worked in `iagent-mesh-sdk` while this ADR was being written, and the
> disposition is one closed, one half-closed — neither consumed.** Verified against that repo's
> tree, not against a report:
>
> - **`sdk-blocking-sync-handlers` is CLOSED** (`e6b6757`, v0.4.0): sync handlers now run via
>   `anyio.to_thread.run_sync` under an explicit `contextvars.copy_context()` — *the quickstart's
>   promise was made true rather than corrected away.* Both rulings the packet demanded were
>   answered **by enumeration**: the census found **zero** `MeshTool` call sites in this repo, so
>   the population holding retroactively-broken handlers was empty and there was nobody to audit.
> - **`sdk-discards-caller-identity` remains OPEN**, and the SDK lane says so itself rather than
>   claiming the win: the SDK half is delivered, but the packet's own step 3 is in **dag-tools** —
>   `CortexDataClient` has no `caller=`, no contextvar read, no `CORTEX_USER_TOKEN` rung, no opt-in
>   service identity. Acceptance 3 is *"vacuously true, not satisfied"* (the variable holds only
>   because nothing reads it) and acceptance 4 is partial (a bare `CortexDataClient()` in a handler
>   still resolves to the service **silently**).
>
> **THE WAKE CONDITION IS THE PIN BUMP, NOT THE TAG** — and the reason is now the *second* one,
> because the first expired within the hour.
>
> ⛔ **SUPERSEDED, same day, before anyone read it.** This paragraph first said v0.4.0 was *"local
> to the SDK working tree — not pushed, not on `origin`, not on PyPI"*, and concluded *"a tag that
> exists locally is a fix that exists nowhere downstream."* **That was true when written and false
> by the time it was committed.** Verified directly rather than accepted from the report:
> `refs/tags/v0.4.0` → `9b36f7d` on the SDK's `origin` (which is also `origin/master`), and
> `iagent-mesh 0.4.0` is **live on PyPI** — wheel and sdist both published. The availability
> objection is gone. Kept visible rather than edited away, because the sentence was quotable and
> someone would have checked it.
>
> **The ruling is unchanged and now rests on cleaner ground: nothing here consumes it.**
> **13 `pyproject.toml` files carry the pin in 14 occurrences** (12 under `agent_fleet/` at one
> each, plus the root at two; a 14th tracked `pyproject.toml`, `agent_fleet/cortex_bff/`, carries
> none), **and 13 `uv.lock` files. Every one still resolves `v0.3.1`; not a single pin has moved.**
>
> **Count the TRACKED population, and here is the command, because an unscoped grep gives a
> different and wrong answer** — 15 files / 18 occurrences, the extra coming from vendored
> `site-packages` copies under `.venv`:
>
> ```bash
> git ls-files '*pyproject.toml' | xargs grep -c 'iagent-mesh @ git+'   # 13 files, 14 occurrences
> ```
>
> *That discrepancy was found by two lanes counting independently and reconciling — a file count
> filtered to tracked files reported alongside an occurrence count that was not. The number was
> not wrong so much as **un-scoped**, which is the same defect class as a by-name check that
> matches only one spelling. Hence the command rather than the number.*
>
> So §8.5's condition is unmet, and the route-C refusal below stands — for the sharper reason it
> was already given: not two open defects, but a fix no consumer here has taken.
>
> **Two consequences of publication, both narrowing the question rather than answering it:**
>
> 1. **The bump is now cheaper and has two legal forms.** `iagent-mesh==0.4.0` from PyPI is
>    available alongside the `git+…@v0.4.0` pin this fleet uses today. **§8.5's checkable event
>    must admit either**, or a bump that takes the PyPI form will read as unmet when it is not.
> 2. **The half-closed defect is now the ONLY structural blocker, exactly as predicted.**
>    Publication removed the availability objection and did nothing for `CortexDataClient` step 3.
>    So once the pins move, route C's refusal rests **entirely** on: a bare `CortexDataClient()` in
>    an agent handler still resolves to the service *silently*, and acceptance 3 is vacuously true
>    rather than satisfied. That is the load-bearing half, and it is untouched.
>
> **A severity correction, recorded because it was overstated in conversation before it was
> checked:** "every current MeshTool consumer is entitlement-unscoped" has **zero instances in
> this repo**. Every `MeshTool` here is prose, or `DynamicMeshTool` — a smolagents `Tool` subclass
> in `restate_analyst/orchestrator/discovery.py:37`, an unrelated class. `mesh_registration.py:7`
> states the reason: engines *"don't use MeshTool — they're FastAPI apps with their own"*
> registration. The defect is real and the blast radius **here** is nil, which is precisely why it
> could sit open: it is a trap for the first consumer, not a live wound.

**Route C is refused today, on evidence, and the evidence is fatal rather than inconvenient.**
`MeshTool` — the SDK's tool-hosting surface, and the natural home for "plug a graph in" — carried
two defects in `iagent-mesh-sdk` when this was drafted, and the first one destroys §3's
provided-guarantee #3:

- **`[[sdk-discards-caller-identity]]`** (open; `iagent_mesh/core.py:180`, `:440`). **MeshTool
  computes a `CallerIdentity`, logs it, and discards it** — app-level dependency return values are
  dropped by FastAPI, and `execute()` calls `func(input_data)` only. A tool author cannot learn who
  invoked them, so *"their only working option entitles every caller of that agent to everything the
  service can reach."* **And it fails invisibly: reading as the service works** — rows come back,
  nothing errors, nothing warns, no test fails.
  **This is precisely the failure class this ADR exists to prevent, sitting inside the component
  that would be the plug-in route.** Identity threading is not a nice-to-have here; it is what makes
  a hosted graph's answer entitlement-scoped rather than service-scoped. A graph plugged in through
  MeshTool today would be an ungated engine wearing a contract — §2's refusal arriving by a
  different door.
- **`[[sdk-blocking-sync-handlers]]`** (blocked-on-human). MeshTool runs **synchronous handlers
  directly on the event loop, no threadpool**, while the quickstart recommends sync `def` and
  promises a background thread that does not exist. LangGraph nodes are routinely sync and routinely
  do real work, so a hosted graph on this path can block the whole tool server. Its packet also
  records the coordination constraint: both defects change `MeshTool.execute()`, and *"two
  uncoordinated fixes to one seam is how it grows a third defect."*

**What the SDK already carries, verified rather than assumed:** authenticated registration transport
in the app factory (`[[sdk-transport-auth-handoff]]`, closed by `68e28c0`, confirmed **consumed** —
an ancestor of tag `v0.3.0`, with the fleet since moved to `v0.3.1`). Engine B itself imports it
(`iagent_mesh.transport_auth`, `main.py:180-183`). The SDK is a live dependency of this fleet, not a
hypothetical — which is exactly why its gaps bind rather than merely inform.

**The ruling:** build route A emitting a route-B registration. **Route C wakes when both SDK defects
close, and not before** — and when it does, it is the better authoring story, because a tool author
writes a handler instead of an engine. Note the structural echo of ADR-0037: this ADR now has a
**cross-repo dependency it did not have when drafted** — `iagent-mesh-sdk`, one item open and one
blocked on a human ruling. That does not block §1, which is why the two are separated here.

---

## §4 — The memory question: what Engine B was for, and what this ADR does about it

**This ADR does not resurrect the memory design, and does not silently bury it.**

The intent was that everything flow through Engine B to be remembered (§Context). The machinery
that would do it is live — a Postgres checkpointer keyed by `thread_id`. What is missing is
**every consumer**: nothing reads a checkpoint back, nothing depends on the call, failure is
swallowed, and the engine is off by default.

**The ruling here is narrow and deliberate: conversational memory is not a verb, and this ADR does
not make it one.** A checkpointer is per-thread execution state — the right thing for a graph to
resume from, and the wrong shape for a mesh answer, which is entitlement-scoped, provenance-carrying
and addressed by subject rather than by thread. Registering "remember this" as a verb would put an
unentitled, unprovenanced write path into the mesh, which is the opposite of what the mesh is for.

**What this ADR does rule:**

- **A hosted graph MAY use the checkpointer** as its own durable state. That is LangGraph's native
  mechanism and there is no reason to take it away.
- **Checkpoint state is NOT mesh-visible.** It is not queried through verbs, not grounded against,
  not entitlement-scoped, and carries no provenance. A graph that wants its output remembered
  *in the mesh* emits a declared output class through its verb, like everything else.
- **The write-only-memory defect is not inherited.** If a hosted graph's state is written and never
  read, that is a fact about that graph, and the seal in §6 asserts a hosted graph's declared
  behaviour is exercised — precisely so the fourth short-circuit above cannot recur silently under a
  new name.

**Whether Engine B is retired, re-registered or repurposed as the host is an open question (§8),
not a decision this ADR smuggles.** What is decided: **it does not stay as it is** — a deployed,
unregistered, off-by-default pod running placeholder nodes is not a state anyone chose, and it has
already survived one architecture cycle by being invisible.

---

## §5 — The durability seam, stated honestly: there isn't one yet

**The dispatch for this ADR assumed the wrapper was Restate-wrapped and asked what durable
execution buys the graph. The read refutes the premise, so the section reports rather than
answers.**

What Engine B has today is **LangGraph checkpointing**: state persisted per `thread_id`, resumable
by a subsequent call presenting the same id. What ADR-0029 built on is **Restate**: durable
execution with `ctx.promise()` suspend/resume, the substrate under the sealed HITL Case-2 workflow,
where a human-await is a real suspension rather than a poll.

**These are different guarantees and the difference decides the build.** A checkpointer resumes a
graph that is re-invoked; it does not suspend an in-flight invocation waiting on a human, and it
does not give the caller a durable promise to hold. So a hosted graph containing a human-in-the-loop
step has two possible homes, and the choice is §8's first open question:

| option | what it means | cost |
|---|---|---|
| **A — graphs host on the existing FastAPI+checkpointer pattern** | Engine B's shape, made registerable. Human-await is expressed as *separate verbs* either side of a mesh-level suspension, per ADR-0029's human-await step | graphs with internal HITL must be split at authoring time; the mesh owns the suspension, which is arguably correct |
| **B — graphs host inside the Restate substrate** | one graph invocation can suspend on `ctx.promise()` mid-run; the workflow model and the graph model unify | Engine B's docstring forbids exactly this import today; a real engineering seam, not a config flag |

**Do not resolve this by asserting Restate's documented properties.** Option B's cost is measured by
attempting it, and until someone does, the honest state is that the mesh's durable-HITL story lives
in ADR-0029's workflow model and a hosted graph reaches it by being *called from* a workflow step,
not by containing one.

---

## §6 — Acceptance seals, each proven-to-bite before green counts

Per the runbook's governing rule: every check asks the **graph, by name**, at the resolution of the
claim. None asks a component about itself.

1. **A graph-verb with an undeclared mandatory input is refused at registration.** Register a graph
   whose input schema has a required field absent from the manifest → registration fails naming the
   field. *Bite check:* the same registration with the field declared succeeds.
2. **A missing mandatory slot 422s naming the vocabulary** — not a `TypeError`, not a default
   silently applied inside the graph. *Bite check:* the pre-fix behaviour (a graph defaulting
   internally) is demonstrated to produce an answer, so the seal is shown to distinguish them.
3. **The output class never grounds.** The graph's `output_uri` is absent from Engine O's `/resolve`
   candidate pool for any phrasing. *Bite check:* remove the `subClassOf mesh:Response` declaration
   and the class reappears in the pool — the seal keys off the declaration, exactly as
   `test_response_shapes_are_not_groundable.py` does, and for the same reason: a declaration a human
   must remember to write needs a derivation asserting it.
4. **The eligibility gate acts on declared arity.** A set-shaped question does not route to a
   `single`-arity graph-verb. *Bite check:* the same question routes when arity is `None`.
5. **Entitlement discriminates, three callers.** An entitled caller routes; an unentitled caller
   gets the honest refusal; a caller entitled to a *different* graph-verb does not reach this one.
   **This is the seal that `run_any_graph` cannot pass**, and it is worth running against a
   deliberately-built `run_any_graph` once, to demonstrate the refusal in §2 empirically rather than
   by argument.
6. **The graph's declared behaviour is exercised end to end** — a routed question reaches the graph
   and returns its declared output type. This is the seal Engine B never had, and its absence is why
   four short-circuits accumulated unnoticed.

**Graph-internal steps are telemetry, not provenance** (ADR-0038). A node-by-node trace belongs in
Langfuse under the existing vocabulary, unrenamed. The mesh's provenance records *which verb ran
under whose identity and how the question was interpreted* — it does not become a graph debugger.

---

## §7 — Non-goals, each with its reason

- **No `run_any_graph`.** §2. Repeated here because it is the one most likely to be built by
  accident, and a non-goal is where people look when they are about to build something.
- **No graph marketplace / dynamic upload.** A graph enters by PR like every other piece of ratified
  config. Runtime-uploadable graphs would make the registered verb set unreviewable, which is the
  property that makes any of this auditable.
- **No auto-derived slot kinds.** Names, types, defaults and mandatory-ness are derived from the
  schema; **kind is a judgment**. Two `str` parameters can have opposite provenance and no type
  system distinguishes them (`slots.py:32-36`); the `_REFERENT_KIND` note records the measured cost
  of guessing — the filler emitted `site_id="Aurora"` at 0.92 confidence and earned an honest 422 to
  a perfectly answerable question. Signature-derived defaults, hand-confirmed.
- **No bypassing the prime.** A graph's classes ride the `CANONICAL_TTL_MANIFEST` like everyone
  else's, and Contract D applies unchanged. There is no fast path for graphs.
- **No LangChain-specific mesh vocabulary.** The mesh does not learn what a graph is. It sees a verb;
  the fact that a graph computes it is an implementation detail of one engine, and the day a team
  arrives with a different framework, nothing in the mesh needs to change.
- **Not a rewrite of Engine A.** Engine A's smolagents loop is a different pattern with its own
  registration; this ADR does not touch it.

---

## §8 — Open questions, with the options laid out

Each of these is genuinely open. **None is a decision written as prose.**

1. **Which substrate hosts graphs — FastAPI+checkpointer (A) or Restate (B)?** §5's table. Decidable
   only by attempting B far enough to price it. **Blocks nothing in §1** — the contract is
   substrate-independent — so the manifest work can start before this resolves.
2. **One graph per engine, or several graphs per hosting engine?** One-per-engine gives each graph
   its own identity, entitlement surface and blast radius, at the cost of a pod per graph.
   Several-per-engine amortises the deployment but shares a Keycloak client across graphs whose
   entitlements may differ — and the four-namespace lesson (`adding-an-engine.md` §0) says a shared
   component name is where wiring gets missed. **Leaning one-per-engine on entitlement grounds;
   not decided.**
3. **The manifest's exact schema, and where it lives.** Candidates: a TTL sibling of the ontology
   extension; a YAML beside the graph; declarations in Python as `slots.py` does today. The third
   has the strongest precedent and the weakest cross-language story. **Note the standing debt:**
   `slots.py`'s derivation is already duplicated across Engines F and P, with the extraction filed
   and the third consumer named as the point where it *"stops being a cost and becomes the defect"*
   (`finance_agent/slots.py:27-31`). **A hosted-graph manifest is that third consumer.** Doing this
   work without extracting first would land the duplication the authors of both copies already
   ruled against.
4. **What becomes of Engine B?** Retire it; re-register its existing use case under the new contract
   (§9's slice 1); or keep it as the hosting engine for option A. Decided by 1 and 2, not
   independently — but **not left as it is** (§4).
5. **When the SDK fix is CONSUMED here, does route C supersede route A's shim?** (§3.1.)
   **The checkable event is the pin bump across the 13 `pyproject.toml` files and their 13
   `uv.lock` entries — not the existence of a tag.** v0.4.0 is now on the SDK's `origin` and on
   PyPI (§3.1), and *still* no consumer here has taken it: every pin resolves `v0.3.1`.
   **The bump counts in EITHER form** — the `git+…@v0.4.0` pin this fleet uses today, or
   `iagent-mesh==0.4.0` from PyPI, which publication newly makes available. Naming only the git
   form would make a PyPI-form bump read as unmet when it is not.
   Note also that only one of the two defects is closed; the identity item's remaining step is in
   `dag-tools`, so "both closed" is a **three-repo** condition, not a two-repo one — and after the
   pins move it is the *only* thing route C's refusal rests on. It is the
   better authoring story — a handler instead of an engine — but it moves the boundary enforcement
   into the SDK, which means the 422-with-vocabulary and the entitlement filter become the SDK's
   guarantees rather than this platform's. That is a good trade only if the SDK's guarantees are
   sealed here too. **Not decidable until the defects close**; recorded so the question is asked
   rather than answered by whoever happens to be building that week.
6. **Does a hosted graph get a `resolved_via` tier of its own?** ADR-0031's provenance tiers make a
   weaker resolution visible. Whether "answered by a hosted graph" is a weaker tier than "answered
   by a deterministic verb" is a real question, and the answer is probably yes if the graph contains
   an LLM node. Not decided; it does not block §1.

---

## §9 — Rollout: slice 1 proves the model on the thing that already exists

**Nothing new until the existing thing passes its own gates** — ADR-0029's slice-1 discipline.

**Slice 1 — re-register Engine B's actual use case under the contract.** Not a new graph. Take the
conversational-synthesis case, give it a real subject and output class, a manifest with declared
slots, an identity requirement and a refusal contract, and make it route. Success is a routed
question reaching the graph and returning its declared type, with the six seals green and each
proven-to-bite.

This slice is deliberately unglamorous, and it is the right one for a reason the Context section
earns: **Engine B is the system's own worked example of what happens when a component is admitted
without a contract.** It ran for an architecture cycle, disabled, unregistered, its output
discarded, its failures swallowed, its memory never read — and nothing anywhere went red. Proving
the contract on precisely that component is the strongest available demonstration that the contract
does something.

**Slice 1 has a prerequisite that is not obvious from its own description, and it is stated here so
it is not discovered mid-build.** The manifest is the **third consumer** of the slot-declaration
derivation now duplicated across Engines F and P — and the third consumer is the point both copies'
authors already named as where it *"stops being a cost and becomes the defect"*
(`finance_agent/slots.py:27-31`). **So the extraction to `agent_fleet/utils/slot_declarations.py` is
on slice 1's critical path, not a filed nicety**, and it comes first: writing the manifest against
either existing copy lands a third divergent derivation and makes the extraction strictly harder
than it is today. The flat/packaged import idiom the extraction must survive is
`adding-an-engine.md` §5, and `tests/test_agent_modules_survive_flat_layout.py` is the seal.

> **AMENDED 2026-09-04 — THE COUNT IS NOW FOURTH, AND THE MECHANISM HAS ALREADY FORKED.** Scoped in
> [`the-manifest-is-the-fourth-consumer-not-the-third`](../plans/the-manifest-is-the-fourth-consumer-not-the-third.md),
> which carries the measurement and the requirements list; the deltas to *this* section are:
>
> **1. `agent_fleet/cost_agent/slots.py` landed 2026-09-03 — the third copy is not the manifest.**
> The threshold this paragraph invokes has already been crossed, by a consumer it did not
> anticipate. The manifest is the **fourth**. Engine-cost's author saw it, named it in the module,
> and kept that copy deliberately the thinnest so the extraction would have less to reconcile — the
> right call, and not what changed the picture.
>
> **2. The paragraph below — *"the extraction takes the MECHANISM and each engine keeps and passes
> its own VOCABULARY"* — no longer describes the tree.** That reading held for two copies. With
> three, the **mechanism itself** has diverged, not only the vocabularies: `slots_for()` emits
> `required` in F and P and **`mandatory`** in C; `_type_of()` returns `(type, enum-values)` in F
> and P and a **bare `str`** in C; `_is_union` is absent from C. The extraction therefore has to
> reconcile a forked output contract before it can hoist anything, which is strictly more work than
> this section priced.
>
> **3. "One moving target… so it does not become a three-way merge" is now six**, and it *is* a
> three-way merge. `arity_for` (P), `missing_mandatory` + `refusal_for` + `with_live_vocabularies`
> (F), `all_declarations` + `mandatory_slots` (C). **None is incidental — every one of them answers
> a row of §1's manifest table**, which is the strongest form of this section's own argument: the
> manifest is the first consumer that needs the *union*, so the extraction cannot be scoped by
> taking any single engine's copy as the template.
>
> **4. The 86-identical-lines figure is a two-copy measurement (2026-09-01) and is not restated for
> three.** It is left as recorded rather than updated, because re-measuring it is the extraction
> lane's first step and a remembered number would pre-empt it.
>
> **What does NOT change:** the extraction is still on slice 1's critical path, and the flat/packaged
> import idiom and its seal are unchanged. The correction makes the prerequisite more urgent, not
> less. **One thing it adds:** settle the `required`/`mandatory` key *before* the extraction rather
> than inside it — the consumer has already voted (`ontology_service/main.py:2673` reads `required`),
> and it is a one-word fix now against a compatibility shim in shared code later.

**And the extraction has a SHAPE, measured rather than assumed** (by the lane that owns both
copies, 2026-09-01): `planning_agent/slots.py` is 305 lines, `finance_agent/slots.py` is 267, and
they are **30% similar — 86 identical lines. This is not a copy with drift.** What is shared is the
**derivation mechanism**: the `inspect.signature` walk, the `eval_str=True` handling for
`from __future__ import annotations`, the union/container origin split in `_type_of`, the
required/default logic. What diverges is each engine's **vocabulary**: `_REFERENT_KIND` maps
different parameters to different class URIs, `_PERIOD_KIND` and the fiscal calendar are
planning-only, and `HANDLE_SLOTS`/`CEREMONY_VERBS` differ per engine.

**So the extraction takes the MECHANISM and each engine keeps and passes its own VOCABULARY.** An
extraction that hoisted the vocabularies too would either grow a domain switch inside a shared
util or force one engine's referent map onto the other — and the finance and planning referent
kinds are genuinely different facts about different ontologies. That distinction is the difference
between a refactor that holds and one that gets re-forked in a month.

**One moving target, named here so it does not become a three-way merge:** planning's copy gained
`arity_for()` (§1's arity row) deriving query-shape eligibility from the same signature walk;
finance has no equivalent. The extraction therefore merges a function that exists on one side only,
and doing it while that is still settling costs more than waiting for it to.

**Slice 2 wakes on the first real graph a team wants to plug in** — not before. The manifest schema
(§8.3) should be authored against a second real consumer rather than designed against an imagined
one, which is the same discipline that produced the runbook template.

---

## Consequences

- **A team keeps LangGraph and gains governance.** The pitch against "why not plain LangChain"
  stops being a comparison and becomes *keep your LangChain* — build the graph in the ecosystem
  with the hiring pool, register it with a manifest.
- **The mesh does not learn what a graph is.** One more engine registering verbs; the framework is
  an implementation detail. A different framework arriving later costs a manifest, not an ADR.
- **Hosted graphs inherit platform fixes.** The response-shape exclusion is the first evidence this
  compounds: a graph declaring its output `subClassOf mesh:Response` gets a fix authored days
  earlier, without knowing it exists.
- **The refusal contract is the price, and it will be the friction.** Some graphs default missing
  inputs internally; those graphs cannot be registered until they stop. **This is the ADR working,
  not the ADR being difficult** — a graph that quietly defaults is precisely the confident-wrong
  answer the mesh exists to refuse.
- **`run_any_graph` is refusable by citation now**, which is the artifact's main near-term value:
  the wrong build is one afternoon's work and demos well.

## Indicators we got this wrong

- **Nobody plugs a graph in for six months.** Then the manifest is too expensive and the honest
  response is to make the derivation cheaper, not to relax the gates.
- **The first hosted graph needs an exemption.** If slice 1 cannot satisfy its own seals without
  softening one, the contract is wrong somewhere and the exemption is the diagnosis, not the fix.
- **A `run_any_graph`-shaped thing appears under another name** — `execute_workflow(spec)`,
  `invoke_agent(config)`. The shape is the tell, not the name: an opaque payload, one verb, nothing
  to declare.

## The one-sentence model

**A graph is admitted the way everything else is admitted — by declaring what it takes, what it
produces, who may call it and what it refuses — and the mesh never learns that a graph is what
computes the answer.**
