to: ia-gov/lane/gov
from: ia-gov/lane/gov
date: 2026-10-06
re: lane/gov's opening brief, and what measuring it changed

# Handoff — lane/gov: the brief, and what measuring it changed

Reports to `invincible-agent/seat/architect`. Packets placed in `invincible-agent/sessions/`,
never committed there. Merges go through Lane 1's gate.

## The brief (as dispatched 2026-10-06)

1. The 49-red baseline to zero: the 37 routing tests on localhost:8084 (the stale WSL relay, then
   make the tests refuse an unexpected responder), the SDK-tag pin tests (now 0.9.6 is cut), the
   stub-harness sys.modules restore across 21 files, the two order-dependent reds.
2. Rulings register: number every ruling since 09-19 (R-082 onward) from handoffs and measurement
   docs; the R-055 citation grep; the inbox census with the unenumerable third state.
3. The lane_packets scanner: external addressees (openddil) listed as such, not "no addressee"; a
   report of unanswered packets per lane older than 48h.
4. CLAUDE.md consolidation across the five repos: the standing rules that live only in chat.

The dispatch said "lane/fin in ia-fin" with a working directory of `a-gov`, which does not exist.
Chris resolved it: **this brief is gov's, in `ia-gov`**. Items **2 and 3** are paired (both read
the packet template); the dispatch's "1 and 3" was corrected by Chris.

## Premises measured, and three that did not hold

- **"49 reds" is recorded nowhere** in the tree. The baseline is being re-measured by identity
  (junit) over `tests/routing` + `tests/test_mesh_writers_conform.py` at `2b6fe0f6`.
- **8084 is not a stale relay.** `wslrelay` (pid 14196) and `com.docker.backend` listen on 8084
  because the container `openddil-demo-projector-01` publishes `0.0.0.0:8084`. OpenDDIL's live demo
  is answering the routing suite; `/health` there returns Prometheus `text/plain`. The probe in
  `tests/routing/conftest.py` is a TCP connect, so it passes and the tests fail against the wrong
  service. Stopping that container is not this lane's act. The in-lane fix is the identity check.
- **0.9.6 does not carry the fleet's pin.** The fleet pins SDK `012a24fb` (= `v0.9.5-10`), which
  is NOT an ancestor of `v0.9.6` (`49cfaa0`). `git diff 012a24fb v0.9.6` removes 1629 lines — the
  systems-of-record module, `has_node`/`delete_node`, Jena writer auth. Re-pinning to the tag would
  regress the fleet.
- **Rulings are numbered through R-089**, so item 2 is a census for rulings recorded only in
  handoffs/measurements, not a fresh numbering. R-082 has no `RULED <date>` preamble.
- **The external-addressee gap is wider than openddil.** `_QUALIFIED`'s lane alternative captures
  the REPO prefix, so `doc-tools/lane/7f` files under lane `doc-tools`, which no `origin/lane/*`
  branch matches — those packets print nowhere, not even UNADDRESSED. `to: OpenDDIL's agent` (9
  packets) parses as UNADDRESSED.
- **Five repos** — invincible-agent, cortex-ui, iagent-mesh-sdk, doc-tools, and dag-tools (Chris,
  2026-10-06; dag-tools has no lanes and no sessions/). CI census (corrected 2026-10-07): ALL FIVE repos
  trigger `pull_request` only on base master/main, so a stacked PR is never built anywhere. The
  first version of this line said cortex-ui, the SDK and doc-tools had no pull_request trigger;
  that was a misread (their workflow files are unchanged since 2026-10-06).
  Rule 2 (only the owning lane commits) means lane/gov edits only this repo's CLAUDE.md; the
  others get packets.

## The baseline, measured by identity at `2b6fe0f6`

`uv run pytest tests/routing tests/test_mesh_writers_conform.py -p no:randomly` → 37 failed, 838
passed, 123 skipped (6m03s). Then the four SDK-pin files → 1 failed, 70 passed.

| reds | cause | owner |
| --- | --- | --- |
| 36 (29 `test_classify_route`, 7 `test_phrasing_independence`) | `HTTPError: 405` — OpenDDIL's projector answers 8084 | lane/gov: identity probe (in flight) |
| 1 `test_no_legacy_residue` | `KeyError: 'data'` — OpenDDIL's **Restate** server answers 8080 as "Weaviate" | lane/gov: same probe |
| 1 `test_sdk_is_pinned_to_a_tag[ia-gov]` | root `pyproject.toml` pins sha `012a24fb`; engines pin `v0.9.5` | **iagent-mesh-sdk/lane/ca**: cut `v0.9.7` from `lane/ca-0.9.7`, which holds `012a24fb`; then lane/gov re-pins |

All `test_mesh_writers_conform.py` arms pass. 38 + 1 = 39 measured here, plus the two
order-dependent reds (which only appear in some orders) — still not 49. The 49 is unsourced.

## State (2026-10-07, end of session)

lane/gov on origin at `f5e9151e`, rebased on master `213ec945`:
`705cedea` routing VOID/18084 · `f6e129d2` inbox scanner · `f6513994` CLAUDE.md rules 3–5 ·
`3b6b8e98` citation census · `f5e9151e` census imports its own scanner. Merge is Lane 1's gate.

- Item 1:
  - Routing reds become VOID (absent or foreign), live-verified with a stand-in foreign server.
  - `test_adr0019_engine_o_contract_a.py` lost its spurious marker but STAYS in
    `_DEFERRING_FILES` (its remaining guards are absence shims).
  - The order-dependent reds do not reproduce at this sha.
  - SDK pin waits on lane/ca's tag.
  - The sys.modules restore conversion (A2, implementer) was in flight at session end; its
    measurements are in the session scratchpad `a2/`.
- Items 2+3: the 30 ruling drafts are with Lane 1 (R-021). The scanner and census are done.
- Item 4: CLAUDE.md here is done. Packets are placed (untracked) in cortex-ui, the SDK and
  doc-tools, with their CI line corrected in place. The dag-tools packet sits in
  invincible-agent/sessions (dag-tools has no sessions/ dir and no CLAUDE.md, only AGENTS.md).
- Report placed: `invincible-agent/sessions/2026-10-07-packet-to-architect-gov-the-four-item-brief-measured.md`.

## Next step

1. If A2's diff is in this worktree, uncommitted:
   - review it: population derived rather than listed, before/after alone + per directory +
     seeds 1–3, ratchet `test_NO_FILE_WRITES_SYS_MODULES_WITHOUT_A_RESTORE` red on a
     no-restore mutant, reconciled against "21";
   - commit named paths with `--trailer "Lane: ia-gov/lane/gov"` (derive it) and push
     `origin lane/gov`; upstream is origin/master, so always name it.

   If A2's diff is not there, re-spec A2 from the brief above. Either way, place a follow-up
   packet to the architect.
2. On lane/ca's reply (v0.9.7 at `012a24fb`, or the tag that contains it):
   - re-pin root `pyproject.toml` (lines 66, 138) and `uv.lock`;
   - re-run the four SDK-pin files.
3. Watch for the architect's ruling on `ia-`-prefixed addresses to out-of-repo lanes
   (`ia-cortex-60`, `ia-ca`; 20 packets read NO BRANCH here). Do not teach the scanner to guess.
