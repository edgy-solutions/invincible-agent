to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-10 (03:50Z; Monday 11-09 21:50 CT)
supersedes: 2026-11-09-handoff-lane-01-0-4-82-rolled-rev-229-walk-today.md

# 0.4.83 is cut and not rolled; the walk is Tuesday 09:00 CT

## NOW

**Chris's 21:16 CT block (11-09), verbatim as relayed:** "walk slipped to Tuesday 09:00 CT; rehearsal didn't happen;
lock free; cut 0.4.83 tonight, do not roll; readiness re-read 07:00 on 0.4.82".

- **Sandbox stays on 0.4.82 (revision 229).** Nothing rolls before the walk.
- **07:00 CT (13:00Z) Tuesday:** the readiness re-read runs on 0.4.82. The person does the logins: `authz_id` read
  from the session, non-empty `/me` entitlements, `/me/paused-runs`, the propose-card text. Never mint a token.
- **09:00 CT (15:00Z) Tuesday:** the OpenDDIL walk. 74's rehearsal did not happen. Lane 1 does not roll, fire or
  walk until 74 or Chris says so in writing after the walk.

**The cut, PR #326 (`lane/01-cut-0-4-83`, `wt\01\cut0483`, head `f614ad04`).** It holds Chart 0.4.83, cortex
`db45763` (`sha256:b320303c…`, measured with controls) and the dated CHANGELOG. **Merged at `3a23fce4`** (second
parent `f614ad04`, on master; CI 20 green and 3 skipped, join ratchet 24). **Chris tags `invincible-agent-0.4.83`
at `3a23fce4`**; nothing is published until then. Not in it:
- dag-tools 0.13.0, which is only on dag-tools' `release/0.13.0` branch: not merged, not tagged, not on PyPI. It
  can join before the tag by a follow-up PR.
- iagent-mesh v0.9.17, which is untagged.
- D's Lane 1 half.

**Before 0.4.83 rolls (after the walk):**
1. Chris's Topaz sync for `obsolescence-deciders` (#314).
2. The values diff, shown to the approver.
3. The roll.
4. Re-materialise `ev_fixture` and the three refusal assets.

**Attestation is done on Lane 1's side.**
- #324 merged at `de1873c2`. #325 merged at `4f2dac35`: the act refuses on the served `excluded`, and ingest-v1
  1.9.1 declares `TaskPayload.attestation`.
- Chris confirmed that `self_attested` stays read from `dropped_by`; it is a fact on the record and decides nothing.
- Packets are placed, uncommitted:
  - master `sessions/`: gov, `viewer_may_attest` withdrawn.
  - `cortex-ui/sessions/`: the route reads `excluded`. Three seal arms move when Cortex re-pins `PRODUCER_REF`:
    lines 105 and 111 go red, and the 124 tripwire goes red as intended.
- The seam `_declared_attestation` returns None until gov names the row.

**Langfuse:** unchanged since the second restart (11-10 01:06Z). perf owes "trace landed" or "401 persists".

## Next, in order

1. After Chris tags: check image-digests `images` against `expected` on the release run. A tag is never moved.
2. **fin's #312 → #316 → #319** as each is resolved.
3. **ADR-0065 D**, Lane 1's half: the `obsolescence_resolution` workflow row and the runner-side trigger, on the
   0.9.16 models. The fleet pin to 0.9.16/0.9.17 is gov's rail; master is on v0.9.15.
4. **7f's ADR-0063 §2–§4** docs PR.
5. After the walk: the 0.4.83 roll order above.

## Measured, not yet acted on

There are three reds on master that are not in the census:
- `tests/test_case_projection.py`
- `tests/test_the_case_panel_reads_its_stage_options_and_release.py`
- `tests/test_an_origin_suggestion_runs_as_a_case.py`

## Queued, unchanged

- #283 alignment (ADR-0067) and forks 1+3; ADR-0066.
- The alice Topaz delete; NetworkPolicy.
- Items `01M6QGKGVF12QW1REN9K0K1HMB` and `01M6QGKFTKSD18ZAPMA285F25X`.
- The FLOW_DECOMPOSITION projector row (`wt\01\flowrow`).

## Worktrees

All under `C:\Users\cnogr\git\wt\01\`. With a venv: `cut0482`, `cut0483`, `taskid`, `train`, `ontology`, `intake`,
`attest`.
