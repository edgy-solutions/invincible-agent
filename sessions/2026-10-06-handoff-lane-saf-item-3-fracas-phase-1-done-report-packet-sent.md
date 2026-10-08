---
to: lane/saf
from: lane/saf
date: 2026-10-06
---

# Handoff — all three work-order items closed out this session

Read this whole, once, before picking anything up. Short version: **nothing is blocking on
lane/saf right now.** All three items are either done-and-committed or correctly deferred with a
stated, checkable reason. The next substantive step is Lane 1 merging the shas below, or the
architect answering ADR-0056's two named open questions.

## Item 1 — Docs entitlement switch-on (GATED) — DO NOT FLIP

`ENABLE_AGENTIC_AUTH` stays off. Prerequisites `f843d2d8` are on master; the gate `e15877ef`
has **not** merged — it lives only on `lane/74-docs-serve-entitlement`. Checked by reading that
lane's own packets/commits, at master `2b6fe0f6`. Nothing to do here until that gate lands on
master; re-check at that point, don't re-derive from scratch.

## Item 2 — HAZ-1004 / seal 7 / deferral-risk refusal — DONE

- `tests/safety/test_seal7_the_ladder_routes_not_just_alice.py` (ADR-0051 seal 7), commit
  `4f6dd2b3`.
- HAZ-1004 measured **Serious**, not High — stated correction, not silently fixed.
- The deferral-risk refusal that's failed since 9/26 is a Jena→Neo4j sync gap owned by lane
  7f/doc-tools, not fixable in this repo. Diagnosed, not patched.
- HAZ-1004's walk-census row deliberately deferred — no confirmed live-cluster/Topaz access
  this session, named as the reason.

## Item 3 — FRACAS Phase 1 — DONE, all three sub-deliverables committed

1. **ADR-0056** (`docs/adr/ADR-0056-fracas-phase-1-what-failed-on-this-part-across-programs.md`)
   + README index row — commit `fe8591fd`.
2. **The verb** `what_failed_on_this_part` (`measures.py`, `main.py` VERBS, two new TTL classes
   `safety:FailureRecord` / `safety:FailureRecordSet` in `safety_extension.ttl`) — commit
   `823b02d0`.
3. **The seal** — `tests/safety/test_fracas_phase1_what_failed_on_this_part.py`, 8/8 — commit
   `c7da3110`.
4. **The walk-census row** — `safety-what-failed-on-this-part` in `walk-census.yaml` + Q4 in
   `safety-walk-sheet.md`, plus a small gap closed along the way: `part_number` had no referent
   in `slots.py`'s `_REFERENT_KIND` map (every other spoken-mandatory slot in this engine has
   one). Added it, pointing at `safety:SafetyCriticalItem` per the ADR's own decision. Commit
   `3e0aace2`.

**Why the walk-census row is the REFUSAL only, not the populated path:** the populated answer is
a flat JSON object (`failures`, `platforms`, `systems_of_record_cited`), not a card — no
`rendersAs` binding or `ROW_KEY` archetype exists for `safety:FailureRecordSet` yet. Capturing a
`drawn` disposition for an unwired archetype would assert cortex-ui behaviour this engine has no
part in. The populated payload IS captured and shown in the walk sheet, for a human walker's
reference, but it is not a census row. Mirrors `assess_deferral_risk`'s own precedent exactly
(its "if the slot IS supplied" follow-on was never a row either).

