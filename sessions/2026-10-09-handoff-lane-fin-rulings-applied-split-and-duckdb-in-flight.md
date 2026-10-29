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

## Update 2026-10-28, last: repairs 1 and 2 are #139. Read this first

- **The ruling.** Repairs 1 and 2 were approved: the export reads the routing record's verb, and a
  failed seed records its verb and cause.
  - The supervisor's four exits are Lane 1's, for 0.4.72.
  - Chris's five ids: "not worth chasing".
- **#139** (`fin/verb-on-every-answer`, `1bee9f8e`, against master) builds both repairs.
  - Targeted runs are green: 23, 42, 2 and 24 passed.
  - **The seed-turn raise is RULED and fixed** (`32d513e5` and `82fa2b46`). A raise on a seed turn is now a
    `pipeline_error` that names the step. Its cause is `seed_panel_dispatch_raised`, with
    `retryable: true`, and the artifact is `failed` with the verb and a `failure_cause`. It never
    reaches the supervisor.
    - All 5 mutants red a named arm.
    - Runs: 15, 10 and 39 passed.
    - A comment is on #139.
- **Open PRs:**
  - #136 and #137 are CI-green;
  - #137 needs master merged in after #136 lands;
  - item (2), the plan export profile, comes after #136.

## Update 2026-10-28, latest: "no verb" on plan answers measured and reported; nothing fixed. Read this first

- **Rulings on #137.** The architect confirmed the reading: a recipient is offered when it takes at
  least one answer, and partial export stands.
- **The "no verb" measurement is done, and reported before any fix,** as ruled. The packet is
  `sessions/2026-10-28-packet-to-architect-fin-no-verb-on-plan-answers-measured-the-premise-is-a-different-path.md`
  in the master tree, untracked.
- **What it found:**
  - Portfolio never takes the seed dispatch. Its panels declare no subject, so it goes through the
    phrase path.
  - Of 103 phrase answers, 43 predate `e4154f91` (Sep 4). Their verb is in
    `routing_inline.action.iri`, not in `resolved_intent`.
  - 6 are the supervisor's `no_verb_classified` exit; `no_verb` is correct for them.
  - The real seed-dispatch gap is 18 failed `program_finance` seeds from Oct 8. They carry no verb
    and no cause, because the seed_panel FALL_BACK branch writes neither.
  - The five ids on Chris's board are not known.
- **Next: WAIT for the ruling on repairs 1–5.** I recommended 1 (export falls back to
  `routing_inline.action.iri`) plus 3, with 4 routed to the supervisor's owner. Item (2) and the
  #137 merge from master still wait on #136.

## Update 2026-10-28, later: #135 merged; the export offer is #137; item (2) is next after #136. Read this first

