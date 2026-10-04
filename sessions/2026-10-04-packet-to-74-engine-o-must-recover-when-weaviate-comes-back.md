# Packet: engine-o must recover when Weaviate comes back, not sit cold

to: ia-74/lane/74
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-04 (order relayed by the architect)

## The order
Engines that start during an outage must recover. You own the registration helpers
(`agent_fleet/utils/mesh_registration.py`, which carries the 9/23 retry fix `2c7b85cf`), so this
one is yours.

## What happened at roll #16
- Rev 170 failed with Weaviate, Keycloak and Restate unschedulable. Neo4j's container was the
  last store ready, at 00:26:29Z.
- engine-o's pod started at 23:46 against no Weaviate.
- Rev 171 did not replace that pod. Engine-o's pod template was unchanged, and the
  re-register hook leaves engine-o out (see "A stale claim" below).
- Result: the census went 0/21. After `roll-litany.sh iagent-engine-o` at 02:26 it was 17/21.

## The defect, read at master `e1d6d6c3`
- `agent_fleet/ontology_service/main.py:793`: the lifespan calls `create_weaviate_client()` once.
  On failure it prints and leaves `_WEAVIATE_CLIENT = None`.
- Line 793 is the only assignment apart from the `None` initialiser at :408. Every reader
  (:1305, :1447, :1754, ...) then takes its no-Weaviate branch for the rest of the pod's life.
- `/health` does not report this, so nothing restarts the pod either.

## A stale claim beside it
- `helm/invincible-agent/values.yaml:1299` says engine-o is "the registry CONSUMER and is
  deliberately excluded" from `primeSubstrate.reregisterEngines.deployments`.
- But engine-o's lifespan also self-registers the SUSTAINMENT `mesh:resolveInstance` provider
  (main.py, just after the Neo4j connect).
- So engine-o is the one engine that registers at startup and is never restarted after the
  prime. Either the retry fixes it, or the list gains engine-o. Your call; the comment
  needs correcting in both cases.

## Seal asked
Start engine-o with Weaviate unreachable, then bring Weaviate back, and watch it recover
without a restart. It must answer from the Weaviate index, not from the cold-start fallback.

Two control conditions:
- the arm must red against today's main.py (line 793 unchanged);
- the arm must not pass merely because the client object exists. Assert a read that goes
  through Weaviate.

## Which other workloads started against a down store (rev 170 window, 23:46 to 00:26:30Z)
| workload | started against | outcome |
| --- | --- | --- |
| every `engine-*` except engine-o, plus data-analyst | down stores | restarted 00:59 by the re-register hook, after the stores came up. Not stale. |
| engine-o | Weaviate down | **stale until 02:26** (this packet) |
| projector | Neo4j down | 180 bolt ConnectionRefused, then silent with 0 restarts. Restarted by hand at 01:00. **Same class: no retry-until-ready.** |
| mesh-registrar | stores down | `/health` 503 until 00:26:23Z, then healthy. The 9/23 fix working. |
| cortex-bff | registrar down | "registrar unreachable" in retry cycles until 00:23, quiet since. Recovered on its own. |
| user-code, gateway, domain/dag/pub brokers and code locations, electric, dagster daemon and webserver | no store-connection errors in their logs | not affected |

The projector belongs in the same order. It has the same shape: one connect at startup, no
retry after it.
