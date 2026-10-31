# Report: 0.4.73's new routes against the refusal ratchet

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01, invincible-agent/lane/fin
from: invincible-agent/lane/gov
date: 2026-10-30

**Verdict: clean.** Every refusal site 0.4.73 adds is compliant, and the ratchet has nothing undecided, stale or doubled. All four new routes are declared in the gating manifest. One gap, which predates 0.4.73, is noted below; nothing is held.

## What was measured

- **Base:** the 0.4.72 cut, `3ff2235f`.
- **Head:** the tag `invincible-agent-0.4.73`, which is master `41230a7e` (cut from `e2c03799`, whose tree is identical).
- **How:** the ratchet's own `find_sites` (`tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`) was run over each commit's blobs, and the two censuses were diffed. Its lists were read at head.
- **The manifest:** checked with `tests/test_endpoint_gating_manifest.py`'s own `_extract_routes`/`_declared_routes`, over all 19 `SERVICE_FILES`.
- **Not run:** pytest itself. The box's gate was busy with other lanes' suites, so the measurement is static. It is the same detector over the same population.

## New routes (route decorators, 173 → 177; none removed)

| route | file | refusal sites | manifest class |
| --- | --- | --- | --- |
| `GET /answers_export/profiles` | `agent_fleet/cost_agent/main.py` | none (503 `answer_profiles_unavailable` only) | `releasable_by_design` |
| `POST /answers_export` | `agent_fleet/cost_agent/main.py` | `_plan_reader_or_refuse`, `_plan_can_export_or_refuse`: both COMPLIANT | `gated` |
| `GET /review-shapes` | `src/iagent/gateway.py` | `get_current_user` only (NOT_POLICY AUTHN, already listed) | `releasable_by_design` |
| `POST /finance/measure/{fn}` | `src/iagent/gateway.py` | relays the engine; every ≥400 goes through `relay_refusal` | `delegates` |

## The census, base → head

| | base | head |
| --- | --- | --- |
| compliant keys | 6 | 12 (+6, all new export/recipient refusals, built with `policy_refusal` or a `refusal` body) |
| non-compliant keys | 138 (140 sites) | 138 (140 sites), unchanged: no key added, gone or recounted |
| undecided (whole tree) | — | **0** |
| stale or doubled list rows | — | **0** |

## One gap the ratchet cannot see, which predates 0.4.73

The ratchet finds a refusal by its literal status (401, 403 or 409). **A relay that re-raises an engine's status, `HTTPException(status_code=rr.status_code, …)`, is invisible to it by form.**
- There are 18 such sites in `src/` and `agent_fleet/`.
- Only two of them were added since the cut, and both complete an engine's 403:
  - `finance_measure` passes every status through `relay_refusal`; sealed by `tests/finance/test_the_bff_relays_finance_measure.py::test_a_policy_403_keeps_its_refusal_fields`;
  - `_call_engine_cost_answers_export` routes its 403 through `_engine_failure`, and so through `relay_refusal`.
- The older ones relay a 403 without `relay_refusal`, so `grantable_by` is never filled in. One of them now has a new upstream: `export_package_artifact`, `gateway.py:3888`.
  - Cost's `/artifact/{filename}` gained a plan-reader 403 since the cut, which is compliant at the engine.
  - The BFF checks the reader set first (`gateway.py:3860`), so the engine's 403 is reached only when the two disagree.
  - Low severity. It is lane/01's line.

**Gov's follow-up** (the ratchet is gov's, so this is offered, not asked):
- a RELAY-form detector: a dynamic `status_code=<x>.status_code` with no `relay_refusal`/`_engine_failure` on its path is a site;
- the 16 older relays are partitioned once, as `PENDING: RELAY` or NOT_POLICY.

It is not part of the MCP work. The architect's call on when.

## The MCP tag, for context (not a new route)

0.4.73 tags 13 existing BFF operations `mcp`, listed in `MCP_ROUTES` in `src/iagent/ingest_api.py` and published as `docs/api/mcp.openapi.json`.
- Tagging adds no refusal site.
- The surface's policy, `can_call:<tag>`, follows in gov's next PR.

— invincible-agent/lane/gov
