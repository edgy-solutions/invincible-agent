to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-11-10 (04:05Z; Monday 11-09 22:05 CT)
supersedes: 2026-11-09-handoff-lane-01-0-4-82-rolled-rev-229-walk-today.md

# 0.4.83 is cut and not rolled; the walk is Tuesday 09:00 CT

## NOW

**11-11 ~02:30Z: THE ARCHITECT'S FOUR ADR-0068 RULINGS ARE APPLIED.**
- **ADR-0068 is DRAFT PR #347,** head `6be220db`. **Do not merge.** It stays Proposed until the architect and OpenDDIL review it.
- **Identity:**
  - `entry_id` and the task occurrence ids are UUIDv7s, minted once by the writing tier. A replay hands back the minted id.
  - A uuid5 over (case, step, transition) is `dedupe_key` only, a lookup key and never an identity.
  - §3 and the item 2 report are both amended.
- **The per-viewer PR is the FIRST on the train after 0.4.85.** It now also carries a **per-viewer Needs-you read** (what waits on this viewer, by kind, label-scoped). The item 1 report names it in its section 5. The UI stops composing the count.
- **The leak is on the board in #348** (item `01M745DH4FN8MN600EQWA58FT6`, worktree `wt\01\leak`). It is board-only, with no CHANGELOG entry. **Merge it on green by head sha** (`fe0d0a47`), using `waitci-348.log`.
- **Packet to the architect:** `sessions/2026-11-11-packet-to-architect-from-lane-01-adr-0068-is-draft-pr-347-identity-amended-board-leak-348.md`.

**11-11 ~02:00Z: OPENDDIL'S THREE ITEMS ARE DONE, AND THEIR FOUR REQUIREMENTS ARE RECORDED.**
- **Item 3, ADR-0068 (Proposed):** `docs/adr/ADR-0068-the-edge-tier-profiles-a-case-journal-one-owning-tier-per-step.md`.
  - It is on branch `lane/01-adr-0068-edge-tier` at `a6efbabe`, pushed, in worktree `wt\01\adr68`. **NO PR**: it goes to the architect, then OpenDDIL, before ratification. Open a PR only on the architect's word.
  - §1–§5 are the ordered positions. §6–§9 are OpenDDIL's four requirements:
    - the task list scopes on labels, and a task the viewer cannot see is withheld and recorded as a routing fault, never redacted;
    - a delegated act records delegator, delegate and expiry, and replicates marked as delegated;
    - the stream stays dark until the per-viewer seal is deployed, and the release and instance are read from helm;
    - edge manuals carry revision, digest and age.
- **Item 1 report:** master `sessions/2026-11-11-report-lane-01-the-bff-routes-behind-the-task-list-and-needs-you.md`. **Attach it to the next OpenDDIL sample packet** (which waits on v0.9.19 and the pin).
- **Item 2 report:** master `sessions/2026-11-11-report-lane-01-task-opened-and-task-closed-are-not-events-today.md`. Report only; build them as ADR-0068 journal entry kinds.
- **Packet to the architect:** master `sessions/2026-11-11-packet-to-architect-from-lane-01-adr-0068-drafted-two-openddil-reports-placed.md`.
- **The approvals[].task / task-list PR (after 0.4.85) now carries requirements 1 and 2:**
  - Select `recipient_id`, and match by authz_id or by a capability from policy.
  - Apply the label dimensions. Withhold and record a routing fault, never redact.
  - Apply the same rule to `approvals[].task` AND to `_load_viewable_case`'s task-holder arm (`holds_task_on_case`, `human_tasks.py:745`, which has no label check today).
  - Seal: the holder sees it; a non-holder does not; the addressed holder without the label sees nothing and the fault is recorded; the control is the same holder with the label.
  - After its roll, tell OpenDDIL the release and the instance, READ FROM HELM. Their stream stays dark until then.