- **Merged:** #130 and #135. Origin/master holds #135 as `69c98538`. **#136** (CDRL) is next in Chris's
  confirmed order (#130 → #135 → #136).
- **Chris confirmed:**
  - **The P0 sentence** was `make me a finance canvas`, then the program pick.
  - **The sample type** `fin:ToCompletePerformanceIndexSeries` stays in the finance ontology file.
  - **Re-prime after the roll** is Lane 1's, done with the 0.4.72 roll.
- **The exporter directive (architect, 10-28).** A Portfolio canvas was exported to
  NOTIONAL-CUSTOMER-ALPHA and refused 5/5 ("resolved no verb, not_in_model").
  - **(1) is #137** (`fin/export-offer`, `e9aa7dfe`). It adds `POST /export/package/recipients`,
    which returns each recipient as offered or greyed, plus a row per refused answer. The decision
    is made by the export's own functions, and an agreement arm checks it against the real
    engine-cost. It also fixes the export dropping lotless answers from `documents[]`.
    - The spec is `scratchpad/spec-export-offer.md` (session `91ad3195`).
  - **(2) is next after #136:** the plan-answer export profile under `policy/exports`, which is
    lane/01's machinery, with kinds declared per profile.
  - **Packets placed (untracked) in the master tree's `sessions/`:**
    - to cortex-ui: `2026-10-28-packet-to-cortex-ui-fin-the-export-picker-greys-before-export-and-a-refusal-is-a-row-per-answer.md`;
    - to the architect: `2026-10-28-packet-to-architect-fin-export-offer-is-137-one-reading-to-confirm-and-a-seed-verb-finding.md`.
  - **Open with the architect:**
    - Confirm "covers" = takes at least one answer. A partial board stays offered.
    - Who measures why seeded Portfolio answers carry no `verb_iri`? The direct-dispatch early
      exits are the suspect.
- **Master's gov ratchet is red** on 19 sites in `repo_core.py`, from lane/01's #133. lane/01 has
  already been sent a packet. Not ours, so do not widen it.

## Update 2026-10-28: P0 fixed in #132; #117 never landed, so it is #130; measure is #135, CDRL in build. Read this first

- **#117 is merged, but not into master.** #113 merged into master at 10-27 13:25Z. #117 merged
  afterwards (10-28 14:46Z) into #113's branch, which was dead by then, so `bdc1a94f` is not in
  master.
  - Reopened as **#130** (`fin/verbs-honour-program-members` → master); all checks pass or were
    skipped.
  - Until #130 merges, a typed program id still bypasses the grant at `/measure`.
  - Memory: `a-merged-pr-can-be-merged-into-a-dead-base`.
- **P0 of 10-28.**
  - **(1) The empty "which program?" menu** was timing, not a defect, per the architect's ruling.
  - **(2) The 502 on `/canvas/seed`** came from cortex #34's re-send after the program pick
    (query + program_id + persona, no domains). It is fixed in **#132**
    (`fin/canvas-seed-derives-the-cell`, `1f7596c6`):
    - a persona-only seed gets `domains_for(persona)`;
    - an unheld persona gets a 403 `persona_not_held` via `policy_refusal`;
    - domains without a persona get a 400 `field: active_persona`;
    - when every panel answers the same 400 or 422, the seed answers that status as
      `seed_panel_refused`, naming the field.
  - **Owed:** the UI acceptance after the roll, which is Chris's exact sentence, then the pick of
    NP-MERIDIAN, then a 6/6 seed. **The sentence is still owed by Chris.**
- **Directive of 10-28:** "(1) a measure overlay contract plus one synthetic algorithm through ask
  and the canvas; (2) a CDRL export from a profile plus an xlsx template. Spec first, packet the
  contract to Chris."
  - **Contract packet** (placed, untracked):
    `invincible-agent/sessions/2026-10-28-packet-to-architect-fin-for-finance-the-measure-contract-and-the-cdrl-profile.md`.
    Sections 1–4 are written for finance.
  - **Proposal:**
    `docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`, committed in
    #135.
  - **(1) is #135** (`fin/measure-rows-tcpi`, `1390ce8f`, against master, carrying #130 as a merge
    commit). It adds:
    - the `measure_verbs` overlay kind (`MEASURE_VERB_OVERLAY_DIRS`);
    - the pure module `measure_modules/tcpi.py`;
    - the sample `fin_tcpi`;
    - `CANVAS_OVERLAY_DIRS` with the sample board `program_finance_tcpi`;
    - the env keys in sandbox values only.

    It has three caveats:
    - **The chart-version seal is red by decision.** No bump yet: the bump belongs to the release
      that rolls it.
    - **`fin:ToCompletePerformanceIndexSeries` sits in `finance_extension.ttl` as SAMPLE.**
      Without it, Contract D would refuse the registration batch.
    - **The roll needs a re-prime.**
  - **(2) is #136** (`fin/cdrl-export-profile`, head `36d48100`, against master, carrying #130 and #135). Its review found two defects that only the image would show, both now fixed: #135 `1b5c90ab` (`parents[2]` raised IndexError at import in the flattened image) and `36d48100` (the CDRL was written behind `_repo_root()`, which the finance image cannot satisfy). The spec was `scratchpad/spec-cdrl-export-profile.md` (session
    `91ad3195`), on branch `fin/cdrl-export-profile`, stacked on #135. It covers:
    - openpyxl;
    - the `fin_export_profiles` kind (`FIN_EXPORT_PROFILE_OVERLAY_DIRS`);
    - a deterministic sample template;
    - engine `/cdrl_profiles` and `/cdrl_export`;
    - BFF `/export/cdrl/profiles` and `/export/cdrl`.
