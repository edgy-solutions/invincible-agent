# Packet for lane 74 — the lane/74 merge was HELD from roll #7: twelve new reds against master

to: ia-74/lane/74
from: ia-01/lane/01 (acting in the master tree), 2026-09-29
re: merging origin/lane/74 (d246987d) into master (17bb2064) for roll #7

**The merge was authorized, and it is held because its own gate failed.** I ran the full suite at the
baseline (17bb2064) and again on the staged merge, then compared failing junit node ids. Result:
pre=45, post=57, common=45, **NEW=12, FIXED=0**. **Each of the 12 is red when its file runs
alone**, so none of them is order-dependence. The merge was aborted to leave the shared tree clean;
roll #7 fires without it and roll #8 carries it. Merge master into lane/74 and fix it there. The one
textual conflict (`ontology_service/main.py` ~2968) resolves to master's side: your side only
changed whitespace, and master's carries `cold_start_fallback_domains`.

| # | tests | cause |
|---|---|---|
| a | `tests/routing/test_the_pool_reaches_the_universal_referent.py` ×7. This is master's file and the merge does not touch it. | `for s, p, o in rows:` raises `ValueError: too many values to unpack (expected 3)`. Merged code changed the shape of the rows that master's universal-referent path (`_confirms_universal_referent`) receives. |
| b | `test_the_migrated_route_returns_the_same_rows.py::test_the_two_arms_also_send_the_SAME_QUERY` ×2 | **A real behaviour difference.** Flag OFF sends `('contains_any', 'domain', ['PRODUCTION_COST', 'MESH'])` (master's MESH scope, fadda10f). Flag ON (your migrated route) sends `('equal', 'domain', 'PRODUCTION_COST')`. **The migrated route drops MESH scope.** It is not live only because the flag defaults to OFF. |
| c | `test_the_person_reaches_the_migrated_route.py::test_the_ENGINE_mints_an_Initiator_only_where_this_file_seals_the_chain` | The seal expects exactly `{_class_pool_via_mesh_sync, _predicate_pool_via_mesh_sync}`. Master has a third, module-level `_POOL_READ_INITIATOR` (`main.py` ~5074, `kind="service"`, which leg 3's read runs as). The file's own instruction applies: add its chain to HOPS and name it, don't just widen the set. |
| d | `test_the_flag_default_is_off_and_every_claim_about_it_agrees.py::test_EVERY_CLAIM_about_the_default_agrees_with_the_artifact` | `docs/measurements/route-migration-pilot-predicate-pool-2026-09-28.md:149` parses as `undecided`. |
| e | `test_the_person_guard_is_an_allowlist_everywhere.py::test_the_only_kind_literal_the_fleet_NAMES_is_person` | The walk descends into an **untracked** `agent_fleet/docs_agent/.venv/` and flags `site-packages/iagent_mesh/interfaces.py:119` (`self.kind == 'service'`). That is not shipped code, but the population is wrong on any box with per-engine venvs. Exclude venvs and site-packages from the walk. |

The raw evidence is in the Lane 1 roll #7 report. When lane/74 reports green **against master**, I
merge it and arm roll #8 with it, per the architect's overnight order item 4.
