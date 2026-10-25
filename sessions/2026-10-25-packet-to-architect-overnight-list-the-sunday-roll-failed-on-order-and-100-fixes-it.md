to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-25
re: the overnight list, in order

## Asks (each one is yours or Chris's to decide)

1. **One approved Restate read** of case da479c74's invocation, to decide which of four 422s
   refused its task register (item 2). Until then the cause is a hypothesis.
2. **The `maintenance-bridge` label** (item 2). Either the content kind declares a vocabulary
   domain (`MAINTENANCE`), or `maintenance-bridge` enters `policy/domains.yaml` with grants. Until
   one of those lands, no person can see an OpenDDIL case.
3. **Merge OK for PR #99** (208 and ingest-v1). It changes the BFF image, so per your ruling it
   lands Monday.
4. **A ledger read route for ingest-v1, or not** (item 4). The doc says it is "not shipped". The
   sample client holds the act's `record_id` as its ledger entry.
5. **ADR-0060 section 6, items 5–8** (item 5): ca's review is folded in, and four points need a
   ruling.
6. **7f's `document` kind** (their 2026-10-25 packet to me, not on my list). Four platform
   declarations; I have acted on none:
   - `document` in `allowed_leaves`, with a label. This is their blocker, and it makes `document`
     a domain.
   - The overlay mirroring their `passes`.
   - `review_shape: document`, which needs SDK v0.9.11.
   - A `mesh:GeneralDocumentArtifact` leaf under `mesh:PDFArtifact`.
   - Their packet also names a red that predates it: `doors-export` overlay drift. Master's
     overlay already mirrors both passes (db7db75c), so their red reads another copy. Told
     them; not traced.
   - Who takes these?
   - Their second packet (the kinds for the second team) adds four more, all yours:
     - `identity.document_identity` reads no title. `title` would be a new `LABEL_ALIASES` field,
       and it needs the labels the team's title blocks print.
     - No `schematic` kind until the team sends its file list. Register on a format, not on a word.
     - A `domain_type=None` kind writes nothing to the graph. Identity-only is fine; answerable
       is not. 7f asks that this and `document` be one decision, not two.
     - 7f's drift seal should read a pinned ref, not our working tree.
   - It also found `maintenance-fault-event` on our side only. That is the event branch (it seeds
     the case and runs no pass), so I told 7f to allow-list it with that reason, not register it.
7. **Widen `s1000d_fault_walk`, or not** (item 6). The brief says "fix the retrieval ones". I read
   that as not, on its face, ruling a change to the walk contract. Yes means: add the two selects
   and their `returns`, regenerate `mrad.ttl` from doc-tools #131, and remove three markers (four
   with the regeneration).
8. **fin's finance canvas: PRs #97, then #98** (their 2026-10-25 packet to me, not on my list).
   - Each needs a cortex-bff roll; #98 also needs presentation-agent. Those are image changes,
     so by your Sunday/Monday split they go with Monday's roll, not today's chart-only one.
   - #98 widens `test_the_alias_returns_ONLY_artifact_ids` by `template_id`, and fin asks for a
     ruling on that.
   - #97 also fixes a live defect: every chat-routed `mesh:seedCanvas` builds the portfolio board,
     whatever template it named.
   - I have merged neither. Merge OK, and which roll?
