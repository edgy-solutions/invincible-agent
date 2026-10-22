to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01
date: 2026-10-22
re: HEMCG2-2683 replacement pairs (your note to 7f, item 2 is Lane 1's)
relay: Chris

Committed on lane/01-202. A copy is placed, uncommitted, in doc-tools and cortex-ui sessions/. This report carries no secret.

# `replacement_mpn` is already the term, end to end. Promotion cannot correct or remove a replacement, because `REPLACED_BY` carries no notice scope

This is code-reading only, tonight. No code changes; the freeze holds, and item 2 is built after the dry run as you said. Every claim below is a file and line I read, not a run.

## 1. The term exists. 7f needs no ruling

- **doc-tools** already writes the relation at ingest. `doc_tools/plugins/sustainment.py:2041-2045` writes `MERGE (c)-[:REPLACED_BY {ltb_date: part.ltb_date}]->(alt)` from `part.replacement_mpn`, beside `SUBJECT_TO`. The Jena form is `pcn:hasReplacement` at `:2149`.
- **The BFF wire** already pairs the two by index. The review sensor builds `{affected_mpn, replacement_mpn, needs_review}` from `review_items` field paths `parts[i].affected_mpn` / `parts[i].replacement_mpn` (`src/iagent/defs/extraction_review_sensor.py:101-117`). `GET /ingest/{id}/extraction` serves a `replacement_mpn` row under the same `part_index` as its affected part (sealed in `tests/test_ingest_review_card_routes.py:240-242`).
- **So, for 7f:** emit the right column as `parts[i].replacement_mpn` on the SAME `i` as `parts[i].affected_mpn`. Never emit it as its own `parts[j].affected_mpn`. That alone fixes the review card and the ingest graph for HEMCG2-2683; the BFF needs no change for that part.
- **One thing for you to rule on, about `ltb_date`.** The ingest edge puts the affected row's `ltb_date` on the `REPLACED_BY` edge itself (`:2044`). It does not put it on the replacement node. If "replacements never inherit ltb_date" includes the edge property, that is a 7f change. If it means only the node, it is already true.

## 2. What item 2 actually needs from Lane 1: promotion cannot reach the replacement

| surface | today | read at |
| --- | --- | --- |
| review row | carries `replacement_mpn` | `gateway.py:1537`, sensor `:101-117` |
| a steward's row edit | keyed on the affected `mpn` only: `corrected` = `{mpn, corrected_mpn, evidence, evidence_ref}`; no replacement key | `agent_fleet/restate_analyst/steward_correction.py:42-45` |
| promotion's graph write | `apply_row_edits` and `remove_notice_edges` touch `SUBJECT_TO` only | `src/iagent/promotion_stores.py:293-306, 454-515` |
| the edge to correct | `(Component)-[:REPLACED_BY {ltb_date}]->(Component)`: **no `provenance_ingest_id`, no notice** | doc-tools `sustainment.py:2044` |

The last row is the blocker:
- `SUBJECT_TO` points at a `SustainmentNotice` that carries `provenance_ingest_id`, so promotion can delete "this notice's" edge.
- `REPLACED_BY` joins two shared `Component` nodes and records no notice. Promotion can add one, but it cannot tell which notice asserted an existing one. So it cannot safely correct or remove one: two notices naming the same pair would share the edge.

## 3. Proposal, for your ruling

1. **7f**: stamp `REPLACED_BY` with the notice's `provenance_ingest_id`, and MERGE on it, so each notice gets its own edge. This makes the edge per notice, the same as `SUBJECT_TO`.
2. **Lane 1, after the dry run**:
   - Add an optional `replacement_mpn` to the `corrected` and `added` row-edit shapes. Absent means unchanged; an empty string means "no replacement".
   - Make `apply_row_edits` and the reconcile pass delete or write this notice's `REPLACED_BY` alongside its `SUBJECT_TO`. A deleted row drops both edges.
   - Seal the HEMCG2-2683 shape: 22 pairs promote to 22 `SUBJECT_TO` + 22 `REPLACED_BY`, and no replacement is subject to the notice.
3. **Cortex**: a FIX on the replacement cell sends `corrected: {mpn: <affected>, replacement_mpn: <new>}`. Until (2) is live, that FIX has no wire shape. Please don't build it to send `corrected_mpn`: that rewrites the affected part.

**Alternative, which I don't recommend**: promotion writes `REPLACED_BY` itself and ingest stops writing it. That splits the relation from its `SUBJECT_TO` sibling, and two writers would own one notice's edges.

## 4. What I did not check

- Whether 7ff203e8 (HEMCG2-2683) has been promoted. If it has, Neo4j holds 44 `SUBJECT_TO` edges for it, 22 of them on replacements. Reading that needs a graph read I have not been approved for. Either path fixes it: a promotion that deletes the 22 rows, or a re-extraction after 7f's fix plus the reconcile.
- Whether doc-tools already detects an "Alternative Part Number" header as a replacement column (`table_text_layer.py` / `sustainment_merge.py` have many replacement hits). That is 7f's to say.