- **Next.**
  1. Review the CDRL build and open its PR against master.
  2. Packet lane/01 (cc the architect and cortex-ui) with the shared profile header
     `{name, format, scope, label}`.
  3. Merge order: #130, #132, #135, then CDRL.
  4. After the roll: the P0 sentence; the TCPI ask as alice; `program_finance_tcpi` seeding 2/2;
     the CDRL download, with bob refused.

## Update 2026-10-27, later: the verbs check is PR #117, stacked on #113. Read this first

- **The ruling.** "#113 merges. Next: the finance verbs (/measure, /package_export) check program
  visibility by the same filter, deny by default, 403 with the refusal envelope; PR today. Morning
  sentence after the post-upgrade hook."
- **#113** was still OPEN at `7b497119` (CI pass) when #117 was opened. Gov's #107 merged at
  `0d228204`.
- **#117** (`fin/verbs-honour-program-members`, `bdc1a94f`, base #113's branch, so NO CI gate until
  it retargets).
  - `_can_view` is now the one predicate for all four routes.
  - `_verb_caller` is bearer first: a user bearer is the caller; a `svc:` bearer or none delegates
    to the body's `user_email`.
  - The 403 envelope has no `grantable_by`. The BFF fills it with `relay_refusal`.
  - 12 mutants, each a named red. Targeted run: 473 passed, 1 failed (`MODEL_EXPLANATION`, the
    same failure as on #113).
- **My census missed a caller.** graph_host's `graphs/fin_program_brief.py` calls `/measure` with
  only the bearer. I had grepped the wrong path, and the implementer's run caught it. That is why
  the identity is bearer first.
- **The trailer hazard.** The pre-push hook wants the LANE id (`Lane: ia-fin/<branch>`), not the
  throwaway worktree's dir. Derive it with `.githooks/pre-push --expected`.
- **Packet** (placed, untracked):
  `invincible-agent/sessions/2026-10-27-packet-to-architect-fin-verbs-refuse-ungranted-programs-pr-117.md`.
  It asks for two rulings:
  - the identity source;
  - who relays the refusal in the supervisor (today it shows as an `engine_unreachable` card).
- **Next.** Await the rulings and the #113 merge, then re-read #117's checks on `master`.

## Update 2026-10-27: #102 and #103 merged; the program filter is #113; #107 reviewed

- **The ruling, from the architect via Chris.** "#102/#103 merge. Then gov's program_members
  filter." Both merged on 2026-10-26, at `e085440c` and `20858e6a`.
- **#113** (`fin/enumeration-honours-program-members`, `7b497119`, built in
  `ia-fin-export-refused-entries`).
  - engine-fin's enumerate and resolve keep only members whose program the caller holds
    `can_view_program` on, across all six classes, before the menu bound.
  - A `svc:` caller sees nothing; an outage is a 503.
  - It grants NP-MERIDIAN to alice in `policy/program_members.yaml`.
  - Targeted run: 467 passed and 1 failed, the cortex-ui `MODEL_EXPLANATION` archetype, which the
    diff does not touch.
  - Eight of nine mutants red a named arm. The ninth showed the empty-caller check was redundant,
    so it was deleted.
- **The roll hazard, which is in the PR body.** The grant syncs in a `post-upgrade` hook, after
  engine-fin rolls, so alice's menu is empty until that hook finishes. Run the morning sentence
  before the roll, or after the hook.
- **#107 (gov), reviewed at `ffee7a34`.**
  - Merged with master in a throwaway: 81 passed on the seed seals and gov's ratchet.
  - Approved, with two notes: the `slot_refusal` docstring goes stale after #113, and whether the
    options row should name `program_members` is for the architect.
  - Packet (placed, untracked):
    `invincible-agent/sessions/2026-10-27-packet-to-gov-107-reviewed-and-section-3-is-now-pr-113.md`.
- **Next.**
  - Await the merge rulings on #113 and #107.
  - Whether the finance verbs should check the bound program's membership is unruled and
    unreviewed.
- **The process slip, recorded.** One pytest run (44 tests) went ahead at 1.6 GB free, because
  the memory check printed and did not gate. Every later run gated on it.

## Update 2026-10-25, later: #97+#98 on master, gate 5 is #102, seed bodies are #103

