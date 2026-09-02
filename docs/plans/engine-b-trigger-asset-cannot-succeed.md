---
id:         engine-b-trigger-asset-cannot-succeed
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0046 Context (the Engine B read that found it) — this item is the DEFECT, not the ADR's decision
code-site:  src/iagent/defs/agent_routers.py:110-117, agent_fleet/langgraph_support/main.py:200-213
summary:    A REGISTRATION IS NOT A REACHABLE CALL, in its cleanest new form — the Dagster asset that triggers Engine B POSTs with NO JSON BODY while SupportRequest.thread_id is required with no default, so the request is a 422 before the graph is reached. The asset carries a metadata card describing `POST :8082/support` as though the path worked. Found 2026-09-01 by the ADR-0046 read, from source only; NOT reproduced live, because Engine B is `enabled: false` in sandbox — which is also why it could sit here undetected. Cheap fix (send a thread_id), but the INTERESTING half is that nothing would have caught it: the asset is the only caller that passes no body, and the other caller (dynamic_supervisor) passes a full one and swallows its own failures.
---

# The Dagster asset that triggers Engine B cannot succeed

**Found 2026-09-01**, reading Engine B for [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md).
**From source only — no live call was made**, because Engine B is `enabled: false` on the sandbox
cluster (`helm/invincible-agent/values-sandbox.yaml:31-32`).

## The defect

`trigger_langgraph_support()` posts to `/support` with **no body at all**:

```python
# src/iagent/defs/agent_routers.py:110-117
def trigger_langgraph_support() -> dict:
    """Trigger Engine B (LangGraph) support agent pod."""
    response = requests.post(
        f"{LANGGRAPH_SUPPORT_SVC_URL}/support",
        timeout=300,
    )
    response.raise_for_status()
```

The endpoint's request model requires a field with no default:

```python
# agent_fleet/langgraph_support/main.py:200-203
class SupportRequest(BaseModel):
    """Incoming request to the /support endpoint."""
    thread_id: str            # <-- required, no default
```

Every other field on `SupportRequest` is defaulted. `thread_id` is not — correctly, since it is the
checkpoint key and a default would silently merge unrelated conversations into one thread. So the
call is a **FastAPI 422 before the graph is invoked**, and `raise_for_status()` turns that into an
asset failure.

## Why it matters more than a one-line fix

**The asset advertises a path it cannot walk.** It carries an `_icon_card` metadata block naming
*"**Endpoint:** `POST :8082/support`"* — documentation-shaped, rendered in the Dagster UI, and
describing a call that 422s. That is [[a-registration-is-not-a-reachable-call]] in a new place: the
declaration is present and correct-looking, and nothing connects it to whether the call works.

**Nothing was ever going to catch it**, and the reasons compose:

- The **other** caller (`src/iagent/defs/dynamic_supervisor.py:2369`) sends a full body, so the
  endpoint's happy path is exercised by the code that does not have the bug.
- That caller **swallows its own failures** by design (`{"status": "skipped"}`), so even a genuine
  Engine B fault does not surface there.
- Engine B is **off in sandbox**, so neither path runs where anything is measured.

## The fix, and the check that should come with it

Send a `thread_id`. The asset is a manual trigger, so a stable synthetic id (or one derived from the
run id) is the obvious choice — but **the choice is a real one and should be stated in the code**: a
constant id means every manual trigger appends to one ever-growing thread; a per-run id means each
trigger starts a fresh conversation with no memory. Both are defensible; silently picking one is how
the next reader inherits a behaviour nobody chose.

**Do not verify by watching the asset go green.** Assert the response body — a 200 whose payload is
an `AgentResponse` with the summary the graph produced. `raise_for_status()` on a fixed call proves
the request was accepted, not that the graph ran.

## Related

- [ADR-0046](../adr/ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) — the read that found
  this; its Context section carries the full four-way short-circuit of Engine B's memory design.
- [[engine-b-has-no-output-type-of-its-own]] — the sibling defect from the same read.
