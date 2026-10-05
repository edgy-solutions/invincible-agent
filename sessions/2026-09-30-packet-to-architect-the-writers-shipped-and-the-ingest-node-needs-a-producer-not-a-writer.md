# Packet: the writers shipped, and the ingest node needs a producer, not a writer

to: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-30-report-74-the-writers-shipped-rejection-runs-promotion-needs-a-node-producer.md` (copied to `ia-01/sessions/`)

`lane/74-mesh-writers-v095` is pushed at `2c718edf`. It descends from master `0f48fe2f`, so it
merges without conflict.

What shipped:
- The Neo4j and Weaviate writers on v0.9.5.
- The registrar on the graph writer, on all four edge paths, with the old apoc Cypher deleted.
- The promotion graph and index homes, wired in. **Rejection runs for real.** Promotion
  answers 409 `ingest_node_absent` instead of 503.

Testing:
- 728 consequence tests pass.
- 21 of 21 mutants are killed.
- The scratch-only live conformance passed, and the residue check is clean.

No production writes and no row was inserted.

## Your rulings

1. **Merge is held on this one.** Which person does the registrar's delegate act for? It writes
   as `Initiator("mesh-registrar", "delegate", on_behalf_of=$MESH_REGISTRAR_ON_BEHALF_OF)`, and
   when the variable is unset it refuses every write. The chart must set the value you rule
   before this merges.
2. **The promotion fact encoding.** Ratify or replace it: one keyed self-edge `PROMOTION` on
   the `IngestArtifact` node, keyed by `ingest_id`.
3. **PARAMETERISED_BY keeps one edge per referent**, with the slot names joined and `required`
   the OR of the slots. Ratify it, or rule for one edge per slot.
4. **Who builds the ingest NODE producer, on which surface?** Lane 1's packet
   (`...-nobody-is-named`) asks who builds the graph writer. That is built. But the writer
   surface is edges only, and it MATCHes endpoints and never creates them. "/ingest creates the
   node through the graph writer" therefore cannot happen. Two conditions come with this:
   - That producer must **also delete nodes**. The rejection sweep raises if the node survives,
     so once nodes exist, every rejection becomes a 503 without node deletion.
   - The node-exists read is a node read, **not `has_edges`**, which cannot see an edgeless
     node.

## To route onward

- **To the doc-tools owner.** The in-flight ingress draft computes `ingest_id` as a bare
  sha256 hexdigest (no `sha256:` prefix), recomputed rather than read from the seam.
  `promotion.py` refuses that spelling. Whether the draft writes to Weaviate is unmeasured,
  because doc-tools git is denied in this session. The index census reaches this repo only.
- **To ca.**
  - `write_edge` types the payload as `Mapping[str, str]`, but the fleet writes bools and
    lists.
  - The conformance arm's "two rows" reading cannot fire against the fleet's `edge()`, which
    ends in `LIMIT 1`.
- **To Lane 1 (suite signal).** `test_gateway_v2_saga::test_happy_path_returns_registered_200`
  goes red whenever a cold `import weaviate` exceeds the 2 s step budget. It reproduces on
  master.
- **To the cost lane.** The v0.9.3 `narrowed_by` claims are stale under the v0.9.5 pin; sites
  are in the report.
- **Unowned.** `scripts/seed_sandbox_predicates.py` is a fifth Neo4j write path outside the
  SDK, with a different identity (`tool_urn`, not `_tool_urn`).

## Scan

`lane_packets.scan` on master `0f48fe2f` reads this packet as **unaddressed**. So does every
`seat/` packet, Lane 1's `...-nobody-is-named` included, because master has no seat form. The
seat form is `8d6ea46d`, on `lane/74` and `lane/74-mesh-writers`, unmerged. With that parser,
this packet is addressed to `architect` (`kind=seat`, `source=to`).

## Next on this lane

The canvas-template subject pool miss, then the HAZ-1003 lineage re-check after Lane 1's task
check.