9. **When the cortex-ui readback fix (PR #100) ships.** Sunday's roll left revision 217 `failed`
   on a correct realm (see "The Sunday roll"). #100 needs a chart bump, and a bump restarts every
   pod. I propose 0.4.70 rides Monday's 208 roll rather than a second Sunday roll. Merge OK?

## The Sunday roll: 0.4.69, revision 217, failed on a correct realm

- **Conditions met:**
  - rolled from 09:37:07Z, under the lock, after the 07:00Z gate;
  - tr's readback had been pulled at 08:14Z, and tr released its pod;
  - the Dagster in-flight read was empty;
  - worker6 was Ready.
  - It was a chart-only change, as you split it. The images are held at `867813be`.
- **The failure.** At 09:44:10Z the post-upgrade hook `iagent-realm-reconcile` ended in
  `BackoffLimitExceeded`.
  - The converge PUT replaced cortex-ui's `["*"]` with the two literals, and the live client
    holds exactly those two.
  - Keycloak serves the set in its own order, and our readback compares the array as text. It
    printed FAIL on the reversed pair.
  - The converge compare has the same defect: it re-PUTs on every run.
  - Our test double returned PUT order, so #91's arms could not see it.
  - `prime-substrate` and `engine-reregister` did not run, because they come after the hook.
    Engines register at startup anyway.
- **The fix, PR #100.**
  - It compares the members as a set in both places, and the double now serves those fields
    reversed.
  - Against the unfixed template, exactly the two arms matching the live failure go red. With the
    fix, 25 pass.
  - Four mutants, one per compare, each turn their named arm red.
  - The other files that share the double pass.
  - It carries no version bump (ask 9).
  - `docs/releases/0.4.69.md` is in the same PR.
- **Live, read after the roll:**
  - 7 of 7 nodes Ready;
  - 33 of 33 deployments and every StatefulSet ready;
  - 19 services at `867813be`;
  - every other readback line `ok`, `training-workbench` included.
  - The census exits 3 on 13 ingest-written data edges with no attribution (not verbs). It also
    reports one malformed `explain` form REMOVED. `explain` itself is live.
- **wb.** The auth endpoint admits `training-workbench` (200). It now refuses `cortex-ui` with
  wb's redirect (400 `redirect_uri`); the controls are 200 for its own origin and
  `Client not found` for an unknown id.
  - So wb's borrow ended today, not Monday as my 10-24 packet said.
  - The readback packet is in wb's sessions/, telling them to switch today.
- **Brokered login as atlantia: pass.** Deep links: see item 2.
- **Not run:** the `roll-litany.sh` health legs.
- The roll lock is released.

## 1. Release-tag race: fixed and repaired

- PR #93 merged as `db7db75c`.
  - The `release` job in `build-containers.yml` now `needs: build` for the same commit, and it fails
    when any of the 19 images is missing.
  - `scripts/retag_images_by_digest.py` treats a tag that already names another digest as a
    conflict. One conflict anywhere means nothing is tagged anywhere.
- Repair dispatches, each at its release sha:
  - 0.4.68: run 40163650736;
  - 0.4.69: run 40163755303.
- Each tagged 19 of 19, with 0 digest conflicts. The 0.4.69 notes record both under "repair".

## 2. Case da479c74, read-only as four actors

Read-only, ~04:30–05:10Z, against images at `867813be`. Nothing acted on the case.

**Verdict: the expectations do not hold, and the code is behaving as written.**
- **One id end to end: yes.** The BFF log shows one id throughout:
  - the ingest at 02:48:49Z returned 200;
  - the task register at 02:48:51.05Z;
  - the case summary at 02:48:51.30Z returned 200;
  - then `GET /cases/<id>/action` every ~30 s, which answers 404 `no_action_record`.
  - No spliced or second id appears.
- **Tasks live: no.** The task register answered **422**. At `867813be` the runner treats a 4xx as
  terminal, so the instance failed and released its state.
  - Which of the four 422s it was is **undecided**. The leading candidate is
    `no_entitled_recipients`: an `owning_tier` other than `ORG`/`edge-01`. That is a hypothesis.
  - Deciding it needs ask 1, one Restate read.
- **Visible to the four: none.**
  - Each walk opens `/case/<id>?idp=openddil`, and the case's state reads absent (404).
  - The case's only label is `maintenance-bridge`: the content kind's registered domain, with
    every definition's `classification` null.
  - That word is not in `policy/domains.yaml`, so no person holds a cell for it.
  - liaison.coalition holds no cell under either reading.
  - Ask 2.
- **The 320A verb is absent**: 0 files at `867813be`, 4 at the `d412c8b6` control.
- **The denial is in force.** The walk spec freezes both ids and aborts non-GETs to them. The
  atlantia wrapper names only da479c74; d1a7ee0b is dropped.
- **For Monday:** if the instance failed on the 422, Chris's brokered run has no task to act on.
  It needs the event re-driven once asks 1 and 2 are settled.

**Deep-link walk after the roll** (atlantia, brokered, `--trace off`):
- **A**, `/case/da479c74-85a8-5e80-98b8-b0613de01663?idp=openddil`, read-only: pass.
  - The panel header shows the id.
  - The case state reads absent (404), the same as before the roll, so ask 2 still stands.
  - `replaceState` goes to `/`.
  - No case write was attempted.
- **B**, `/ask?q=`: pass. The composer holds the question, unsent.

## 3. 208

- 208 is committed at `aecc87b4` on `lane/01-ingest-v1` and is in PR #99. At review, the status
  row names the open empty-confirm task. `review_shape`, `account` and `extraction_defect` are
  `{task_id, edits}`. ingest-v1 goes to 1.1.0.
- Verb health is in `scripts/version_census.py`, per your 10-24 ruling. It fails on a zero count or
  on a declared verb that no live edge carries.
  - **Gap:** `policy/graphs` rows count toward the walked total, but no verbs are read from them. A
    verb only a graph declares is therefore not owed.
- 320A is cut at Monday 18:00 from `lane/74-planned-inspection-interval` at `d412c8b6`.

## 4. ingest-v1 client

- `samples/ingest_client.py` and `docs/api/ingest-v1.md` section 1 are at `cf4d44bb`, in PR #99.
  The client drops, polls, reads the extraction, promotes or rejects, and reads its ledger entry.
- Its drift test has 10 arms:
  - the routes against the OpenAPI, and the keys against each 200 schema;
  - two AST arms that stop a URL or a body read bypassing the tables;
  - a control;
  - the client driven against the real app, from drop to a replayed promote.
  - 4 of 4 mutants turn their named arm red.
- **A departure, which you can reverse:** `POST /ingest` now accepts a blank or absent
  `on_behalf_of` as the caller.
  - The page said "send it blank to mean myself" from 1.0.0 on, and `_admit_on_behalf_of` already
    did that. But `Form(...)` answered a blank with 422 `missing`, so the work team's first drop
    would have failed.
  - It is a loosening, so every request that worked before still works. ingest-v1 goes to 1.2.0.
- **"Read ledger":** there is no route for it (ask 4). The client holds the act's `record_id`, and
  a repeat decision replays it.

## 5. ADR-0060

- ca reviewed it on 10-24, and the review is folded in at `11be1ec4` on `lane/01-adr-0060`. It
  went to ca only.
- Settled in the text: the descriptor's per-class identity and parent fields are not the row's
  `identity_field` and `parent_link_field`, and the row's fields stay where they are.
- Proposed for your ruling: the origin rule runs inside `nominate`, before `limit`.
- Open: ArtifactRef (a) or (b); whether EntityVerb shares `verbs_for`'s registry or is a sibling;
  moving `visible_by_origin` into the SDK.

## 6. Ask-the-manual on MRAD-ARR-0417

- **Where it is:** the seal and the note are at `0ea8617d` on `lane/01-ask-the-manual`:
  - `tests/test_ask_the_manual_mrad_arr_0417.py`;
  - `docs/measurements/2026-10-25-ask-the-manual-mrad-arr-0417.md`.
- **What it runs:** the real `s1000d_fault_walk` declaration over `mrad.ttl`.
- **Score:**
  - 6 of 10 questions are answered at data-module level.
  - 4 of 10 are answered at an element below the module: the fault code, the part, the ICN and the interval.
  - **0 of 10 give the paragraph or step text** a mechanic reads.
- **Safety:** the walk sends a mechanic to 520A without its "Disconnect power before removal."
  warning. doc-tools' S1000D parser never emits it, so it is also missing from the chunks.
- **The misses, by kind**, each a strict xfail:
  - **Retrieval, ours:** tools, the gasket and screws, the figure title. All three are in the
    triples, and the walk has no select for them. **Not fixed**, because each fix widens
    `walk-MRAD-ARR-0417.json`, which changes only by ruling. Two selects (`tools`,
    `ipd_items`) are written in the note and were run over the fixture. Ask 7.
  - **Extraction, 7f's:** the warning, 421A's isolation tree (the condition for "replace"), the
    tool name, and the 320A paragraph text. Packeted, warning first. 7f's doc-tools **PR #170**
    (open) reports all four closed, in the graph and the chunks. That is their report; I have not
    measured it.
  - **A fifth that #170 leaves.** S1000D procedure step text is in the graph (#131) but in no
    chunk: the chunker's step branch reads a root predicate that the S1000D parser never emits.
    Read from the code at #170's head, not run. Packeted to 7f with the control.
  - **Fixture lag, ours:** step text and order. doc-tools has emitted them since #131, and our
    `mrad.ttl` predates that. Regenerating it moves the walk contract's own input, so it waits on
    the same ruling.
- **Two mutants**, each turning exactly its named arm red. Restores checked with `cmp`.

## Not measured

- `/ingest/mine` now makes one defect read per row. That cost has not been measured.
- Verb health (#99) has not run against the live registry. The post-roll census ran 0.4.69's `version_census.py`, which predates it. It runs at the 208 roll.
