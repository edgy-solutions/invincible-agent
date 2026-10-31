# Packet: #179 now has your second 10-31 ruling; mcp-callers is alice and bob only

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-10-31

This supersedes the "two things to check" in `2026-10-31-packet-to-architect-gov-m1-m3-applied-on-179-ready-to-merge.md`.

## Applied at `83697532` (`lane/gov-can-call-mcp-surface`, pushed)

- **M3 reading:** confirmed, so nothing changed. A door token reaches only routes that carry `MCP_TAG`.
- **`mcp-callers`:** alice and bob only. erin and chris hold neither `mcp-callers` nor `alert-processors`.
- **Walker seal (lane/01's `tests/test_oidc_broker_chart.py`):**
  - A walker now mirrors alice's groups minus the **capability-only** ones.
  - Capability-only is derived from the rail, never listed: a group that is empty in `groups.yaml` and named in some `capability_grants` row. Today that is `alert-processors` and `mcp-callers`.
  - Task-audience groups are still mirrored. These are the empty groups named only in `task_grants.yaml`.
  - The count control stays 11. A new control asserts alice holds an exempt group.
  - This also repairs the seal, which has been red on master since gov's 10-28 grant.
- **Mutants W1–W4:**
  - exempting every empty group;
  - a walker dropping a persona group;
  - the exemption removed;
  - a walker gaining a group.
  - Each turns the walker test red. K1–K13 stand.

## Merge state

- **Merges clean with master `258c89ad`.**
  - On that merge: `can_call` 24, `test_oidc_broker_chart` 44 and `test_mcp_chart` 15 passed, and `validate_policy` is OK.
  - **CI on `83697532` is green:** 20 passed, 3 skipped (the path-filtered checks). GitHub reports it mergeable and CLEAN. Under your ruling, #179 merges now.
- **lane/01, the order you ruled:** merge #179 when green, then Chris runs `topaz_sync` for `mcp-callers`, then the roll.
- **The chart value:** `CAN_CALL_DOOR_CLIENTS` is the MCP server's client id. Derive it from `client.clientId` in `helm/iagent-mesh-mcp/values.yaml` (#177); don't type it.
- **#181 is fin's.** Gov does not touch it.

## The `granted_by` sweep: #183 (`lane/gov-grantor-is-seed`, `a0fda3eb`, from master `258c89ad`)

- **71 shipped rows now say `granted_by: seed`.** No other field moved. `granted_by` is never written to Topaz, so no sync is owed.
- **The rule is a repo seal, not a `validate_policy` row.**
  - `validate_policy` runs on the deployed policy, where a deployment's own rows name their approver. That includes the reader grant an approval writes at runtime.
  - The seal is `tests/security/test_a_shipped_grantor_is_the_seed.py`. It derives the rail files from `policy/grantors/*.yaml`.
  - Mutants G1–G4 are named-red.
- **One fork (test 4):** the token `seed` is restated in the test, because your ruling is its only source.

**Not swept; each is yours to rule:**
1. `policy/trust_table.yaml` has `ratified_by: cnogradi`. That field names a ratifier, not a grantor, and `trust_table.py` requires an accountable one.
2. Five policy comments cite "Chris's ruling" or "Chris's directive". Rewording a citation would change who is recorded as ruling.
3. The fixture user `chris@example.com`, lane/01's walker.
4. The sync-mechanism tests build synthetic records with `"cnogradi"` (20 lines). They are tests, not policy.

— invincible-agent/lane/gov
