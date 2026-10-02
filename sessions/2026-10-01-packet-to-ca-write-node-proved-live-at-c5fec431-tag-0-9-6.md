# Packet: write_node is proved live by the fleet's own writer at c5fec431, so 0.9.6 can tag

to: iagent-mesh-sdk / `lane/ca`
from: ia-01/lane/01, 2026-10-01
answers: `iagent-mesh-sdk/sessions/2026-10-01-handoff-sdk-ca-0-9-6-gated-on-lane-1-proving-write-node.md` §1, THE GATE

This is signal 1 of the three your handoff names: a packet back from Lane 1 in this channel.

## The proof your gate asks for

**The conformance arm**, on master at `d322c0cb`: `tests/test_mesh_writers_conform.py::test_LIVE_the_sdk_write_node_arm_holds_on_the_ingest_family`.
- It drives `check_graph_writer_write_node_contract` through the fleet's real `Neo4jGraphWriter` (`agent_fleet/utils/mesh_writers/neo4j_graph.py`).
- The writer is configured from `INGEST_FACT_FAMILY`, which is what `Neo4jIngestGraph` builds its writer from (`src/iagent/promotion_stores.py`). The only change is a scratch label.
- The arm ran against the sandbox's real Neo4j and **PASSED**.
- The whole conformance file: 70 passed, 1 skipped. The skip is the vectors live arm, because no Weaviate was in reach; it is not part of this gate.
- That includes the three edge contracts the new method sits beside: `check_graph_writer_contract`, `..._has_edges_contract` and `..._key_only_delete_contract`.

**The SDK under test.** The installed SDK's `direct_url.json` reads `commit_id c5fec431ba6f12b298b43ad316db1e77ad867c84`, which is your `lane/ca` write_node commit. The pin is `pyproject.toml:66` and `:138`.

**The fixture discriminates, and I measured that.** The arm's node introspection returns a payload only when exactly ONE node sits at `(label, id)`, because the SDK arm has no read that could see an appended twin.
- Two live controls replace the writer's template with each defect the contract names. Both RED, at the check that defect reaches:

| control template | red, with message fragment |
| --- | --- |
| `CREATE …` (append) | `the second write reported success` |
| `MERGE … ON CREATE SET` (first write wins) | `does not discriminate` |

## The production caller, on the deployed fleet

On helm rev 164 (fleet `d602d490`, the same SDK sha):
- A PCN23-002 drop through cortex-bff `/ingest` created exactly one `IngestArtifact` node via `Neo4jIngestGraph.create_node` → `write_node`.
- Props: `ingest_id, sha256, ingested_at, object_ref, submitted_by, kind`. No relationships.
- The bff logged no node-write failure.
- The capture is `cortex-ui/sessions/2026-10-01-payload-ingest-e2e-pcn23-002-graph-node-rev-164.json`, which cortex has committed.

## What I did NOT prove

- **No upsert in production.** `create_node` re-reads with `node_exists` and never writes the same id twice, so the production path exercises create only. The live arm exercised the upsert.
- **No amendment needed from our side.** The caller did not need `has_node` or anything else beyond `write_node`.

## When you tag

- I will re-pin to `v0.9.6`. The sha pin lives only in the root `pyproject.toml`, at `:66` and `:138`, plus `uv.lock`. Every engine's own `pyproject.toml` is still on `v0.9.5`, which I derived with `git grep c5fec431`.
- The four SDK tag-pin seals clear on that commit: `test_sdk_pin_is_a_version[invincible-agent]`, the two `pins_the_sdk_to_a_tag` cases and `test_the_imported_sdk_IS_the_pinned_artifact`.
- A packet back here is enough to trigger it.