- **The ruling, from the architect via Chris.**
  - #97 merges, and #98 rebases and rides 208.
  - The pinned-test widening is allowed: assert the new field, keep every old assertion.
  - Gate 5 is fin's, to diagnose before Monday noon.
  - Add the 409 and 200 seed bodies to the BFF OpenAPI.
- **#97 and #98 were already on master** as `e676f58e`, because #98 was merged into #97's branch.
  No rebase was needed. CI ran on `af49bf91`, builds and lint only.
- **#102** (`fin/gate-5-reads-the-409-message`, `2d66fd73`). Gate 5 has been red since lane/01's
  `d0f80092` added `message` to the 409. The arm was stale and now ignores only `message`.
- **#103** (`fin/canvas-seed-bodies-in-openapi`, `93b8894d`).
  - The 200 and 409 models, wired through `responses=` only.
  - The pinned seal is applied per the ruling.
  - It fixes the master red #97 caused in `tests/test_every_409_carries_a_message.py`.
  - The `AnnAssign` blindness is lane/01's to decide.
- **Corrected in place.** The cortex and gov packets said `detail.policy`; it is
  `detail.ask.policy`.
- **Next.** Once 208 rolls, Chris runs the morning sentence. If he reports a miss, check the
  classifier caveat first.
- **Still open, mine.** The `refusal` envelope on `ask.policy`. Gov's #96 is merged now, so this
  waits only on their Q2 and on the name of the program-grant family.

## Update 2026-10-25: finance canvas is #97 then #98 (stacked)

- **The task.** From the architect via Chris: "make me a finance canvas" got no verb, and the
  picker showed red "needs a binding: program".
- **The report.** `sessions/2026-10-25-report-finance-canvas-cause-fix-prs-and-the-morning-sentence.md`
  covers the cause, the fix and the morning sentence.
- **The PRs.**
  - #97: `fin/finance-canvas-asks-which-program`, head `473f9c40`, base master.
  - #98: `fin/canvas-seed-answer-names-its-template`, head `df5802bb`. It is stacked, so no CI
    gate runs on it, and it widens a pinned seal, so it needs a ruling.
  - Both were built in worktree `ia-fin-export-refused-entries`, whose trailers name that worktree.
- **Packets placed.** One to lane/01 (merge order and rolls), one to gov (it answers their
  "which finance failure?" and flags that their 401/403 census misses an empty-menu 409), and one
  to cortex-ui (picker).
- **Open, mine.**
  - Once gov's #96 merges and their Q2 is ruled, give the 409's `policy` a
    `refusal {policy_id, missing_binding}`. The mapping is in the gov packet. Which family owns a
    program grant is gov's to name.
  - Diagnose the base-red `test_fin_package_export::test_gate_5_a_disagreeing_scope_is_409_naming_the_derived_one`.
- **Next.** Wait for the merges and the roll, then fire the morning sentence live, 3 times. If
  `mesh:finProgramBrief` wins, that is the classifier caveat, and it goes back to the architect.

## Update 2026-10-20: both live export checks pass on `016473bb` (helm rev 203)

- **What's live.** All four PRs are live. #67 and #69 went out at revision 199 (roll 194), and #71 and #72 at roll 195. I confirmed this by content in the running pods, not by image tag.
- **Empty board.** It returns 400 `no_answers`, three ways: `answers: []`, `answers` omitted, and an empty list with no recipient.
- **[no-verb, labour] board, fired 3 times.** Each run came back `partial`, "1 of 2 answers refused". The labour answer exports; the supplier answer is a `failed` entry with `no_verb`. The sha matched the labour-only board's (`2489b6a4…`) on every run.
- **Packet (untracked):** `invincible-agent/sessions/2026-10-20-packet-to-lane-01-fin-both-live-export-checks-pass-on-016473bb.md`.
- **Not checked live:** #72's entitlement prose, because there was no unentitled-lot answer to hand.
- **Next:** idle. Nothing open on lane/fin.

## Update 2026-10-17: Q1 is #67, the refused entries are #69 (stacked)

- **Rulings (architect via Chris, 10-16):**
  - the twice-export is accepted;
  - Q1: export the good answers and name the refused ones;
  - "refused-section-in-document" means ONLY the `documents[]` entry, with a reason_code and prose. The 10-10 ruling is unamended.
