# Handoff: lane/fin, 2026-10-09. Rulings applied; per-engine split and duckdb PR in flight

to: invincible-agent/lane/fin (worktree `ia-fin`)
from: invincible-agent/lane/fin, the session of 2026-10-08/09

## Rulings received (architect, 2026-10-09)

- **Q0, the collision.** Keep #8, #9 and #11. Close #10, which came from a stray session that has been dead since the reboot, not from this lane. Read its four commits, then cherry-pick only what #9/#11 lack, as this lane's own commit.
- **Q1, mixed boards.** Today a mixed board is refused whole. Build the per-engine split next. A refused engine renders as a refusal section, and the others export.
- **Q2, the duckdb file.** Yes, the file is `dist/` duckdb. The access denial is a Windows ACL. Chris fixes it; do not work around it.
- **Q3, duckdb skips.** Add duckdb to the root `agent-fleet` extra. Silent skips become skips with a reason that the suite summary prints. Small PR.
- **Q4, the R-001 status note.** Lane 1 owns the rulings-register note; we do not edit `docs/rulings/README.md`.
- **Q5, cost boards.** Ad-hoc boards; no ratified template.
- **General.** Ratify nothing.

## Done

- **#8** (`fin/board-eac-comparison`) merged 2026-10-10T04:27Z. program_finance slot 5 is `finEacComparison`.
- **#10** closed, with a comment saying what was read and taken.
- lane/fin `ad51b5d6` reverts the four stray commits. The tree equals `6aceae41`.

## Update 2026-10-10, later: rulings Q1–Q4 applied. Nothing open but merges and the ACL

- **Rulings received:**
  - **Q1:** no ad-hoc export for engine-fin; ratified templates only. That is the finance control, not a gap.
  - **Q2:** the fin section goes to the board's recipient and states "not a ratified template", nothing else.
  - **Q3:** the refusal lives in the API response and the exporter's view, never the customer page.
  - **Q4:** lane/fin rebases #11 with `--force-with-lease`. Merge order is #11, #18, #21.
- **Done:**
  - #11 is rebased onto `3976a9e0` and pushed (`b9792711` → `ae01d904`). Tests: 55 passed, 1 skipped, exit 0. GitHub reports MERGEABLE.
  - #21 has `f66a2da5`, which applies Q1–Q3 and is pushed. Tests: 83 passed, 4 skipped, exit 0. Mutants M8–M10 all red. GitHub reports MERGEABLE.
  - #18 is unchanged and merges clean.
  - The digest packet and the cortex-ui packet are updated.
- **Next:** merges are Lane 1's. Run the dist-page `--like` check once Chris fixes the ACL.

## Update 2026-10-10: everything below is now a PR. Read this first

- **#11** `fin/cost-reproducible-build` @ `b9792711`: open.
  - Master's `0374249f` is #11's `bf01618f`, rebased (same patch-id). As a result, #11 add/add-conflicts with master at `tests/cost/test_the_alpha_build_is_idempotent.py` L26.
  - `git rebase origin/master` drops `bf01618f` and fixes this. The rebase is not pushed: the classifier refused the history rewrite. Digest Q4 asks who does it.
- **#18** `fin/duckdb-extra-skip-reasons` @ `bc2e730b`: open. It MUST merge after #11. Measured: on master + #18, the census arm reds on the bare skip at L26 that `0374249f` brought in, and #11's `b9792711` fixes that site.
- **#21** `fin/export-per-engine-split` @ `a224129a`: open, worktree `ia-fin-export-split`. Measured: master + #11(rebased) + #18 + #21 gives 155 passed, 18 skipped (Pyodide VOIDs), exit 0.
- **Packets placed (untracked):**
  - the digest: `invincible-agent/sessions/2026-10-10-packet-to-lane-01-fin-digest-split-pr21-duckdb-pr18-merge-order-11-then-18.md`. Questions 1–4: engine-fin ad-hoc path; fin recipient on a mixed board; refusal section at the response level; who rebases #11.
  - cortex-ui: `cortex-ui/sessions/2026-10-10-packet-to-cortex-ui-a-mixed-board-export-answers-per-engine-documents.md`. It covers `documents[]`; today's button shows `partial` with no link.
