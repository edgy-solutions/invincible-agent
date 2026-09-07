---
id:         slice-1-cannot-declare-slots-for-an-input-no-node-reads
status:     closed
owner:      agent
blocked-on:
closed-by:  83ec883
closed-by-note: Closed by an ARCHITECT RULING rather than by code, and 83ec883 is the commit that records it in ADR-0046 (§8.4 RULED - retire Engine B; §9 amended - slice 1 waits for its consumer). This packet asked slice 1 to choose between declaring the implemented TRIAGE case and implementing the intended SYNTHESIS case, and named a third reading it did not rule: that a use case whose principal input was never read by anything is evidence for retirement. The ruling took the third. mesh:StatefulSupportResponse STAYS DECLARED as the class the next hosted graph inherits, and the checkpointer pattern stays documented.
repo:       invincible-agent
ruled-by:   ADR-0046 §1 (the admission grammar) and §9 (slice 1) — this packet SCOPES slice 1 against Engine B as it actually is
code-site:  agent_fleet/langgraph_support/main.py, src/iagent/defs/dynamic_supervisor.py, setup/ontologies/mesh_system.ttl
summary:    Scoping ADR-0046 §1's manifest rows against Engine B found a blocker that is not a missing declaration but a missing consumer. The use case slice 1 exists to register — conversational synthesis, per synthesize_stateful — sends its PRINCIPAL INPUT as `dagster_context`, the fanned-in results of every parallel sub-task. Engine B writes that into `messages` and NO NODE READS IT. So the verb cannot honestly declare a slot for the one thing its caller sends, and slice 1 must first choose between declaring the TRIAGE case that is implemented or implementing the SYNTHESIS case that is intended. Also resolved here - the OUTPUT end is now declarable and declared (mesh:StatefulSupportResponse, 2026-09-06); the INPUT end is NOT, because no class describes Engine B's subject and which subject it is depends on ADR-0046 §8.4, which is open. Contract D refuses atomically if either end is absent, so this is a hard gate on registration, not a tidiness note.
---

# Slice 1 cannot declare slots for an input no node reads

**Scoped 2026-09-06** for ADR-0046 §9 slice 1 — *"re-register Engine B's actual use case under the
contract."* Read-only against source; **no live call was made**, because Engine B is
`enabled: false` in sandbox (`values-sandbox.yaml:31-32`).

## §1 — ADR-0046 §1's manifest rows, resolved against Engine B as it is

| row | status for Engine B | why |
|---|---|---|
| **output class** | **DONE 2026-09-06** — `mesh:StatefulSupportResponse`, `rdfs:subClassOf mesh:Response` | declarable because it describes the shape `/support` returns today; verified in the grounding-exclusion seal's derived population (49 response shapes, `tests/routing/test_response_shapes_are_not_groundable.py`) |
| **subject (`input_uri`)** | **BLOCKED** | no class in any TTL describes what an Engine B question is *about*, and **which** subject it is depends on §8.4 — the triage case and the synthesis case have different ones |
| **input slots** | **BLOCKED — see §2** | the intended use case's principal input has no consumer in the graph |
| **slot KIND** | derivable once slots are | four-kind vocabulary is settled; `thread_id` is the interesting one (see §3) |
| **arity** | **`single`, and it is forced** | `thread_id` is required with no default *and* names one conversation instance — the signature-derived rule (`planning_agent/slots.py`) gives `single` with no judgment call |
| **identity requirements** | **partially known** | Engine B already takes the SDK transport-auth dependency and announces `component="engine-b"`; `user_id` defaults to `"default_testing_user"`, which is a defaulted identity and therefore not an identity requirement at all |
| **refusal contract** | **derivable, and thin** | today the only refusal is FastAPI's 422 on a missing `thread_id`. There is no domain refusal, because there is no domain logic — both nodes are placeholders |

## §2 — THE BLOCKER: the use case's principal input has no consumer

`synthesize_stateful` (`src/iagent/defs/dynamic_supervisor.py:2907`) is the caller that states the
intent — *"Fans-in the results from all parallel sub-tasks and forwards them to Engine B (LangGraph
Support) to maintain conversational memory."* It sends:

```python
json={"thread_id": …, "user_id": …, "user_query": …, "dagster_context": results}
```