Verified before each commit: `tests/safety/` 273 passed / 3 skipped (same count as before this
session's additions — only the intended 8 new tests appeared); both walk-census tests green;
`test_no_new_sibling_name_bleed_in_definitions` green.

**Two open questions ADR-0056 names for the architect, not decided here:**
1. `SystemOfRecordConnector.lookup(value) -> dict | None` is one-to-one; FRACAS's real query is
   one-to-many. Phase 2 needs either a new protocol shape or a fan-out composition.
2. The verb performs no per-caller filtering by program membership — no existing mechanism
   covers filtering a live verb's multi-row output (only ingested-artifact visibility exists).

Phase 2 (real connector, live data, OpenDDIL's edge entry) is explicitly out of scope and waits
on OpenDDIL's dry run, per the work order.

## Commits this session, in order

`4f6dd2b3` → `823b02d0` → `c7da3110` → `fe8591fd` → `3e0aace2`. All pushed to `lane/saf`.

## Next step if you are lane/saf picking this back up

Nothing is in flight. If you land here cold: confirm the report packet below actually reached
seat/architect (it's untracked in the shared tree, placed not committed — check it's still
there, since another lane or the architect may have already picked it up and it could be gone).
If it's gone, that's success, not a problem. Otherwise there is no open thread of mine to
resume — wait for the architect's next assignment or re-check Item 1's gate.

## Report packet placed (untracked, shared tree)

`C:\Users\cnogr\git\invincible-agent\sessions\2026-10-06-packet-to-architect-three-items-item-3-fracas-done.md`

## Follow-up work order (2026-10-07) — status

**1. HAZ-1004 severity.** Matrix: `setup/ontologies/safety_risk_matrix.ttl` line 194:
`[] a safety:MatrixCell ; safety:whenSeverity "III" ; safety:whenProbability "B" ; safety:yieldsRiskLevel safety:Serious .`
Severity III is `safety:Marginal` (about lines 109-110); line 96 records the matrix as verified against
MIL-STD-882E Table III on 2026-09-12. HAZ-1004 (`agent_fleet/safety_agent/entities.py` about line 221):
severity "III", probability "B". So severity = Marginal (III); risk level = Serious.
"High" and "Serious" are the SAME axis (risk level: High > Serious > Medium > Low), but neither is a
severity category (Catastrophic I, Critical II, Marginal III, Negligible IV). The work order's "high" was
wrong on value (the cell yields Serious, not High) and loosely worded as a severity. My "Serious" was
right as a risk level; my phrasing of it as "severity" was wrong and is corrected here.

**2a. Seal.** `4f6dd2b3` covered only the first act (ladder routes beyond alice to
`safety_concurrence`, carol). The risk_acceptance_high path was not covered. Now sealed in `88f65457`
(`tests/safety/test_seal7_the_ladder_routes_not_just_alice.py` section 6): High acceptance lands in
`risk_acceptance_high`, which only alice holds; parametrized controls differing only in risk level
(HAZ-1004 serious -> alice's serious audience; HAZ-1003 medium -> bob) do not reach the high audience.
14 passed. Mutation (hardcoding the high audience in `policy/workflows/safety_acceptance_direct.yaml`)
killed 3 tests; restored. There was no fix to run it against, so the mutation is the red proof.

**2b. HAZ-1004 walk-census row: NOT RUN, blocked.** Unblocked by a Lane 1 packet that reports a roll
whose image sha contains `88f65457` (or the merge carrying lane/saf's safety commits `3e0aace2`,
`88f65457`) onto master. Check: `git merge-base --is-ancestor 88f65457 origin/master` exits 0 AND a
Lane 1 packet names the rolled revision. Until both hold, do not fire it.

**2c. Deferral-risk refusal** is doc-tools 7f's. Packet (untracked, in invincible-agent/sessions/):
`2026-10-07-packet-to-7f-safety-deferral-risk-refusal-failing-since-0926-hypothesis-only.md`.
The Jena-to-Neo4j gap is labelled hypothesis; no live store was queried.

**3. Item 1** still waits on Lane 1 merging `e15877ef` (only on `lane/74-docs-serve-entitlement`).
Nothing to do until it lands on master.

## Merge-gate red (2026-10-07) -- fixed in 241f365c

Lane 1's gate named `tests/safety/test_the_walk_sheet_matches_the_engine.py::test_the_parser_finds_the_sheets_three_prompts`.
Cause: `3e0aace2` added a fourth sheet prompt; the positive control listed three. CONTROL was stale,
SUBJECT was right. Control now lists four (test renamed ..._four_prompts), still exact-match. Reproduced
red alone on tip; the test file is identical at 2b6fe0f6 where the sheet has 3 prompts (so green there).
Ran alone (12 passed) and tests/safety/ + walk-census + two routing walk tests (348 passed, 3 skipped).
Next: Lane 1 re-merges by sha, rolls, then sends the helm revision for the HAZ-1004 walk-census row.

## ADR-0056 Q2 built (2026-10-07) -- commit 0b60e7e7

Proposal 2 (per-caller program filter) accepted and built. Files: `policy/overlays/sample/platform_programs.yaml`
(PLT-ALPHA->SANDBOX_PROGRAM_ALPHA, PLT-BRAVO->SANDBOX_PROGRAM_BRAVO; PLT-CHARLIE unmapped on purpose),
`PLATFORM_PROGRAM_OVERLAY_DIRS` (loader in measures.py; chart default in `configmap.yaml`),
`agent_fleet/utils/program_membership.py`, the gate `_visible_records` in `measures.py`, the 503 in
`main.py`, `SANDBOX_PROGRAM_BRAVO` (alice) in `policy/program_members.yaml`.
Seal: `tests/safety/test_fracas_program_filter.py` (15 arms, controls differing in membership / mapping
row / Topaz state). Mutations: drop check -> 9 reds; unmapped-allow -> 2; swallow-to-empty -> 3;
no-caller-allowed -> 1; first-program-only -> 3.
DEPARTURES from the proposal (also in the packets): identity is `current_caller()`, not `user_email`;
the engine uses its own copy of the Topaz check, not `human_tasks`.
STILL TO DO BY A HUMAN / LANE 1: seed `SANDBOX_PROGRAM_BRAVO` in Topaz (program sync, a live write);
roll engine-safety and the configmap. NOT VERIFIED LIVE: that dispatch carries the user's token for
this verb; if it carries svc:supervisor the verb answers empty for everyone.

## Update 2026-10-07 -- no_person refusal (supersedes "answers empty for everyone")
The svc / no-caller case no longer answers empty: `what_failed_on_this_part` raises
`measures.NoPerson`, `main.measure` answers 422
`{"error":"no_person","message":"this verb answers for a person; the caller carries none","fn":"what_failed_on_this_part"}`.
BOTH `svc:*` and an unresolved caller refuse; a real person with no membership still gets the empty 200.
No pre-existing `no_person` exists anywhere in the fleet (grep of every worktree); the body copies the
sibling 503 in the same handler, status 422 as the gateway's `no_requester`. Walk sheet residual
corrected: assessDeferralRisk IS registered; its SUBJECT SCOPE is the open question.

## Update 2026-10-08 -- SystemOfRecordQuery consumer + second FRACAS verb
- SDK: safety engine pyproject pinned by full sha 60e56c972b209617dbe85cff6ff606c957e120ad (same git+https
  style as every engine and the root pin; root pyproject UNTOUCHED, still 012a24fb, so the root venv lacks
  `SystemOfRecordQuery` and the one Protocol arm skips there; it passes under `uv run --with` the pinned sha).
  safety_agent/uv.lock: 2-line change (iagent-mesh source rev only).
- `failure_source.py`: connectors implementing the Protocol (fixture = the sandbox connectors), `gather(by,value)`
  cites `<connector>:<record_id>`; `measures` no longer holds FAILURE_RECORDS. All first-verb seals unchanged and green.
- Verb 2 `failure_trend_for_this_platform_by_month`: bucket `observed_on`, calendar month, no timezone, empty months
  zero-filled between first/last VISIBLE month, unparseable dates under `undated`. New class safety:Platform (+ instances,
  slot `platform_id`), safety:FailureTrend. Registries touched: entities.PLATFORM_IDS, main.VERBS, measures, slots,
  instances, safety_extension.ttl, walk-census row (refusal-only: no rendersAs/ROW_KEY for FailureTrend), walk sheet Q5,
  sheet-test expected list, ADR-0056 amendment.
- Stale claims fixed: ttl FailureRecordSet comment said "no per-caller filtering".
- STILL BLOCKED: HAZ-1004 walk row (needs Lane 1 roll packet naming revision with my shas).
- Walk-sheet residual re-corrected: the architect's 2026-10-07 ruling (via lane/gov packet) is a subject-scan DOMAIN exclusion
  (MAINTENANCE class outside the SUSTAINMENT+MESH scan), superseding lane/saf's manifest hypothesis.
