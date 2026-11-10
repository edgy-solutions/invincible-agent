to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-10 (04:05Z; Monday 11-09 22:05 CT)
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
parent `f614ad04`, on master; CI 20 green and 3 skipped, join ratchet 24).

**THE TAG IS HELD (Chris, 11-09 ~22:00 CT):** "hold the 0.4.83 tag ... I tag 0.4.83 at the new head tomorrow after
the walk." Every PR merged before the tag rides 0.4.83, with its CHANGELOG entry under the dated 0.4.83 heading.

The architect's overnight order, via Chris (11-09→10). After the walk, in this order:
1. tag 0.4.83
2. Topaz sync
3. values diff
4. roll
5. re-materialise
6. doc-tools roll
7. tr's `propose` run
8. wb 0.1.9
9. 74's rehearsal

Lane 1's part:
- Fold #310, #322 and #323, and fin's #312, #316 and #319 **as fin resolves each** (fin resolves; Lane 1 does
  not push to fin's branches).
- Pin PRs as tags appear: dag-tools 0.13.0 (this lane) and iagent-mesh v0.9.17 (gov's).
- LANGFUSE_HOST moves from the Secret to the ConfigMap.
- `attestation` is read from the content-kind row once ca ships the field.
- D's `obsolescence_resolution` row.
- Item: `notice.mfr_source` derivation (gov's ask to 7f is Lane 1's).
- Review perf's tracing PR #327 (`lane/perf`). **#327 does NOT ride 0.4.83** (Chris, 11-10: perf is re-basing on
  provenance-telemetry). Do not merge or fold it before the tag.
- 07:00 CT readiness re-read on 0.4.82: six items, no synthetic event.

**PR #328 (`lane/01-dag-tools-0-13-0`, `wt\01\dag0130`, head `9405874f`): dag-tools 0.13.0.**
- dag-tools 0.13.0 is published:
  - tag `bed53b9`, on PyPI;
  - `central-gateway` `9c9a99ee…`, `user-deployment` `d385757d…`;
  - `:0.13.0`, `:0.13` and `:sha-bed53b9` resolve to one index each; a missing tag gives 404.
- No four-sites packet for 0.13.0 reached any inbox. The four sites used: the root pin, the two digests and the
  brokered-read seal, whose version-gated xfails were removed (5 pass).
- finance_agent and data_analyst are not moved.
- The CHANGELOG adds #310, #322 and #323 to the 0.4.83 table.
- **MERGED at `af87f0c0`** (^2 `9405874f`, on master; CI 21 green and 3 skipped, join ratchet 24).

**Two KNOWN reds (neither is #328's). Ruled 11-10 ~04:07Z, the architect via Chris:**
- `test_chart_version_tracks_chart_content` has been red on master since #310 (`57f16df2`); every fold into the held
  version reds it, and CI runs no pytest.
  - **Ruled:** "A final commit just before the tag touches Chart.yaml with a comment naming the head it releases,
    so the version sits on the content it ships. No bump to 0.4.84, no seal change. Until then the red is known
    and named in the handoff."
  - That final commit is Lane 1's last PR before Chris tags.
- `test_oidc_broker_chart` walkers [erin|chris]: #314 gave alice `obsolescence-deciders`, a cell group, and not the
  walkers.
  - **Ruled:** "the walkers mirror alice, so erin and chris join obsolescence-deciders in the same PR that fixes it.
    gov's to do; it rides 0.4.83."
  - The packet to gov, with the ruling appended, is in master `sessions/`.
  - users.yaml changes, so it needs Chris's topaz_sync before the roll.

**mesh v0.9.17 was tagged at 03:49Z.** Gov's pin PR was not open at 04:05Z.

**Fin's chain:** #312 **MERGED at `7a9b19e4`** (^2 `24057dea`; CI 21 green and 3 skipped, ratchet 24). Fin's resolve
opened `## 0.4.84 — not yet cut` for its entry. **The pre-tag CHANGELOG + Chart.yaml commit moves that entry under 0.4.83
and deletes the 0.4.84 heading.** #316 and then #319 wait on fin's resolve. Packet placed: entries go under 0.4.83.

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

1. Merge #328 on green. Fold fin's PRs as fin resolves each, and gov's v0.9.17 pin PR. Then, before the tag,
   a final CHANGELOG tidy, plus the Chart.yaml answer.
   After Chris tags: check image-digests `images` against `expected` on the release run. A tag is never moved.
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
