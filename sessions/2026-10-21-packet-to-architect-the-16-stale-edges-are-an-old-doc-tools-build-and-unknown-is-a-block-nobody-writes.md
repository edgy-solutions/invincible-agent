to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: invincible-agent/lane/01, 2026-10-21
re: directive 2026-10-20 item 2: "trace which writer made them ... one packet, no fix yet"
relay: Chris

This packet carries no secret. No fix is proposed or made.

# The 16 stale edges came from doc-tools' own graph writer on a build before 09-17. "unknown/unknown/v1" means the manifest has no `format_identity` block, and no producer writes one

I checked this from code and git history only. Nothing was run against a cluster, and I did not read the live manifest's keys.

## 1. The 16 edges

These are the 16 that promotion `dr-c7c206bcbc97fb74` reconciled away as `not_in_reviewed_set`:
- 14 quote-wrapped values, such as `"2052-8002-92"`;
- 2 glued cells: `TYC1056344-1,\n9501815SP-1` and `160303P1,\n160303P001`.

**Only two code paths write `SUBJECT_TO`:**

| writer | where | could it make these 16? |
| --- | --- | --- |
| doc-tools `SustainmentPlugin.to_graph_queries` | `doc_tools/plugins/sustainment.py:2038-2039`: `MERGE (c:Component {mpn: part.affected_mpn}) MERGE (c)-[:SUBJECT_TO]->(n)`. Its RDF half is at `:2140`. | **Yes.** It writes `affected_mpn` exactly as extracted. It only MERGEs and never removes. Every sustainment run calls it, the vetted `sustainment/inbound/` path included (`doc_tools/assets/semantic_assets.py:855`). |
| the BFF's steward row-edit write | `src/iagent/promotion_stores.py:281-287` | **No.** It writes only the mpns a steward corrects, needs a matching `provenance_ingest_id`, and stamps `obtained_via`. |

These are **not** writers:
- `seed_sandbox_predicates.py`, the `setup/` ttl files and `src/iagent/defs/`;
- `notice_parts.py` and engine-o (they read only);
- doc-tools' corpus scripts (`pcn_corpus_run.py`: "no Neo4j").

`git log -S` for the four strings finds only docs, scoring scripts and one text fixture, which loads no graph.

**The build that made them is older than 09-17.** I checked this in history:
- doc-tools' own corpus validation (`docs/pcn-corpus-validation-2026-09-21.md:55-67`) shows the old build emitting `"2052-8002-92"` and 13 more quote-wrapped values from TYC-PCN-24-210412's "Alias Part Number(s)" column.
- The fixes came in four commits, each an ancestor of `133714c` (the build on this ingest's record), so today's build cannot produce these values:
  - `ad95e15` (09-17): a quote is a delimiter;
  - `044f007` and `ffb4b5f` (09-17): an alias column is not the part;
  - `4d3a943` (09-24): split glued tier-1 cells.

**Why no ingest names them:** ingest-status rows only began on 09-30 (`60e1c93d`), and `notice_id` only on 10-13, both after that build. That is why the record's `earlier_ingests` is `[]`. The earlier run keyed its notice node `PCN-24-210412`, the same `id` today's run MERGEs into, so its edges sat on the same notice.

**Not measured:** which run wrote them. The most likely is a vetted `sustainment/inbound/` drop of the same PDF before 09-17. It is not a seed.

## 2. `unknown/unknown/v1`

`promotion.py:297` computes the record's `format_fingerprint` with `format_fingerprint_from_manifest(manifest)` (`agent_fleet/utils/format_fingerprint.py:198`):
- That reads `manifest["format_identity"]`, which holds `{manufacturer, doc_type, doc_type_source}`, and needs `doc_type_source` in `{"extraction", "title"}` (`:63`).
- With the block absent, the answer is `unknown/unknown/v1`.
- `git grep format_identity` in doc-tools matches nothing. The producer has never written the block.

**The history:**
- The 10-07 vocabulary mismatch ("title" vs "extraction") was fixed by R1 (`279ef179`).
- R2 (`doc-tools/sessions/2026-10-08-packet-to-7f-r1-r3-answered-...`) moved the fingerprint onto the manifest and asked 7f to write the block.
- The block was never written, so every manifest-sourced record carries `unknown/unknown/v1`. The reader's docstring (`:208`) says so.

## What this leaves open (yours to route; no fix from me)

- **7f:** the RDF side was written by the same `to_graph_queries` run (`:2140`), so it may hold the same 16 values. I did not read Jena. Item 3's correction record names the 16 in `reconciled.removed`, so 7f's consumer can withdraw them by exact value.
- **7f:** writing `format_identity` into the manifest is the whole fix for the fingerprint. Until it lands, the trust table cannot key on a format.
- **A class, not one notice:** any notice ingested on a build before 09-17 may carry alias-column edges. Reconciling on promotion clears them one notice at a time, and only for notices that get promoted.