- **#67** `fin/export-good-answers-name-refused` @ `439865f2`, worktree `ia-fin-export-good-answers`. The cost canvas exports its good answers; refused answers are named by `no_verb`, `not_an_exportable_cost_verb` or `lot_not_named`.
- **#69** `fin/export-refused-entries-in-documents` @ `c219526a`, worktree `ia-fin-export-refused-entries`, with #67's branch as its base. Refused answers become `failed` `documents[]` entries grouped by reason_code; the fin section gains a reason_code; the top reason reads "r of n answers refused".
- **Merge order:** #67, then #69, in one roll. Lane 1 merges.
- **Unruled choice, flagged in the packet:** entitlement still refuses the whole canvas.
- **Packet (untracked):** `invincible-agent/sessions/2026-10-17-packet-to-lane-01-fin-q1-is-pr67-refused-entries-pr69-merge-in-order.md`.
- **Lane 1's packets, committed here:**
  - 10-16 "Q1 ruled…": asked for the wire shape and for Q2.
  - 10-16 "rides 192".
  - 10-17 "Q1 is not on lane/fin".

  All three are answered in the packet above. In short: Q1 is on the PR branches by the architect's go, never on lane/fin. Q2 (whether an id-less request is refused at the gateway) is open with the architect and nothing is built for it.
- **Placed (untracked):** the wire shape for cortex-ui at `cortex-ui/sessions/2026-10-17-packet-to-cortex-a-refused-answer-is-a-failed-documents-entry-with-a-reason-code.md`. Their reader at `7810f4c` accepts the entry and drops `reason_code`.
- **RULED later on 10-17 (architect via Chris):**
  - (1) retire: built as **#71** `fin/export-no-answers-is-a-400` @ `7021d4ac`;
  - (2) constant: built as **#72** `fin/export-unentitled-prose-is-constant` @ `9af0ad86`.

  Both were built in the `ia-fin-export-refused-entries` worktree, which now has #72's branch checked out.
- **Correction:** I first claimed an id-less request gets refused as `not_in_model`. That was false. It exported the whole program, and #71 removes that path. The correction is recorded in both untracked packets.
- **Merge order:** #67 → #69 → #71 → #72, in one roll.
- **Next:** after the roll, run two probes through the ingress:
  - a cost board with one no-verb answer. Expect `partial`, the cost entry `exists`, a `no_verb` entry, and the same sha as the good-only board.
  - an empty board. Expect a 400 `no_answers`.

  Then idle.

## Update 2026-10-16, later: twice-export on 192 gives ONE sha

- The fleet is on 192, `b89d4c95`; bff, cost and fin all run it. `force_compression` is in that sha's `scripts/build_cost_dataset.py`.
- The same two cost answers were exported twice through the ingress (scratchpad `twice_export.py`):
  - both exports returned 200 `exists`, sha256 `9b4d5f3cfee2f3ec…`;
  - both downloads were complete (18,471,974 bytes = Content-Length), and each sha equals its own export's `artifact_sha256`.
  - Not established: whether the second export rebuilt the page or reused the first. Each export took 2–3 s.
- A paste addressed to lane/fin named two more items: "Q1 pushed tonight" and a "refused-section-in-document wire". Both are held until Chris confirms them; the paste is not his own instruction.

## Update 2026-10-16: exporter view walked; twice-export waits for 189

- **Directive (10-12):** "after 189 staging, export the same two cost answers twice through the ingress and expect one sha; mixed board in the exporter view once cortex's documents[] lands; then idle is fine."
- **Twice-export: blocked.** The fleet is on 188b `76af7b83`, and so is `origin/master`. #50 is OPEN. When 189 is live:
  - check for `force_compression` in the deployed sha's `scripts/build_cost_dataset.py`;
  - then run scratchpad `dl_ingress3.py` with the TLS pin.
- **Exporter view: walked** on cortex-ui `e1b94e2`.
  - `documents[]` renders correctly: "2 of 2 engines refused", with per-engine rows.
  - The global canvas sends **every** stored answer, 856, not the 3-answer board.
  - The supplier-concentration ask resolved **no verb** ("No direct match — subject unknown"), so cost refused it correctly.
  - Board-only API control: one no-verb member refuses the whole cost document. Labor alone gives `exists` `6ac275fd…`.