- **Next:** wait for rulings on Q1–Q4 and for the `dist/` ACL fix, which is what the `--like` check of the dist page needs.

## In flight at the time of writing (2026-10-09, superseded by the update above)

1. **#11** (`fin/cost-reproducible-build`, worktree `ia-fin-cost-reproducible-build`): an implementer is adding the part #10 had and #11 lacked.
   - The slice-1 branch of `build_html` dropped `as_of`.
   - It also adds `--sha` and `--like PAGE`.
   - Spec: the session scratchpad's `spec-pr11-slice1-cherry.md`.
   - After it lands, also give #11's `importorskip("duckdb")` a `reason=`, or the duckdb PR's census seal reds the join.
2. **duckdb PR** (`fin/duckdb-extra-skip-reasons`, worktree `ia-fin-duckdb-extra`):
   - pins `duckdb==1.5.2` in the root extra, equal to cost_agent's pin;
   - relocks with uv;
   - gives every duckdb `importorskip` a `reason=`;
   - adds a `pytest_terminal_summary` section in `tests/conftest.py`.

   Rejected: `addopts = -rs`. There is no root inifile, and adding one moves rootdir for Lane 1's full suite.
3. **Per-engine split.** Not started. Read first:
   - gateway `/export/package` at master ~L1991-2090;
   - the ad-hoc cost path ~L2028;
   - `_resolve_export_answers` ~L1815;
   - `_export_package_from_template` ~L1871;
   - engine-fin `/package_export`, `finance_agent/main.py` ~L771-870. It takes ONLY a template-shaped canvas (`template_id`, `template_hash`, `panels[{panel, verb, params}]`) and requires every panel's `params.program_id` to equal the recipient's program.

   Open design points to settle before speccing:
   - (a) One request has one `recipient_scope`, but the cost scopes (`notional-customer-*`) and finance scopes (`program_office.<program>`) are disjoint. Which recipient does each engine's partition get?
   - (b) Ad-hoc finance answers have no template (Q5: no ratified template) and the store keeps no `program_id` in `_resolve_export_answers`' output. Check `accepted_slots` in the `resolved_intent` writer, master ~L6872.
   - (c) The partition key should be derived from each engine's own verb set (cost `canvas.EXPORTABLE`, fin `main.VERB_TO_FN`/`VERBS`), never from a `cost`/`fin` prefix. A verb in neither set is refused by name.
   - (d) Response shape for cortex `CanvasExportButton.tsx` / `src/api/client.ts` ~L876. Keep the single-engine response unchanged.
   - The mixed test in #9 (`test_MIXED_...refuses_the_whole_export_by_name`) pins today's behaviour, which the ruling confirms for today. The split PR changes it.

## Fork not resolved by me: which page is "the dist page"

#10's `3a61c42e` message says `dist/cost-validation-notional-customer-alpha.html` is a slice-1 (one-file) page. It says `--slice1` reproduced it byte-for-byte (sha256 `be4a4057…`) with no duckdb read.

#11 reproduces the 09-06 dataset document by identities. I could not check which one dist holds (Q2: ACL, Chris's fix). Once the ACL is fixed:
- run `scripts/build_cost_package.py --like dist/cost-validation-notional-customer-alpha.html --recipient notional-customer-alpha --out-dir <tmp>`;
- compare the sha of the result.

## Standing

- Trailer: derive from `ia-fin` (`Lane: ia-fin/lane/fin`), never from a PR worktree.
- One PR per item, cut from origin/master in a fresh `ia-fin-<slug>` worktree.
- No rolls.
- A pre-existing red, not ours: `tests/planning/test_producers_speak_their_archetype.py` `_CONTRACTS` L45 names `ShortfallGrid.contract.ts`, which cortex-ui moved to `src/archetypes/shortfall-grid/contract.ts`.
