---
id:         packaged-imports-unresolvable-in-agent-images
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/mesh_registrar/v2_restate.py
repo:       invincible-agent
summary:    FOUND 2026-08-22 by a seal written after Engine P hit the same defect. `v2_restate.py:162` does `from agent_fleet.mesh_registrar.main import _get_neo4j_driver, _get_weaviate_client` inside the RegistrationSaga handler. `agent_fleet` DOES NOT EXIST in the agent image — verified live against the running mesh-registrar pod: `ModuleNotFoundError: No module named 'agent_fleet'`. The VirtualObject IS mounted ("Mounted Restate VirtualObject 'RegistrationSaga' at /restate"), so the handler raises on invocation rather than at boot, which is why the pod is healthy and has been for as long as anyone has looked. NOT FIXED HERE — mesh_registrar is registry work and belongs to another lane; recorded, waived explicitly in tests/test_agent_modules_survive_flat_layout.py with an expiry guard that fails once the defect is gone.
---

# A registration handler that cannot import what it needs

Found by a seal written for Engine P's own version of this defect, then **verified against
the live image** rather than inferred from source.

## Measured

```
$ kubectl exec iagent-mesh-registrar-… -- python -c \
    "from agent_fleet.mesh_registrar.main import _get_neo4j_driver"
ModuleNotFoundError: No module named 'agent_fleet'
```

The agent image is built with `COPY ${AGENT_DIR}/ /app/` and `WORKDIR /app`, so
`/app` **is** `agent_fleet/mesh_registrar/`. Its modules are top-level (`main`, `v2_saga`),
and the `agent_fleet` package does not exist at any path.

## Why it has never been seen

The import is **inside the handler body**, not at module scope:

```python
# agent_fleet/mesh_registrar/v2_restate.py:162
from agent_fleet.mesh_registrar.main import (
    _get_neo4j_driver, _get_weaviate_client,
)
```

So it raises when `RegistrationSaga.register` is INVOKED, not when the service starts. The
pod boots, mounts the VirtualObject, passes every probe, and reports healthy — and the
registration path is dead. That combination is the reason to file it rather than wait for it:
**there is no symptom to notice.**

Whether anything currently calls this handler is not established here. If nothing does, the
defect is latent and cheap. If something does, its failures would surface as saga errors far
from this line.

## Same class as Engine P's

Engine P had the identical shape and it cost a full build-and-roll cycle to find:

```python
try:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh
except ImportError:
    register_engine_to_mesh = None      # ← twelve registrations skipped, in silence
```

The try/except made the crash go away without making the import work. Engine P served
`/health`, reported healthy, and registered nothing; the Predicate count sat at 52 across two
settled reads with no error in any log. **Guarding a repo-only import does not fix it — it
hides it.** The fix is a real alternative: `from utils.… import …` first, packaged second.

## Fix

```python
try:
    from main import _get_neo4j_driver, _get_weaviate_client
except ImportError:
    from agent_fleet.mesh_registrar.main import _get_neo4j_driver, _get_weaviate_client
```

Both fleet orderings are acceptable — `neo4j_expert` puts flat first, `presentation_agent`
puts relative first. The seal checks only that an alternative EXISTS.

## Why waived rather than fixed

`mesh_registrar` is registry work and belongs to another lane. The waiver in
`tests/test_agent_modules_survive_flat_layout.py` names the file, the reason, and the live
verification, and is paired with `test_no_waiver_outlives_its_defect` — which FAILS if the
waiver stops describing a real offender. A waiver that survives its own fix is a lie the next
reader has to disprove.

## Acceptance

`kubectl exec <mesh-registrar-pod> -- python -c "import v2_restate; …"` resolving the handler
imports, plus deleting the WAIVED entry — the expiry guard will demand the deletion.
