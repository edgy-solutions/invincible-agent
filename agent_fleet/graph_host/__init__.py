"""The graph host — the engine a team plugs a LangGraph graph into.

ADR-0046 slice 1, re-scoped 2026-09-08: not "re-register Engine B" but "the engine a team
plugs a graph into". Engine B stays retired; the only thing revived from it is the
`AsyncPostgresSaver` + `thread_id` checkpointer pattern, which is the one part that worked.

── §0 OF THE PLAYBOOK: THE FOUR NAMES, CLAIMED BEFORE THE BUILD ────────────────────────────
`docs/runbooks/adding-an-engine.md` §0 — *"An ADR names an engine in prose. It does not
allocate a component name."* Engine F cost an hour by discovering `engine-f` was already the
presentation agent. Four DISTINCT namespaces, written down here so all four can be grepped
when the wiring is thought to be done:

    helm values key                       graphHost
    component / service / deployment      engine-lg
    image name                            graph-host
    Keycloak client id                    iagent-graph-host
    port                                  8098
    source directory                      agent_fleet/graph_host/

**All six were verified free before a line of wiring** — `engine-lg`, `engineLg`, `graphHost`,
`graph-host`, `graph_host`, `ENGINE_LG` and `iagent-graph-host` each returned zero hits across
`helm/ agent_fleet/ src/ scripts/ tests/ policy/`, and 8098 is unallocated (the highest port in
use is 8097, engine-cost). *"Prose names and component names are different registries"*: the
prose name is **the graph host**, and `engine-lg` is what the cluster calls it.

**`engine-lg` is deliberately not a letter.** The dispatch offered "engine-lg or whatever
letter's next", and a descriptive component name is worth more here than the next free letter:
this engine is not one capability, it is the door many graphs come through, and a letter would
tell a future reader nothing about which door.

── WHAT THIS RESOLVES IN ADR-0046, BY CONSTRUCTION RATHER THAN BY RULING ────────────────────
Two of §8's open questions are answered by building this rather than by deciding them, and both
are recorded in the ADR amendment rather than left for a reader to infer:

* **§8.2 — one graph per engine, or several per hosting engine?** The ADR leaned one-per-engine
  on entitlement grounds, *"not decided"*. A manifest-driven host is the SEVERAL side, and the
  entitlement cost the ADR worried about is paid differently: each row declares its own subject,
  slots and domains, and every invocation runs as the initiator (ADR-0049 Ruling 1), so two
  graphs sharing this pod do not share an entitlement surface — they share a process. What they
  do share is a blast radius, and that is the honest cost of this choice.
* **§8.5 — does route C supersede route A's shim?** Route A (this host) with the SDK's
  `MeshTool` *inside* it for every inner call. The question dissolves: the host owns the 422 and
  the entitlement boundary, and `MeshTool` carries identity into the graph's nodes.

── REFUSED BY NAME, INHERITED FROM ADR-0046 §2 ──────────────────────────────────────────────
A generic `run_graph(graph_id, payload)` endpoint. A manifest row with a `payload: object`
slot — `run_any_graph` wearing a manifest, and `manifest.py` raises on it. A node that reaches
a database, an engine or the vault other than through `MeshTool`.
"""
