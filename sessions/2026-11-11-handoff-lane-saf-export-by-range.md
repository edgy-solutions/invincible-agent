---
to: invincible-agent/lane/saf
from: invincible-agent/lane/saf
date: 2026-11-11
---
# Handoff

Newest saf handoff. Rounds 44 and 45 are in `2026-11-11-handoff-lane-saf-export-grants-known-profiles.md` (on #361, not yet merged).

## Round 46 - rulings owed, recorded here and not on #361

Architect via Chris, 2026-11-11: #361 (Job 26, head c085220b) merges if it is green with seals by 01:30Z; otherwise it leads 0.4.86. It was green at that head and was not touched again. Gov reviews that sha; Lane 1 merges it. This PR is independent of #361: it branches from master and edits none of #361's files.

## Round 47 - Job 27: select by range on POST /ingest/export/notices (targets 0.4.86)

Decisions (each is also in the PR body):
1. Selection: `notice_ids` XOR `range:{from,to}`; both or neither is 422 `export_selection_invalid`. An empty id list keeps `export_notice_ids_invalid`.
2. Bounds: YYYY-MM-DD UTC days, both ends inclusive, from <= to, at most 92 days; one shared parser (`_export_parse_range`) now serves the GET batch route too.
3. Timestamp: `created_at` (receipt). Not `updated_at`, not the promotion time; `exportable_states` decides eligibility.
4. Size: 500 notices in scope, 5000 receipts scanned; both 422 `export_range_too_large`, also under check_only. An empty range is 200.
5. Domain: other domains' notices are dropped silently before the shared preflight; a range never enumerates them.
6. Audit: the record gains `range: {from, to, field}` only when a range was given; the id form's record is unchanged.

Census of sites (gateway.py unless named, line numbers on the pre-change master): 14246-14248 limits and date regex; 14408-14415 `ExportNoticesRequest`; 14420 `_record_export`; 14425-14455 `_export_notice_domain` (reused); 14457-14503 `_export_preflight` (reused, unchanged); 14506-14572 the POST route (selection, check_only, audit, filename); 14577-14670 the GET batch route (day parser, 92-day check moved into the shared parser); `ingest_status.py` ~798 `list_mine` (the new `list_by_created` sits beside it); `docs/api/cortex-bff.openapi.json` regenerated; `tests/routing/test_the_export_profile_server_is_sealed.py` (unchanged, still green).

Seals: `tests/routing/test_export_by_range_is_the_id_form_with_another_selector.py` (27 tests). 13 mutants, all killed, text mode utf-8, applied-asserted, restored with cmp.

Next: gov reviews; cortex-ui reads the packet for the request shape.
