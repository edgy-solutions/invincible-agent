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
4. Size: 500 notices in scope (superseded by round 48: the scan counts only the caller's own notices); 422 `export_range_too_large`, also under check_only. An empty range is 200.
5. Domain: other domains' notices are dropped silently before the shared preflight; a range never enumerates them.
6. Audit: the record gains `range: {from, to, field}` only when a range was given; the id form's record is unchanged.

Census of sites (gateway.py unless named, line numbers on the pre-change master): 14246-14248 limits and date regex; 14408-14415 `ExportNoticesRequest`; 14420 `_record_export`; 14425-14455 `_export_notice_domain` (reused); 14457-14503 `_export_preflight` (reused, unchanged); 14506-14572 the POST route (selection, check_only, audit, filename); 14577-14670 the GET batch route (day parser, 92-day check moved into the shared parser); `ingest_status.py` ~798 `list_mine` (the new `list_by_created` sits beside it); `docs/api/cortex-bff.openapi.json` regenerated; `tests/routing/test_the_export_profile_server_is_sealed.py` (unchanged, still green).

Seals: `tests/routing/test_export_by_range_is_the_id_form_with_another_selector.py` (27 tests). 13 mutants, all killed, text mode utf-8, applied-asserted, restored with cmp.

Next: gov reviews; cortex-ui reads the packet for the request shape.

## Round 48 - architect ruling on #364: the cap counts only the caller's notices

Architect via Chris, 2026-11-11 (stays on 0.4.86; a forward commit on #364, no merge sha agreed yet):
1. Silently omitting other domains' notices from a range is kept.
2. The scan cap counts only receipts in the caller's domains. `export_range_too_large` states the cap (configuration) and never a count; no message, detail field or log line on that path carries one.

Done: the 5000-receipt scan cap is gone. `_export_range_ids` reads the store a page at a time (keyset, `list_by_created(start, end, limit, after=)`), scopes each receipt to the caller's domains as it arrives, counts only those against the 500 cap and stops at the first one past it. A notice's domain is not a column of the store (it is in the decision record or the open review task), so the scope is applied per page, inside the scan, not in the SQL. The refusal text is "a range may select at most 500 notices; narrow the range". The API schema did not move (`--check` is 0).

Seals (32 in the file): 4a under the cap beside another domain's 20 receipts is admitted, control over the cap is refused; 4b the refusal's whole body carries no number but the cap, control a detector that catches a body with a count; keyset paging; no length is formatted in the branch's source. Mutants: 14 of 14 killed, including "scan before domain scope" and "count back in the reply".
