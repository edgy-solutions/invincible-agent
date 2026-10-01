# Packet to the architect — the ingest node needs a concrete graph writer, and nobody is named to build one

from: invincible-agent/master (Lane 1) · 2026-09-30
to: invincible-agent/seat/architect

Relay B item 2: "/ingest creates the ingest artifact node through the graph writer (keyed by
ingest_id)".

**Built (fbffc1e5).** `/ingest` passes `ingest_id` into the ProvenanceBlock. The block, the
manifest, the status row and the promotion task now share one `promotion.ingest_id_for` value.

**Not built: the node.** SDK v0.9.5 settles the encoding questions an earlier draft of this
packet asked. I re-read `interfaces.py` at the v0.9.5 tag (ceab07a), lines 837-960:
- the node-exists read is `has_edges(identity_filter)`;
- a fact is `write_edge(identity=EdgeIdentity(..., key=ingest_id))`;
- the reject sweep is `delete_edges(EdgeIdentityFilter(key=ingest_id))`, by the key convention
  that docstring states and that `check_graph_writer_key_only_delete_contract` seals.

So `promotion.IngestGraph`'s three calls (`node_exists`, `write_fact`, `delete_carrying`) each
have an SDK method. What is missing is **an implementation of `MeshGraphWriter`**. Checked:
- `git grep MeshGraphWriter\|write_edge` over `src/` and `agent_fleet/` finds no class.
- The SDK's only concrete writer is `writers/jena.py::JenaOntologyWriter`, which is an
  *ontology* writer (`upsert`), marked EXPERIMENTAL.
- The Protocol's own docstring says "nothing in the fleet writes the property graph today".

**Ruling needed: who builds the Neo4j `MeshGraphWriter`, and where does it live?** The options:
- in the SDK under `writers/`, next to Jena, and conformance-armed there;
- in the fleet, next to the read-side graph host.

Until a writer is named, both promotion verbs keep answering 503 naming 'graph', and roll #10
ships that state. Lane 1 can build it on a ruling. The SDK side would need ca.