`dagster_context` **is** the use case: every parallel sub-task's result, fanned in. Engine B's
`/support` turns it into a `SystemMessage` appended to `messages` — and **no node reads
`messages`.** `triage` reads `task_description`; `respond` reads `triage_category`, `dataset_id`
and `task_description`. That is ADR-0046 Context's short-circuit #1, met again from the declaration
side rather than the behavioural one.

**Why this stops slice 1 rather than slowing it.** §1's whole argument is that declaring slots is
what lets the router know a slot is missing instead of reporting `NO_VERB_CLASSIFIED`. A
declaration for `dagster_context` would be **a declaration the graph cannot honour** — the router
would learn to require, resolve and pass a value that changes no output. That is worse than the
current silence: it converts an unimplemented feature into a *contract*, which is precisely the
failure ADR-0046 exists to make refusable.

**The endpoint's own request model already disagrees with its caller**, which is the same fact seen
a third way. `SupportRequest` declares `task_description` and `dataset_id` — the fields the nodes
read — while the real caller sends neither, and `/support` papers over it with
`request.task_description or request.user_query` and `request.dataset_id or "default"`. **Three
descriptions of what this verb takes exist and no two agree**: the request model, the caller, and
the nodes.

## §3 — So slice 1 must choose, and the choice is cheap to state and not cheap to make

**Option A — declare the TRIAGE case, which is implemented.** Subject is a support task; slots are
`thread_id` (spoken-mandatory, `single`) and `task_description`; output is
`mesh:StatefulSupportResponse`. Everything declared is honoured. **Cost:** it registers the
placeholder — a keyword heuristic and an f-string (`main.py:86-125`) — as a mesh verb, and §9's
success criterion (*"a routed question reaching the graph and returning its declared type"*) would
be met by a graph that does no work. The contract would be proven on a component whose answer is a
template.

**Option B — implement the SYNTHESIS case first, then declare it.** Make a node read `messages` /
`dagster_context` so the fan-in has an effect, then declare against that. **Cost:** slice 1 stops
being "re-register the thing that exists" and becomes a build — which is exactly what §9 chose it
*not* to be (*"Nothing new until the existing thing passes its own gates"*).

**A third reading exists and should be named rather than discovered:** §8.4's *retire Engine B* is
still live, and this packet is evidence for it. **If the use case's principal input has never been
read by anything, the honest question is whether the use case exists at all** — and slice 1 would
then be proving the contract on a component the system is about to delete.

**Not ruled here.** §8.4 says this is *"Decided by [§8.1 and §8.2], not independently."* This packet
records what the declaration attempt found, so whoever rules §8.4 rules it knowing that the
intended use case is unimplemented rather than merely disabled.

## §4 — Dependencies, stated so nobody starts around them

- **The `slot_declarations` extraction is Lane 1's and gates the build.** Per ADR-0046 §9 as
  amended 2026-09-04, the manifest is the extraction's fourth consumer and writing it against any
  single engine's copy would land a fifth divergent derivation. **This packet does not start the
  manifest**, and slice 1's slot work should not begin before the extraction lands. Requirements
  the extraction must satisfy are in
  [[the-manifest-is-the-fourth-consumer-not-the-third]].
- **The output class's CODE half has not landed.** `mesh:StatefulSupportResponse` is declared in
  `mesh_system.ttl` and **needs a prime to reach the graph**; Engine B still returns BAML
  `AgentResponse` in `main.py`. Registration cannot cite a class the graph does not hold.
- **Engine B is `enabled: false` in sandbox**, so every claim here is source-read. Nothing in slice
  1 can be verified live until it is enabled.

## §5 — What this packet does NOT do

It does not author the manifest (Lane 1's extraction gates it), does not rule §8.4, does not declare
a subject class, and makes no live observation. It also does not fix the three-way disagreement in
§2 — that fix depends on which option §3 takes, and choosing it here would be the ruling this packet
exists to inform.

## Related

- [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) §1, §8.4, §9.
- [[the-manifest-is-the-fourth-consumer-not-the-third]] — the extraction's requirements list.
- [[engine-b-has-no-output-type-of-its-own]] — the sibling defect; its ontology half is now closed.