**11-11 ~01:40Z: THE ARCHITECT'S TWO GAPS, ANSWERED.** The architect accepted #346 and #340 (including the out-of-order merge), and Lane 1 writes #340's bullet at the deadline.
1. **#331 is MERGED** and waits on nothing. Merge `cf92efc6`, ^2 `3c6a68f0` (the head). CI 22 success / 3 skipped; ratchet 24; is-ancestor of origin/master.
2. **The three refusal datasets are BUILT,** before the lock passes to 74 at 11-11 16:00Z. Lane 1 materialised them on 11-10 between 20:31 and 20:36Z, and all three are SUCCESS:

   | asset | run | columns |
   | --- | --- | --- |
   | `ev_refusal_fixture` | `81a0e28c` | 13 |
   | `ev_refusal_missing_column` | `c66cfeba` | 12 |
   | `ev_refusal_wrong_type` | `b038250b` | 13 |

   Nothing remains to build. What remains is to confirm fin's URNs from the catalog after Chris's sync.
- **Three OpenDDIL items in progress, from the architect** (none is on the 0.4.85 train):
  1. The Tasks and Needs-you BFF routes: their shapes and how each picks the viewer. This goes with the next OpenDDIL sample packet. Per-viewer scoping of the task list folds into the approvals[].task PR.
  2. A report, not a build, on whether task-opened and task-closed events exist, and what the door needs to emit them: an occurrence id, idempotent delivery, and a cursor for catch-up.
  3. The edge-tier ADR draft, as **ADR-0068**. ADR-0066 is reserved for "contracts are data", per ADR-0065:18. It goes to the architect, then to OpenDDIL for review, before it is ratified. It names no customer, place or outside framework.

**11-11 ~01:20Z: #331, #346 AND #340 MERGED; THE REST WAIT ON THEIR OWNERS.**
- **The architect's order, 11-11:** "#331, #345, #339 then #341, #340, #342, #343, saf's wiring, gov's v0.9.19 pin". The two master reds are Lane 1's.
- **Merged:**

  | PR | merge | ^2 | notes |
  | --- | --- | --- | --- |
  | #331 | `cf92efc6` | `3c6a68f0` | |
  | #346 | `82824722` | `769e22e5` | Lane 1's: both reds fixed; test-only |
  | #340 | `4a1e1b5a` | `c9b6fcee` | no CHANGELOG bullet: perf sends text, or Lane 1 writes it into the cut PR after 11-12 20:00Z |
- **Waiting:**
  - #345 (fin): CHANGELOG conflict.
  - #339 (74): no bullet. #341 is stacked on it; retarget, close and reopen after #339.
  - #342 and #343 (gov): CHANGELOG conflicts. Gov was told to re-merge now.
  - saf's wiring: not open.
  - gov's v0.9.19 pin: ca hasn't tagged v0.9.19.
- **Refusal datasets:** materialised 11-10 (`81a0e28c`, `c66cfeba`, `b038250b`). After Chris's sync, confirm fin's URNs from the catalog.
- **approvals[].task is RULED:** the gateway serves it on the train after 0.4.85.
  - Match by authz_id against the recipient row, or by a capability read from policy. Never a group name in code.
  - The seal asserts present for the holder and absent for a non-holder reader.
  - `list_tasks_for_workflows` does not SELECT `recipient_id` today.
  - Cortex has been told.