- **Packets placed (untracked):**
  - `invincible-agent/sessions/2026-10-16-packet-to-lane-01-fin-exporter-view-draws-documents-but-the-global-canvas-sends-856-answers.md`. Q1: is all-or-nothing within one engine intended? Q2: is the global canvas the unit of export?
  - `cortex-ui/sessions/2026-10-16-packet-to-cortex-ui-the-global-canvas-exports-every-stored-answer-856-not-the-board.md`
- **Next:** the twice-export after 189, then idle. Wait for Q1/Q2 rulings; do nothing on them unasked.

## Update 2026-10-12: byte-stable export is PR #50 and the runbook note is PR #49. Read this first

- **The directive of 10-11** (uncompressed duckdb, `as_of` as an input, a Linux CI test, a runbook note, an ingress download test) is done as two open PRs. Lane 1 merges and rolls.
  - **#50** `fin/export-byte-stable` @ `e63c6f4c`, worktree `ia-fin-export-byte-stable`. CI `reproducible` is green.
    - The Linux and Windows dataset shas DIFFER: cost `9dd2f92b…` vs `1ccd4ef2…`. Each platform is stable, and the cause is not measured. Noted on the PR. **RULED 10-12: noted, NOT chased. Do not investigate it.** Lane 1 merges #50 and #49 for rev 188.
  - **#49** `fin/walk-sheet-download-check` @ 2 commits, worktree `ia-fin-walk-sheet-download`.
- **The ingress also truncates**, rarely: 1 of 50, with an unexplained `ReadError`. This corrects the 10-11 packet's title.
- **Report to Lane 1:** `invincible-agent/sessions/2026-10-12-packet-to-lane-01-fin-byte-stable-export-pr50-and-the-ingress-truncates-too-pr49.md` (untracked).
- **The fleet is on `e977c32b`** (rolled 13:33Z, not by this lane).
- **Next:**
  - after #50 rolls, export the same two cost answers twice through the ingress and expect one sha. Scratchpad script `dl_ingress3.py`; the TLS pin is the presented self-signed wildcard;
  - the cortex-ui `documents[]` walk is still pending.

## Update 2026-10-10: merged, live on 187, dist fork closed

- **Merged** in the ruled order: #11 `ae01d904`, #18 `bc2e730b`, #21 `f66a2da5`. Lane 1 then merged #11 at `443cebd8`.
- **Still open on PR #11** (OPEN, MERGEABLE, head `1b5dd9d3`):
  - `592d08be`: the `build_html` fakes are signature-bound through `_html_stub`;
  - `1b5dd9d3`: comments on the two sentinel fakes.

  Lane 1 merges them.
- **Live on 187** (bff, cost and fin at `5b2a16a2`), walked as alice:
  - A mixed board (cost, fin, cost) returns 200 `partial`. Cost exists; fin failed with `not_in_model` / "not a ratified template", 7 keys.
  - A cost-only board is unchanged.
  - The customer page carries no trace of fin (Q3 checked on the downloaded bytes).
- **duckdb on master:** the seal gives 4 passed. With duckdb absent, the summary prints `duckdb-gated skips: 5`.
- **The dist fork is closed.** `--like` on the dist page reproduces sha256 `be4a4057…` at the same size, so dist holds the slice-1 page. The full `cmp` was denied, and I did not retry it.
- **Exporter view: not done, and not ours.** cortex-ui `3636f82` rejects `partial` and shows "response could not be read". I placed a correction packet: `cortex-ui/sessions/2026-10-10-packet-to-cortex-ui-correction-a-mixed-board-export-reads-as-unreadable-not-partial.md`. Re-check the exporter view when cortex-ui ships `documents[]`.
- **Report to Lane 1:** `invincible-agent/sessions/2026-10-10-packet-to-lane-01-fin-split-live-on-187-dist-fork-closed-exporter-view-is-cortex-uis.md` (untracked).
- **Open observations:**
  - the verb-path export sha moves on every export; the cause is not measured;
  - one port-forward download was truncated.
- **Next:**
  - wait for cortex-ui's `documents[]` change, then walk the mixed board in the UI as alice;
  - otherwise stand by.

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
