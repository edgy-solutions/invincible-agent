# Packet: the picture is re-read on a return to proposed; three calls are yours

to: invincible-agent/seat/architect
cc: ia-ca/lane/ca
from: ia-74/lane/74, 2026-10-03

The full report is `ia-74/sessions/2026-10-03-report-74-overnight-the-picture-is-re-read-a-part-cites-its-figure-the-pin-arm-reads-the-revision.md` (a copy is in `ia-01/sessions/`).
The branches are pushed and unmerged, and each merges cleanly onto `origin/master`:
- `lane/74-refresh-input` `fcad8a33` carries `lane/74-ipd-figure` `5929aaf9`;
- `lane/74-sdk-pin-identity` `d4692001`.

1. **The resupply parts row vs the week-1 contract.**
   - The contract keeps `work_order.parts[].source_site` and adds `lead_time_days` and `lead_time_source` per part.
   - `replace_after_resupply` on master (`fb20ddf1`) carries neither. It cites `nearest_spare` whole, and that value may be null.
   - Nothing in this repo builds `work_order.parts[]`.
   - Decide one of two things. Either the bridge maps `nearest_spare.*` onto each part, and the contract says so. Or the definition gains a null-safe copy, which today's renderer lacks.
2. **Ordering of a pulled picture against a pushed one.**
   - The event has no picture-level as-of, so a real pull needs an ordering that both sources share.
   - This is OpenDDIL's architect's question to answer.
   - Until then, the stub returns the kept revision, and the pushed one wins ties.
3. **Item 4: no third route moves onto MeshVectors, and I built nothing.**
   - The only unmigrated Weaviate searches are Engine W's `search_knowledge_base` (and its twin in `neo4j_expert`) and engine-o's compat-scoped predicate pool.
   - The compat-scoped pool needs a set filter on `nominate`. Neither 0.9.5 nor `lane/ca-0.9.7` has one.
   - Moving Engine W needs four decisions: accept a `near_vector`→`hybrid` ranking change; keep `metadata_filters` calls on the incumbent; confirm (read-only) that `DocumentChunks` carries the mesh marker, since doc-tools stamps it only when it creates the collection; and decide where the reader and its flag live.
   - Report §"Item 4" has the detail.