**11-10 ~21:45Z: TRAIN HALF IN; THE WRITER FIX IS #344; CUT PR HELD.**
- **The architect's order:** "0.4.85 is cut and rolled by Friday 11-13".
  - The cut PR is released when the full train is in, or at Thursday 11-12 23:00Z (17:00 CT, Lane 1's reading), whichever comes first.
  - After the roll, `telemetry_misses` must read 0 on the six engines and cortex-bff. Any non-zero value is reported.
  - Train rule: a red or a new conflict stops that PR; the rest continue.
- **Merged since 21:20Z, by head sha, ratchet 24 on each:**
  - #336 `622bcb7f` (^2 `a616770f`)
  - #329 `431d57bc` (^2 `54c161c0`)
  - #337 `bc5e87c2` (^2 `0501c923`; retargeted, then closed and reopened)
  - #319 `82f70fd0` (^2 `831d8d06`)
- **Still to come:**

  | PR | state | waiting on |
  | --- | --- | --- |
  | #331 | `0ecd9cab`, CONFLICT in `finance_agent/measure_verbs.py` (with #316) | fin's re-merge (packet sent) |
  | #339 | `78ad62ed`, CLEAN | 74's 0.4.85 CHANGELOG bullet (packet sent; the architect agreed) |
  | #340 | `32fa21a5`, CONFLICT in the root and restate_analyst `pyproject.toml` | perf's re-merge (packet sent) |
  | gov's engine-fin pin move | not open | — |
  | fin's live-leg PR | not open | — |
  | **#344** (Lane 1's writer fix) | `b1485cf2`, test merge CLEAN, its bullet lands inside 0.4.85 | CI, then ratchet, then merge |
- **The ruling on the nine ActionRecord errors** (verbatim in the transcript):
  - **ca, SDK:** `work_order` gains `option` and `readiness`; `provenance` gains `case_definition`, `case_id` and `emitted_by`. All are optional strings. `forbid` stays, and the contract version is bumped.
    - v0.9.18 is already tagged (`2f47e9ee`), so this goes in **v0.9.19**. ca has the packet, and the architect has been told.
  - **Lane 1, writer:** `graph_uri` is filled from the node (still required), and `manual_nodes_consulted` is flat. A seal checks against the pinned schema. 9418f245's stored record is not rewritten.
    - That is **#344**: the walk returns `node_uris` and `citations` keeps its shape.
    - The seal allows the 5 ruled fields only while the pin's `model_fields` lacks them.
    - `test_s6_the_model_refuses_a_stage_it_cannot_honour` is red on master too (`82f70fd0`), so it predates #344.
- **OpenDDIL packet: HELD.** Re-issue it once #344 and ca's v0.9.19 are both merged, which also needs a pin move to v0.9.19.
  - The sample is the seal's writer-produced record, sent with the schema and the contract version.
  - Say that live confirmation follows the 0.4.85 roll.
- **D1:** the architect asked Chris to say "D1 moves to Wednesday" to Lane 1 and 74. **Not yet said.**
- **Roll gates:**
  - 74 holds the lock from 11-11 16:00Z until its written hand-back.
  - Chris's Topaz sync is needed (#336 adds walkers to obsolescence-deciders).
  - The values diff goes to Chris first.

**11-10 ~21:20Z: THE 0.4.85 TRAIN. The cut PR is HELD (architect: "Hold the PR, not the tag; the automation tags on merge").**
- **Merged, all under `## 0.4.85 — not yet cut`:** #330 (`a91eb7dc`, ^2 `74c0b498`), #335 (`00099a7d`; the heading and the utf-8 fix), #338 (`d665658d`; langfuse `>=4.7.0,<5` = 4.15.6), #334 (`6f5bb97d`, ^2 `5d1dc05f`), #316 (`7f1a782b`, ^2 `41d88ea2`).
- **Train order from here:** #329 → #337 → #339, then fin's #319 → #331, and gov's #336.
  - #329 (`dcde090c`) and #336 (`9779ce26`) CONFLICT on the CHANGELOG 0.4.85 heading. They are gov's to re-merge; there is a packet to gov.
  - #337 (74, `e958ee78`) is stacked on #329 and gets no CI. After #329 merges: retarget it to master, close and reopen it, merge on green.
  - #339 (74, `78ad62ed`, the where-used BOM for PCN26-182) has no CHANGELOG entry; ask 74 for one under 0.4.85 at its turn.
  - fin walks #319 next, then #331 (packet sent).
  - Merge each by its head sha with `train-one2.sh`, after `join-ratchet.sh`. Test-merge first with `$S/testmerge.sh N` to see where the CHANGELOG hunk lands.
- **OpenDDIL action-record packet: HELD** ("until I rule and the two agree"). It has a banner. The record fails ActionRecord with 9 errors; those were pasted to the architect.
- **74's roll lock:** the handover packet is placed, giving 74 the lock from 11-11 16:00Z. The lock read free at 21:01Z. Lane 1 does not roll, fire or walk until 74's written hand-back. That includes 0.4.85.
- **Re-materialise done:** ev_fixture `c31c24a9` (13 columns, adding status_period and eac_reported) and the three refusal assets. fin has been told.
- **Not started:** LANGFUSE_HOST from the Secret to the ConfigMap; the notice.mfr_source attestation for 7f; ADR-0065 D (waits on #329).

**11-10 ~19:45Z: 0.4.84 IS ROLLED (revision 230) AND 1010'S EPISODE IS FREE.**
- Chris: "Topaz synced at f9fa4d7b. Diff approved. Roll 0.4.84, then release on 9062f943's episode".
- The roll ran from `wt\01\rel484`, the tag tree. All pods are ready, and engine-a is on `ec4735ed…`. The roll lock is released.
- `CaseEpisode/ep-292a06284244b860fca1eb512c6f1dd6/release` answered 200.
  - After it: `open`, `holder` and `revision` are absent, `last_closed` = 9062f943, and `occurrences:9062f943` is kept.
  - The next occurrence of 1010's fault opens a NEW case, with predecessor 9062f943.
- **NAMED LANDMINE (accepted by Chris, 11-10): `WorkflowRunner/9062f943-9b93-574c-bdf0-6497175c9e1f` `run` and `~5` stay
  SUSPENDED for ever. Never cancel, kill or signal either.**
  - Killing `~5` wakes the parent, whose except branch records the case as "failed".
  - Killing the parent starts the 30-day purge of the case record.
  - Signalling `~5` (`tier_ack`) replays its October journal on new code.
- Old failed Jobs `pcn-gate-preroll-*` (12d, 8d and 2d old) are not this roll's. Not read.
- Not done (no word yet): re-materialise `ev_fixture` and the three refusal assets.

**11-10 ~18:20Z: 0.4.84 IS CUT AND TAGGED; the next step is Chris's Topaz sync and roll.**

The architect's sequence: cut 0.4.84 → Chris's Topaz sync (obsolescence-deciders) → values diff → roll → `release` on
9062f943 → read that its episode is free → tell Chris.
- **Done:**
  - #333 merged at `f9fa4d7b`, and `invincible-agent-0.4.84` is tagged there. 0.4.83 stands at `3a23fce4` and never rolls.
  - image-digests: 19 images = 19 expected.
  - Values diff (scratch `valdiff-484-masked.txt`): 22 digests change, plus the same six secret-file keys as 0.4.82.
- **After Chris's roll AND his go:**
  1. Send `CaseEpisode/ep-292a06284244b860fca1eb512c6f1dd6/release {"case_id": "9062f943-9b93-574c-bdf0-6497175c9e1f"}`.
  2. Read that episode: `open` is absent, and `last_closed` = 9062f943.
  3. Tell Chris.
  - NEVER cancel 9062f943. NEVER touch 62b9e840; the re-walk uses a new occurrence.
- **~5, from the code read:** a kill of ~5 alone wakes the parent → except → "failed". A kill of the parent starts the
  30-day purge of the case record. So the proposal is to leave both suspended, as a NAMED LANDMINE: "never cancel,
  kill or signal `WorkflowRunner/9062f943` or `~5`". Confirm it in the report after the release.
- The report is scratch `cut84-and-9062-report.md`.
- **HELD on Chris's "hot fix 1st"** (that order arrived after the tag, so it ships as 0.4.85):
  - merge #316 (then fin walks #319);
  - #330 by sha `74c0b498`;
  - #329 with 74's ImpactRow fix stacked on it (not pushed yet);
  - `encoding="utf-8"` on the chart-version test's subprocess call.
  - The join ratchet is 24/24 on #316 and on #330.

**11-10 ~17:45Z: THE WALK FAILED AT THE DOOR, and the hotfix is PR #332** (`lane/01-a-released-case-frees-its-episode`,
worktree `wt\01\episode`, head `2ecb93d4`).
- 16:33Z: OpenDDIL's occurrence 62b9e840 ATTACHED, by our derived episode key, to case 9062f943. That case was released
  on 10-29, but its run and instance `~5` were still suspended on the pre-0.4.72 `tier_ack` step.
- The read is reported (scratch: `walk-failure-62b9e840-read.md`).
- The fix:
  - `release` is sent when a chaining table names a terminal;
  - a disposing emit `break`s its definition;
  - two seal arms, each killed by its own revert.
- MERGED at `27d59a39` (CI 20 green, join ratchet 24/24). Reported to the architect and Chris; the next step is theirs:
  the tag ruling, then the live action on 9062f943 after the roll.
- **Do NOT touch 62b9e840 or 9062f943.** Freeing 9062f943 is a live action for Chris: an episode `release`, or a cancel,
  which fails the case. `~5` must never be resumed on new code, because its journal would mismatch.
- **`invincible-agent-0.4.83` ALREADY EXISTS on origin at `3a23fce4`.** chart-releaser created it at 03:43Z. Whether the
  later content rides 0.4.84 needs Chris's ruling. The hotfix entry sits under 0.4.83, as ordered.

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
