to: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-10-10
re: your Q1–Q3 answers and the origin-on-promotion ruling -- built, sealed, one PR; ten questions

# gov: origin enforced at read, recorded on promotion

## PRs

- **PR #7** (merged): its description now carries findings 2–4. Finding 3 is measured: the old
  string-match test stays green under all four WHERE mutants; the sqlite test reds all four.
- **PR [#32](https://github.com/edgy-solutions/invincible-agent/pull/32)** (lane/gov → master, open): commits `164420e5`, `b02b49bd`, `25c339cf`, `22c9d267`.
  A trial merge against `origin/master` (`3976a9e0`) is clean. The only file both sides touch is
  `gateway.py`; master's hunk there is the action-record route, which writes no origin property.
  **No roll was done.**
- **PR [#39](https://github.com/edgy-solutions/invincible-agent/pull/39)** (`lane/gov-resolve-instance` → `lane/gov`, open, tip `ac6e4ff0`): the Q7 gate on `/resolve_instance`, plus S (ruling (b)), P (Q8 behind one flag), and the outage seal re-derived at eleven. 187 merged it at `2999bdca`, and that merge is held until 187 re-merges `ac6e4ff0`.
- **PR [#45](https://github.com/edgy-solutions/invincible-agent/pull/45)** (`lane/gov-enumerate-gate` → `lane/gov-resolve-instance`, open, tip `9393ff08`): ruling (d), the enumerate gate. It merges lane/74's #40 (`311999f4`).
- **#39 and #45 were ACCEPTED by the architect on 2026-10-11.**
- **PR [#47](https://github.com/edgy-solutions/invincible-agent/pull/47)** (`lane/gov-caller-census` → `lane/gov-enumerate-gate`, open, tip `4f172cda`): Day 2's caller census. It seals "a service identity is never a grant" at the callers. Since 2026-10-12 it merges lane/74's #48 (`d7f8f3c1`).

## What landed

| commit | what |
| --- | --- |
| `164420e5` | Q3: `get_status_for`'s real WHERE clause runs against in-memory sqlite and replaces the string match. |
| `b02b49bd` | Q2: entitlement at READ, on the sources of engine-o's `/notice_parts`. |
| `25c339cf` | Your ruling: a promotion attests origin = D at the steward rung, the dropper cannot attest, plus the backfill. |
| `22c9d267` | The awaiting_origin steward case end to end: the real writers and the real reader joined through one graph. |

**`b02b49bd`, read side.**
- **One decider.** `agent_fleet/utils/origin_entitlement.py` holds the decider; `src/iagent/origin.py` is now a re-export shim, so the BFF and engine-o run the same `can_consume` / `origin_visible`.
- **`notice_parts.source_visibility`, in order:**
  1. Seeded content → visible.
  2. The dropper → visible.
  3. No artifact, or not promoted → withheld.
  4. Origin absent or unresolved → withheld.
  5. Origin not consumable by the caller's domains → withheld, with **no Topaz call** (no 503 existence oracle).
  6. Otherwise, program membership decides, and only if the origin names a program.
- **A withheld notice answers byte-identical to an unknown one.**
- **The image now ships the table.** `Dockerfile.agent` ships `policy/domain_consumption.yaml`. Without it, engine-o's loader fails closed to `{}` and withholds every drop-derived source.

**`25c339cf`, write side.**
- **What gets written:** `attest_origin` writes `origin_owner_domain=D`, `origin_resolved_by="steward"`, `origin_evidence="steward_attestation:<record_id>"`.
- **Where D comes from:** the `document_promotion:<D>` audience the steward was authorized on, never the payload. An audience with no domain is a 422 before any write.
- **Never downgrades:** an existing `record` or `steward` origin is kept.
- **Dropper refusal:** PROMOTED by `dropped_by.authz_id` or `dropped_by.on_behalf_of` is a 403 `dropper_cannot_attest_origin` before the ledger write. The gateway now files `on_behalf_of`.
- **Backfill:** `scripts/backfill_promotion_origin.py` goes through the same `attest_origin`. It is a dry run by default (`--apply` to write), never creates a node, and skips and lists an unparseable audience rather than guessing it.

## Your four tests

| ruling's test | where |
| --- | --- |
| promotion writes origin + rung | `tests/test_promotion_records_origin.py` (exact payload, SDK-validated) |
| non-consuming domain withheld | `tests/security/test_notice_sources_by_origin.py` (failing first: 17 red on HEAD, on assertions) |
| rejection stays dropper-only | `tests/security/test_steward_origin_case_end_to_end.py` arm 1, plus `test_promotion_records_origin` (a rejection writes no origin) |
| migration backfills, then a no-op | `test_promotion_records_origin` (counts and zero writes on the second run) and the e2e arm 6 (the reader reads what the backfill wrote) |

## Tests run

Every file was run alone and gated; none of them is the full suite (that is Lane 1's).

| file | result |
| --- | --- |
| test_notice_sources_by_origin (new) | 21 passed |
| test_promotion_records_origin (new) | 22 passed |
| test_steward_origin_case_end_to_end (new) | 8 passed |
| test_ingest_status_projection | 42 passed |
| test_origin_writer | 9 passed |
| test_notice_parts_provenance | 21 passed |
| test_a_document_is_promoted_on_the_approval_plane | 73 passed |
| test_gateway_ingest_routes | 66 passed |
| test_promotion_payload_is_derived_from_the_extraction | 26 passed |
| test_an_origin_suggestion_runs_as_a_case | 17 passed |

Earlier in the work, also green: test_origin_visibility 21, test_origin_across_the_kind_tree 52,
test_origin_resolver 7, test_ingest_retry_route 14, test_the_promotion_graph_and_index_homes 48,
test_the_promotion_stores_keep_the_record_and_move_the_objects 18, test_mesh_writers_conform 63
(8 skipped), and the flat-layout and image-layout import tests.

## Mutants

Every mutant was restored and checked with `cmp`. No crash was counted as a red.

**Read check (new file):**
- M-a: arm 4 red.
- M-b (the duplicate `can_consume` removed): arm 9 red. It kept: it is what enforces "pure check before Topaz".
- M-c: arms 2 and 11 red.
- M-d: the blank-dropper arms red.
- M-e: 15 arms red.
- M-f: arms 3, 5, 6 and 9 red.

**Promotion (new file):** M1 (dropper refusal removed), M2 (record keep dropped), M3 (wrong rung), M4 (D from the payload) and M5 (backfill skips `node_exists`) each red a named arm. M3b, which also sets the validator to "record", reds as an SDK `ValidationError` ("requires evidence").

**The join (the point of the e2e file).** Each mutant was run against the e2e file and against the per-piece file:

| mutant | e2e file (red arms) | per-piece file |
| --- | --- | --- |
| J1: origin_writer writes `origin_domain` | arms 2, 3, 3-FINANCE | `test_origin_writer`: red (happy-path spec shape) |
| J2: attest_origin writes `resolved_by` | arms 4, 6 | `test_promotion_records_origin`: red (store payload, backfill) |
| J3: cypher reads `a.owner_domain` | arms 2, 3, 3-FINANCE, 4, 6 | `test_notice_sources_by_origin`: red **only on a cypher-TEXT assertion**; its row-fed behavioural arms stay green |
| J4: `_apply` skips `attest_origin` | arm 4 | not run |

The per-piece files do notice J1–J3, but J3's per-piece catch is a check on the statement's
text, not on its behaviour. The e2e file is the only one that catches a read-side rename by
what the reader then returns.

## Answers received 2026-10-10, and what was done

- **Q1 answered, built: `38cebe0f`.**
  - The ruling: the gateway was wrong. `visible_by_origin` in `agent_fleet/utils/origin_entitlement.py` is now the one rule, and both engine-o's `read_notice_parts` and the gateway's `_origin_visible_to_caller` call it.
  - A program-less origin is decided by `can_consume` alone.
  - `tests/security/test_one_origin_rule_both_callers.py` (30 passed) runs one truth table through the helper, the real gateway function and engine-o's real reader.
  - Mutants:
    - D1 (the gateway's old guard re-added): reds the gateway column only.
    - D2 (membership asked before consumption): reds all three columns.
    - D3 (member always True): reds all three columns.
    - D4 (engine-o skips the helper): reds the engine-o column only.
    - D5 (an explicit blank-owner guard): quiet, because `can_consume` already refuses a blank owner. The line was deleted, and the measurement is recorded in the docstring.
  - **Reversed deliberately:** PR #7 sealed a "no-program" record as "half an origin is no origin" in `test_origin_across_the_kind_tree.py`. It is now its own arm (visible to a consumer, Topaz not asked), with a control that differs only in the viewer's domains (51 passed).
  - Not covered by the Q1 change: the AnswerArtifact read carries no rung, and no writer in this repo sets an origin on an AnswerArtifact today. Engine-o's "unresolved → withheld" precondition has no gateway twin because there is nothing to read it from.
- **Release:**
  - PR #32 goes in **rev 187, not 186**, with its own PCN re-walk.
  - The backfill runs live as part of the 187 roll, by Lane 1 (authorized).
  - Lane 1: run it straight after the roll and before the re-walk. Until it runs, promoted drops with no origin are withheld from everyone but the dropper.
- **Q2–Q8 and Q10 answered later on 2026-10-10.** What was done for each is in the next section.

## Answers to Q2–Q10, and what was done

- **AnswerArtifact "how resolved".** Not built. The rung field goes on the write path when something first writes an origin there, not before. This is noted in the PR #32 body.
- **Q2, an accept files the promotion.** BUILT at `0380bd50`.
  - The behaviour:
    - A steward's accept on an `awaiting_origin` row files `document_promotion:<owner_domain>`, with the domain taken from the origin and not the kind, and moves the row to `review`. The task is filed first, the status moves second.
    - If filing is refused, the origin stays written and the row stays put. The refusal is named in the route's answer.
    - A reject stays terminal and dropper-only.
    - The stage route now keeps the `extraction_ref` on an `awaiting_origin` row, so the accept can build the payload.
  - **A premise correction.** Your ruling says the accept records `resolved_by="steward"`. Every suggestion produced today is record-backed, so the accept writes `"record"`, and the later promotion keeps it rather than downgrading it.
    - Engine-o treats both rungs the same: visible to consumers.
    - I left the writer's mapping alone. Say if you want a steward accept of a record-backed suggestion to write `"steward"` instead.
  - **Open, Q2b.** The suggestion case opens at `POST /ingest`, before extraction. If the steward accepts while the row is still `received` or `extracting`, nothing is filed, and the row later lands at `awaiting_origin` with an origin and no task.
    - Is that a race worth closing? If so, should the stage route's domainless branch file against an already-accepted origin?
  - **Open, Q2c.** If filing is refused after the origin is written, the row stays at `awaiting_origin`, which the retry route treats as terminal (409). So there is no retry path.
    - Should the retry route re-run the filing for an `awaiting_origin` row that has an accepted origin?
  - **Arm 2 of the e2e seal is rewritten** to the new behaviour:
    - The steward accepts through the real route, the task is filed, and the content is still dropper-only.
    - The real `promotion.act` on the filed payload then opens it to a consumer (rung kept `record`) and refuses the dropper.
    - Arm 1 now also asserts that no task is filed and that the row stays at `awaiting_origin`.
  - **Runs:**
    - origin write route: 24 passed (+8 arms);
    - ingest routes: 66;
    - the e2e seal: 8;
    - neighbours: suggestion case 17, retry 14, status projection 42, approval plane 73.
  - **Mutants**, each restored and checked with `cmp` and `git diff`:

    | mutant | red arms |
    | --- | --- |
    | E1 no filing on accept | route (a), (d)×2, (e), (f)×2; e2e arm 2 |
    | E2 the kind decides the domain | the same set as E1 |
    | E3 status moved before the task is filed | route (a), (d)×2 |
    | E4 filing on `write_refused` | route (b) |
    | E5 filing at any stage | route (c) |
    | E6 `extraction_ref` not kept by the stage route | the ingest-routes arm only |

  - **A blind spot, recorded:** e2e arm 2 does not see E6, because its row fake preloads `extraction_ref`. The ingest-routes arm is the only seal on that join.
- **Q3, the identity seal.** BUILT at `5aeeec21`, test only: green on today's code, so nothing needed fixing.
  - 3 passed, each test against a control that differs only in the asserted values.
  - Mutants: Q3a (the gateway honours a body `user_email`) reds the gateway arm; Q3b (`task_def` keys merged into the specialist payload) reds the specialist arm.
  - The seal: a body-asserted `user_email`, `entitled_domains` or `user_id` changes nothing the gateway hands the supervisor.
  - The same holds for a `task_def` carrying them into the specialist and fallback dispatches.
  - The user token reaching specialists is noted in the PR as Lane 1's follow-up.
- **Q4, confirmed.** No change.
- **Q5, the legacy log.** BUILT at `06636572`.
  - One warning per PROMOTED act whose task has no `dropped_by`; none for REJECTED or when `dropped_by` is present.
  - 25 passed (+3 arms). Mutants L1 (log removed) and L2 (log on every promotion) each red their arm.
- **Q6.** Noted in the PR body: Lane 1 lists and refiles live tasks with a non-domain audience in the 187 roll. Until then they cannot be promoted.
- **Q7, the Jena verbs.** TRACED, and the gate is BUILT in PR #39 (`69d72b59` on `lane/gov-resolve-instance`, stacked on #32). Ruled 2026-10-10: trace plus a gate PR for `resolve_instance`.
  - Both blockers below are closed there: the caller reaches the verb through `/resolve` and `/fill_slots`, and the join goes notice IRI → Neo4j node (the same lookup `/notice_parts` uses) and component → `pcn:subjectToNotice` in Jena. `prov:wasDerivedFrom` was not needed: no drop producer sets it.
  - One verdict function, `notice_parts.notice_visible`, serves both callers. Runs: the truth table with a third column, 40 passed; the new file, 22. Mutants G1–G8 each red their arms (table in the PR).
  - **`resolve_instance`: YES.**
    - Doc-tools' user-drop parser writes the notice into Jena `SUSTAINMENT_INSTANCES` at extraction, before any promotion (`doc_tools/plugins/sustainment.py:1972-2023`). It writes the notice IRI `http://internal/sustainment/doc/{id}` and component IRIs `http://internal/components/{mpn}`.
    - Engine-o's SUSTAINMENT provider returns them with no origin filter, and the request carries no caller (`ontology_service/main.py:5093-5104`, `sustainment_instance_provider.py:26-31`).
    - It also leaks existence: `/notice_parts` answers a withheld notice exactly as an unknown one, but `resolve_instance` still returns it as a candidate.
  - **`instances_by_property`: NO, under the deployed config.**
    - It reads only `pcn:dispositionState`, which only `/write_item_state` writes, from the review → dispatch flow.
    - That flow watches `sustainment/`, but drops land under `ingress-user/`.
    - It becomes YES if any values file widens `REVIEW_WATCH_PREFIX` to `ingress-user/`. I have not read the deployed values.
  - **`declared_query`: NO.** The only declared verb (`s1000d_fault_walk`) reads `mil:*DataModule`, which only the XML S1000D ingest writes. The user-drop sensor accepts PDF only.
  - **Engine E (Neo4j) `resolveInstance`:** drop-derived `WorkInstruction` nodes carry no IRI field and are skipped. It becomes YES if a sync later adds a `uri` to them. Unverified.
  - **The proposal:** `resolve_instance` gets `visible_by_origin` in a follow-up PR (187 or 188), the same helper and no new rule. Two blockers before that PR:
    1. The verb's request carries no caller today, so the caller's identity has to reach it first. That is the same chain as Q3.
    2. A Jena IRI has to be joined to its `IngestArtifact`. The Jena triples carry `prov:wasDerivedFrom`; I have not yet checked whether it names the ingest_id.
- **Q8, `provenance_ingest_id`.** TRACED; NOT CHANGED, because the ruling as worded would hide all seeded content today. Ruled 2026-10-10: the change is parked behind doc-tools stamping seed provenance. Until then, no provenance (and, in #39, no graph row) reads as seeded. #39's arms covering that behaviour name the precondition, so they flip together when the stamp lands.
  - **The one writer** of `provenance_ingest_id` on a `SustainmentNotice` is doc-tools' `SustainmentPlugin.to_graph_queries` (`sustainment.py:1923-1950`).
    - It runs only on the user-drop path, from `POST /ingest`, which always puts an `ingest_id` in the block. Nothing in this repo or the SDK writes notices.
  - **The seeded path writes no seed provenance at all.** That is the vetted `sustainment/inbound/` sensor, then `build_knowledge_graph`, then `sustainment.py:1876-1882`.
    - It sets only `pub_date`, `mfr`, `mfr_parent`, `type`, `revision`, `doc_level_ltb_date` and `needs_review`.
    - So "no `provenance_ingest_id` and no seed provenance → withheld" would withhold every seeded notice: the 12 the tests cite and the whole vetted corpus.
  - **To apply the ruling,** doc-tools' vetted path would first have to stamp a seed-provenance property on the notice. The manifest already carries `source_key` and `pipeline_version`, but neither reaches Neo4j. Then the existing seeded notices need a backfill.
  - **Two hazards the trace found, both today:**
    1. The drop's provenance stamp is a separate query from the one that creates the notice, and its failure is only logged (`semantic_assets.py:781`). A drop whose stamp failed reads as seeded and is visible.
    2. Notices merge on `{id}`. A drop whose `doc_id` matches a seeded notice stamps `provenance_*` onto the seeded node, and a later vetted re-ingest never clears it.
  - Both are doc-tools' to fix. Ruling needed: who stamps seed provenance, and is the change gated until that backfill runs?
- **Q10, packet addresses.** BUILT at `9766f984`.
  - The extended address test: 46 passed. The seat test: 38 passed.
  - Mutants:
    - P1 (the form made unmatchable): 5 reds.
    - P2 (an internal repo accepted): 3 reds.
    - P3 (any branch accepted): 1 red.
    - Plain removal of the form crashed with IndexError, which was not counted as a red.
  - **Measured: gov's own scanner could not spell the ruled address.** `to: cortex-ui/master` parsed UNADDRESSED, because the grammar knew only `<repo>/lane/<x>`, `<repo>/seat/<x>` and `<Name>'s agent`.
  - **The fix** adds an external `<repo>/master` form. It accepts `master` only, for another repo only; `invincible-agent/master` stays unaddressed.
  - **`for:` lines:** a `for:`-only packet already parses as unaddressed. It is now sealed.
  - **The census does not reproduce "8 rows": it finds 20 distinct packets.** These are the packets in `invincible-agent/sessions` or `ia-gov/sessions` whose `to:` line names cortex in any form other than `cortex-ui/master`.
    - The command: the first `to:` line in a packet's first 40 lines matching `cortex`, excluding `to: cortex-ui/master`, deduplicated by filename across the two trees.
    - Your 8 may be a sub-window. I can't tell which.
  - **None was written by gov, and I edited none of them.** Each sender reheads its own:

    | sender (`from:`) | packets |
    | --- | --- |
    | lane/01, including the ones signed `invincible-agent/master` | 09-23 please-copy, 09-26 forecastrow (`to: cortex-ui`, which parses as a bare lane `cortex-ui`), 09-26 completeness-count, 09-26 restating-count, 09-30 built-export, 09-30 ingest-seam, 10-01 reason-required-card, 10-01 ingest-routes-rev-163 |
    | lane/ca | 09-30 mirror-source v0.9.5, 09-30 provenance-block (multi-recipient), 09-30 v0.9.5-cut (multi-recipient), 10-01 mirror-source write-node, 10-02 origin-and-system-of-record, 10-06 mirror-source maintenance-bridge, 10-08 mirror-source v0.9.9 |
    | lane/saf | 10-08 bind-the-two-fracas-classes, 10-08 fracas-bindings-final-shape, 10-09 draft-risk-assessment (all `to: cortex-ui/lane/cortex-ts`) |
    | no `from:` line | 09-18 dispatch source-ledger, 09-19 dispatch three-safety-rows (both `to: ia-cortex-60/lane/cortex-60`) |

  - **`for:`-only packets:** one, `friday-demo-runbook.md` (`for: Chris, at the keyboard on Friday`). It parses as unaddressed.
  - **A pre-existing red, not caused by this change:** `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED` fails on 15 unaddressed packets in `ia-gov/sessions`.
    - HEAD's scanner and the new one produce the same 15, and no packet's parsed address changes. I compared the two modules directly over the same directory.

Rulings issued 2026-10-10 (21:29 and 22:11): Q2–Q10 as above. #32 ships in rev 187.

## 2026-10-11: Q2b and Q2c built

**Where the wording comes from.** "Q2 state-function filing, Q2c retry" is your day plan. The exact Q2b/Q2c wording below is from my trace. I have not seen Chris's pasted 21:29/22:11 text, and will check against it before #32's next merge.

- **Q2b and Q2c: BUILT at `00374662`** on lane/gov, pushed. Filing is now a function of state.
  - `_file_promotion_if_ready(ingest_id, requested_by=...)` files if and only if the row is at `awaiting_origin` AND the artifact carries an accepted origin. Three places call it:
    - the accept route (as before);
    - the stage route, right after it moves a domainless row to `awaiting_origin`. That is Q2b, for an accept that landed while the row was still extracting;
    - the retry route, which no longer treats `awaiting_origin` as terminal. That is Q2c: filed → 200 `review`; no accepted origin → 409 `awaiting_origin`; an unreadable origin or a refused filing → 503 `promotion_not_filed`.
  - **The domain is read back from the store**, not taken from the request body. "Accepted" uses the same predicate as `notice_parts.source_visibility` (checked: an owner domain is present, and `resolved_by` is not empty or `unresolved`).
  - **A read that raises is an unknown origin, not an absent one.** Nothing is filed and the row stays put.
  - **`dropped_by` still comes from the row** (`submitted_by` / `on_behalf_of`), so the Q5 exclusion is unaffected. `requested_by` differs by route (case-runner service / stage caller / retrying user) and is attribution only.
  - **Runs**, one gated file each:

    | file | passed |
    | --- | --- |
    | new `test_promotion_filing_is_a_function_of_state` | 18 |
    | origin write route | 24 |
    | retry | 13 (`AWAITING_ORIGIN` left the terminal parametrization) |
    | ingest routes | 66 |
    | e2e seal | 8 |
    | `test_promotion_records_origin` | 25 |
    | approval plane | 73 |

  - **Mutants M1–M6**, each restored and checked with `cmp`. Each one reds the arm derived from its subject:

    | mutant | red arms |
    | --- | --- |
    | M1 the stage route skips the state function | the Q2b order arm and the one-predicate arm |
    | M2 `awaiting_origin` terminal again in retry | three retry arms |
    | M3 the reader accepts `unresolved` | its arm only |
    | M4 no status check | the order arm, the second-accept arm, and a neighbour on all 5 stages |
    | M5 status moved before filing | two arms |
    | M6 the domain read from the request body | its arm only |

  - **Two things found, not changed:**
    1. A retry of a row already at `review`, for a deliberately domainless kind, answers 422 `no_declared_domain`.
       - The shared helper resolves the domain from the kind registry before it looks for the task, and the review retry passes no domain.
       - So an origin-filed row can never take retry's already-filed path. This predates Q2.
       - Should the review retry read the stored origin, the same way?
    2. On the stage route, a refused filing answers `NO_TASK_AWAITING_ORIGIN` and only logs the reason.
- **Q6: BUILT on lane/gov.** The listing is for Lane 1's rev-187 refile: `scripts/backfill_promotion_origin.py --list-old-audiences`.
  - It needs only `PROJECTOR_POSTGRES_DSN`, never touches Neo4j, and writes nothing.
  - "Old" means the real `promotion.domain_of` refuses the audience.
  - Each line carries `task_id`, `ingest_id`, `audience`, `proposed_domain`, `proposed_from` and `created_at`. The proposed domain comes from payload `review_pool`, else the legacy `domain`, else `undecided`; never from the audience.
  - Exit codes: 0 none, 1 some, 2 could not look.
  - The new file passes 7; `test_promotion_records_origin` passes 25 and the e2e seal 8. Mutants B1–B4 each red their arm.
  - **Not run live.** It has had no DSN here; Lane 1 runs it in the roll.

## 2026-10-11: rulings (b), (d) and Q8 built; the outage seal re-derived

- **S, ruling (b): a service identity is never a grant.** Built on #39 at `657864f5`.
  - `origin_entitlement.is_person` is False for no caller, a blank caller, or `svc:`. It runs first in `notice_visible`, the one verdict `read_notice_parts`, `/resolve_instance` and now enumerate share.
  - A non-person sees seeded content only. No route refuses yet: the 422 `no_person` waits for lane/74's caller side of (a).
  - The new seal passes 11. Mutants S1–S3 each red their arms.
- **P, Q8 (parked behind doc-tools stamping seed provenance).** `SEED_PROVENANCE_STAMPED = False`, and both "seeded" branches read it, so behaviour is unchanged. The new seal passes 6, and mutants P1–P2 are red.
- **Wire arms deleted with the measurement.** In ten wire mutants, every one that failed gov's six wire arms also failed lane/74's `test_resolve_instance_hears_the_caller`, and only lane/74's killed W5. W3 is equivalent.
- **The outage seal, re-derived at eleven (`ac6e4ff0`).**
  - #39's link query is the eleventh `execute_sparql` site. **I shipped `657864f5` with that seal red** because I had not run the file.
  - The classification is read from the AST: scoped, with no `GRAPH`/`SERVICE`/`FROM`. The file passes 13, and a `FROM` mutant gives the named red.
  - The first mutant run survived: an escape collapsed to a backspace byte through a heredoc.
- **Ruling (d): the enumerate gate (#45).**
  - Members go through the same `_filter_sustainment_candidates`. All-withheld reads as `empty`, the count does not reveal what was withheld, and a failure answers 503.
  - The new seal passes 10, mutants E1–E5 are red, and nine keep-green files are green on `9393ff08`.
  - **Residual:** `too_many` is unfiltered, and its count includes anything withheld.
- **The retry collision (lane/01's packet, Q2c vs pin-driven).** I placed facts and costs, and asked for neither option.
  - Nothing calls `/ingest/{id}/retry` today.
  - Under (b), the `awaiting_origin` branch needs a pin exemption, or Q2c is unreachable.
  - **Waiting on your ruling.**
- **Checked (2026-10-11):** the architect confirmed the 21:29/22:11 rulings as Q2b (a state function), Q2c (a retry re-runs it) and Q8 (sealed behind seed-stamp). That matches what was built, so there is nothing to change.
- **Day 2:** done; see the next section.

## 2026-10-11: Day 2, the caller census, the AnswerArtifact check and the packet census

**1. Caller census: PR #47 (`d8e61dd2`).** The file is `tests/security/test_every_engine_o_caller_is_classified.py`; it passes 26.

- **What it derives:**
  - every POST to `/resolve`, `/resolve_instance`, `/fill_slots`, `/enumerate_instances` and `/analyze` across `agent_fleet/`, `src/`, `scripts/` and `setup/`, using a `.py` URL detector plus a `.sh` curl scan;
  - each site's class from its payload: PERSON or NO_PERSON, with DOMAINS_WITHOUT_PERSON as a sub-shape.
- **What it declares:** the split of PERSON into TOKEN and FORWARD.
- **There are 17 rows. NO_PERSON has 10 sites**, and they are the 422 `no_person` population:
  - review_composer;
  - run_resolver_corpus ×4;
  - verify_tier3_live;
  - phase1_stable_harness.sh;
  - elicitation_battery;
  - slot_fill_battery;
  - agent_routers → /analyze.
- **Mutants:**
  - M1–M5 are red: a class flip at review_composer, a class flip at `_resolve_subject`, a new site, a deleted row, and the domains shape.
  - X (the supervisor passing `user_email=""`) is green here and in `hears_the_caller`. It is red only in lane/74's `test_the_person_reaches_the_migrated_route.py`, so supervisor-hop provenance is theirs.
  - This corrects my earlier claim that `hears_the_caller` covered it.

**2. AnswerArtifact origin field: not built, because no writer exists.**
- I ran the tripwire's detector over 71 distinct blobs from 99 refs: `gateway.py` 51, `notice_parts.py` 6, `promotion_stores.py` 5, `answer_artifact_writer.py` 4, `artifact_reads.py` 3 and `origin_writer.py` 2.
- It found no AnswerArtifact origin site and no offender.

**3. Packet census, placed for lane/01.**
- There are 86 placed files. Master's parser misfiles 58 ruled-form packets until #32's Q10 parser lands with 187.
- There are 10 `from: lane/saf` packets with no repo prefix.

**Retry collision:** I restated (a) and (b) in one line each in the Day 2 digest to the architect. **RULED 2026-10-12: (a), no pin exemption needed.** 187 already carries (a), so gov changes nothing and Q2c's arm 4 stays as built.

## 2026-10-12: the census counts lane/74's five sites as having a person (#47, `4f172cda`)

- **The ruling:** "add a category for person derived from the artifact's ingest record so 74's five sites count as having a person".
- **`79f90f36` merges lane/74's #48 (`d7f8f3c1`)** into `lane/gov-caller-census`. The merge was clean and brings four commits, including master `c56a0ca2`. The census has to read 74's code to measure the move.
- **The five sites have two shapes, so there are two declared classes. This departs from the ruling's single name, and I flagged it in the packet to 74 (cc the architect):**
  - **INGEST_RECORD** (row 8, review_composer): the `user_email` value uses the `on_behalf_of` parameter, which the BFF fills from the ingest's status row.
  - **TEST_PERSONA** (rows 9–11, run_resolver_corpus, 4 sites): the `user_email` value is `_person()`, which reads `IA_CORPUS_ON_BEHALF_OF` and raises without it.
- **NO_PERSON is 5 sites** (rows 13–17). Lane/74 left them deliberately for the 422 to refuse.
- **UNDECIDED**, lane/74's finding: an unreadable payload used to count as NO_PERSON. It is now a red.
- **DOMAINS_WITHOUT_PERSON** is empty, and it is now derived over the whole census.
- **Mutants N1–N5 all give named reds.** Under N1 (the composer sends `""`), the count arm stays green and only the class arm catches it.
- **Test:** 26 passed.
- **Not run:** lane/74's own seals on the merged tree. The docstring says so.

## 2026-10-12 (2): a blank `user_email` is absent in every arm (#47, `8fc4d1e5`)

- **The ruling:** "two categories approved, accurately described beats one name. Blank "" user_email — make the count arm treat empty as absent, so both arms catch it."
- **One predicate decides PERSON in every arm.** `carries_person` is used by the derived class, arm C, arm D and arm E, for Python, in-process and shell sites.
- **What counts as absent:** a missing key; or any value found for it that is a blank literal (`""`, whitespace or `None`); or, at a shell site, `user_email":""`.
- **What stays out of scope:** a blank passed as a call argument (mutant X). Lane/74's seal owns it.
- **New control:** `test_CONTROL_a_blank_user_email_is_absent_never_a_person`.
- **Test:** 27 passed.
- **Mutants:**
  - **N1b** (composer `""`): red on row 8, DOMAINS_WITHOUT_PERSON and the count.
  - **N6** (dynamic_supervisor:429 stores `""`): red on row 1, DOMAINS_WITHOUT_PERSON and the count. **It survived the test at `4f172cda`** (26 passed, measured), which means a blank at a TOKEN row was invisible to every arm.
  - **N7** (`_bind_from_scope` passes `""`): red on row 7 and the count.
- **Packet placed:** `2026-10-12-packet-to-74-a-blank-user-email-is-now-absent-in-every-census-arm.md` (cc the architect).

## 2026-10-13: row 17 moves with #52; NO_PERSON is 4 (#47, `6780e7d9`)

- **The rulings (architect, 2026-10-12 13:13):** "gov: accepted; row 17 moves with #52 in the 188 landing; blank user_email = absent (done)."
- **`0eb0de7a` merges lane/74's #52 (`5902102b`).** #52 is based on a newer master, so the merge also brings in 29 rev-187 commits. The merge was clean.
  - Three packets that were untracked in ia-gov, and that master now tracks, blocked the merge. Each was byte-identical to master's copy. I backed them up, moved them aside, merged, and cmp'd them back.
- **Before the move**, on the merged tree, there were exactly 2 reds: row 17 and the count (4 vs 5). POPULATION was green, so rev 187 adds no caller site.
- **`6780e7d9`:** row 17 is now TEST_PERSONA, because `_smoke_person()` reads `IA_SMOKE_ON_BEHALF_OF` and raises without it. NO_PERSON is 4 (rows 13–16). 27 passed.
- **Mutants:**
  - R1 (no raise): red on row 17.
  - R2 (`""`): red on row 17 and the count.
  - R3 (`"svc:supervisor"`): red on row 17 only. The count arm treats a service literal as a person, so the TEST_PERSONA arm is the only guard for that shape.
- **Packet placed:** `2026-10-13-packet-to-01-for-188-take-47-at-6780e7d9-it-carries-52-and-moves-row-17.md` (cc the architect and 74).

## 2026-10-14: a `svc:` user_email is absent in every arm (#47, `bb0b5190`)

- **The ruling:** "a svc: literal counts as absent in every arm, same as blank; a service identity is never a person." It answers the question I raised on 2026-10-13, after R3.
- **The change:** `_is_blank` becomes `_names_nobody`, so `carries_person` treats a literal whose head is `svc:` as absent, the same as a blank.
  - The head can be a str constant, an f-string head or the left side of a `+`, matched case-insensitively.
  - At shell sites the rule matches `user_email":"svc:…`.
  - `u or "svc:x"` stays PERSON, the same as `u or ""`.
- **Control:** `test_CONTROL_a_svc_user_email_is_absent_never_a_person`, with checks on both sides.
- **Test:** 28 passed. No real site sends a `svc:` literal, so the classes and NO_PERSON (4) are unchanged.
- **Mutants**, each measured now and against the test at `6780e7d9`:
  - S1 (composer): now red on row 8, DOMAINS_WITHOUT_PERSON and the count. Before: row 8 only.
  - **S2** (DS:429 `"svc:supervisor"`): now red on row 1, DOMAINS_WITHOUT_PERSON and the count. **Before: survived (27 passed).**
  - **S3** (`_bind_from_scope` `"svc:engine-o"`): now red on row 7 and the count. **Before: survived (27 passed).**
  - S4 and S5 (agent_routers, a str and an f-string): now red on row 17 and the count. Before: row 17 only.
  - S6 (harness curl gains `svc:`): green, because the site stays NO_PERSON. Its control S6c (`a@b`) is red on row 14 and the count.
- **Packet placed:** `2026-10-14-packet-to-01-47-moved-to-bb0b5190-a-svc-user-email-is-absent-take-it-for-188.md` (cc the architect and 74).
- **Later the same day, the architect ruled:** "accepted; the engine-side 422 refusing svc: after 188b, as you say."

## 2026-10-14 (2): the visibility catch takes the stores' outage classes only (#54, `16aa5450`)

- **The ask:** lane/74's §4 (2026-10-11 packet): "catch what the lookup's stores actually raise … and let everything else answer 500 … The defence belongs to both routes."
- **The change:** a new branch `lane/gov-narrow-except`, stacked on #45, one commit.
  - `/resolve_instance` and `_gate_enumerated_members` now catch `_VISIBILITY_OUTAGE` and answer 503. Anything else answers 500.
  - `_VISIBILITY_OUTAGE` holds:
    - `SubstrateUnavailable` (execute_sparql's only escaping exception);
    - neo4j `ServiceUnavailable`, `SessionExpired` and `TransientError` (from `visible_notice_ids`);
    - `httpx.HTTPError` (from `program_membership` → Topaz).
  - **`ValueError` is excluded on purpose:** a garbled Topaz body is a defect. A 500 still fails closed.
  - The filter's "graph not connected" now raises `SubstrateUnavailable`, not `RuntimeError`.
  - `/resolve_instance`'s older 502 catch is narrowed to `SubstrateUnavailable`. It predates gov (`cac536e0`).
- **Tests** (gated, one file per run):

  | file | result |
  | --- | --- |
  | new seal `test_the_visibility_check_answers_503_only_for_an_outage.py` | 31 passed |
  | resolve withholds | 16 passed |
  | enumerate withholds | 10 passed |
  | `test_an_outage_is_not_an_empty_answer.py` | 13 passed |
  | `test_enumerate_fans_out.py` | 18 passed |

- **The withholds doubles now raise the real classes.** The old `RuntimeError` doubles, measured against the new `main.py`, are red on three arms (neo4j, link query, enumerate LOOKUP).
- **Before** (the new seal against `9393ff08`):
  - Red: the 12 defect arms (each defect came back as a 503) and the AST arm.
  - Crashed on a missing attribute, not red: the tuple, not-connected, outage and 502 arms.
- **Mutants M1–M5 are each red on a named arm** (see the PR body and the commit message).
  - **M1** (the gate back to `Exception`) leaves the enumerate seal green. That seal tests outages only; the new seal's defect arms catch M1.
- **Packet placed:** `2026-10-14-packet-to-74-section-4-built-pr-54-the-visibility-catch-is-the-stores-outage-classes-only.md` (cc the architect and 01).

## 2026-10-15: #54 approved; the kind-tree seal counts a group's members as recipients (#56, `77f5a795`)

- **The ruling:** "#54 approved. The kind-tree test must count a group grant as a recipient (group → members) — fix the test, Lane 1's work-instruction row lands behind it."
- **The trigger:** Lane 1's packet `2026-10-14-packet-to-gov-kind-tree-seal-reads-grant-to-only-…`. `document_promotion:MANUFACTURING` is `grant_to_groups: [manufacturing-stewards]` only (`050b3164`, on `lane/01-rev189`), and the seal read `grant_to` only.
  - Measured at `579dfadf` with a stand-in work-instruction row: 1 failed (that row's reviewer case), 64 passed.
- **The change:** a new branch `lane/gov-kind-tree-groups`, based on `lane/01-rev189`. PR #56 → `lane/01-rev189`, one commit, one file.
  - A recipient is a `grant_to` user, or a `users.yaml` member of a `grant_to_groups` group that `groups.yaml` declares. Memberless and undeclared groups reach nobody, as in `validate_policy.unusable_group_audiences`.
  - New arms:
    - a two-sided control (7 cases);
    - the join with `validate_policy`, over the real policy plus a fixture holding one group of each outcome;
    - every `document_promotion` audience reaches someone, and one of them is group-only.
  - Both policy loaders read UTF-8 explicitly. Both files hold non-ASCII bytes, and the platform default failed collection.
- **Tests** (gated, one file per run):
  - this file: 64 passed;
  - with the stand-in row: 74 passed, and the reviewer case PASSED (the stand-in was removed and never staged);
  - `test_a_task_audience_granted_to_a_group.py`: 16 passed.
- **Mutants:** K1–K3 (this file) and V1–V2 (`validate_policy`) are each red on a named arm.
  - On the first run, the join covered real policy only and K2 and K3 left it green: real policy holds no unusable group, so it only compared "fine" with "fine". The fixture half was added for that reason, and K2 and K3 were measured again.
- **Packet placed:** `2026-10-15-packet-to-lane-01-kind-tree-seal-counts-group-members-pr-56-your-row-can-land.md` (cc the architect).


## 2026-10-17: the `/ingest/{id}/source` 403 rule against its seal (review only; nothing built)

- **The brief (Day 2):** "the /ingest/{id}/source grant — review the 403 rule against the seal." The architect, 10-17: the route has been on master since `31d0590e` (193, rolled), and gov's 10-16 check was made before the merge.
- **What was reviewed:**
  - The rule: `_ingest_review_access` (`src/iagent/gateway.py:10646-10687` at master `5d8800e0`), the gate shared by `/extraction` and `/source`.
  - The seal: `tests/test_ingest_review_card_routes.py`, from `71cdc40b` (Lane 1, `lane/01-193`).
  - Done in a throwaway worktree at `5d8800e0` with its own venv. Baseline: 11 passed.
- **The rule as written:**
  - Absent or EVENT row → 404 `ingest_not_found`.
  - The caller casefold-equals `submitted_by` or `on_behalf_of` (blanks excluded) → allow, `dropped_by`.
  - Else, a non-empty caller, and `get_task_open_state("document_promotion:<id>")` is open with an audience, and `check_can_act(audience, caller)` → allow, `task_holder`.
  - Any exception → deny. Else 403 `not_entitled`.
  - All of this is decided before the store read, and every decision is audited.
- **Mutants** (each was gated, run against the seal, restored, cmp silent; `git diff` empty afterwards):

  | mutant | change | seal |
  | --- | --- | --- |
  | S1 | the task id → `document_promotion:not-this-ingest` | **green**, 11 passed |
  | S2 | `check_can_act` gets a literal `document_promotion:SUSTAINMENT`, not the task's audience | **green** |
  | S3 | the `except` sets `allowed = True` | **green** |
  | S4 | drop `state.get("open")` | red: `test_gate_dropper_holder_stranger_resolved_and_unknown`, `KeyError: 'detail'` at line 276 |
  | S5 | drop `and state.get("audience")` | **green** |
  | S7 | `on_behalf_of` → `""` | red: same test, `('extraction', 'carol@example.com') assert 403 == 200` at line 263 |

- **Why four clauses are unsealed.** The seal's stubs ignore their arguments: `get_task_open_state` is `lambda t: task`, and `check_can_act` is `lambda aud, who: who in holders`. So the seal decides whether the caller is a holder, but never checks which task or which audience the decision was made on.
- **Findings:**
  - **F1 (S1). Which task is consulted is unsealed.** A gate that read any open task would let the holder of document A's task read document B. Proposed: a stub keyed on the task id, and an arm where a holder of another ingest's open task gets a 403 with the store untouched.
  - **F2 (S2). The audience pass-through is unsealed.** Proposed: key the `check_can_act` stub on `(aud, who)`, with a holder of a different audience than the task's.
  - **F3 (S3). Fail-closed on exception is unsealed.** No arm raises. Proposed: an arm where `get_task_open_state` raises, and one where `check_can_act` raises. Each gives 403 `not_entitled`, `s3.calls == []`, and one deny audit line.
  - **F4 (S5). An open task with no audience is unsealed** (minor). The same arm as F3, with `{"open": True, "audience": ""}`.
  - **S4 is a red, but a fragile one.** The RESOLVED holder got a 200, and the test reads `r.json()["detail"]` before it asserts the status, so the failure is a `KeyError` and not the status assertion. Proposed: assert the status first.
  - **Positive controls:** S4 and S7 are red, so the seal does reach the open check and the `on_behalf_of` clause.
- **Questions for a ruling** (Q12, Q13 below):
  - **F5. An outage answers 403 `not_entitled`, not 503.** `check_can_act` returns False on any error (`human_tasks.py:216-217`), and the gate's own `except` denies. So a Topaz or task-store outage tells a real holder they are not entitled. That is fail-closed, which is right, but #54's ruled shape elsewhere is outage → 503.
  - **F6. A delegated drop's service can read the bytes.** On a delegated drop, `submitted_by` is the service's `authz_id` and `on_behalf_of` is the person (`gateway.py:10169`). The `dropped_by` clause matches either one, so a `svc:` caller gets every source it delegated. `_is_service_caller` (`gateway.py:10844`) is applied by retry but not by this gate. The 10-14 ruling ("a service identity is never a person") was made for engine O's arms. Does it reach this clause?
  - **F7, not a defect.** A holder through a group audience (bob via `manufacturing-stewards`) is decided inside Topaz, where the seal's stub cannot see. Only the live walk, `tests/e2e/walk_document_promotion.py` (written, not yet run), exercises it.
- **Not touched:** the seal is Lane 1's, so gov proposes arms and does not widen it.
- **Packet placed:** `2026-10-17-packet-to-lane-01-source-gate-seal-four-clauses-unsealed-two-questions.md` (cc the architect).

## 2026-10-17 (2): Q12 and Q13 built and sealed (#73, `d53d89ca`)

From the architect, via Chris: "S1 gap accepted; Lane 1 adopts your five arms before the seal counts. Q12: Topaz outage is 503, same as #54 — a holder of the task is never told not_entitled because a dependency is down. Q13: a service reads the source of drops it delegated because the delegate rule already grants it (it seeded them), not because it is "the submitter"; a service holding a review task counts for nothing. Seal both arms."

- **Where:** branch `lane/gov-review-gate-rulings`, from master `8ab9551a`, in a throwaway worktree with its own venv. PR #73 → master.
- **Q12, built:**
  - `human_tasks.can_act_or_unavailable` raises the fleet's one `AuthorizationUnavailable` (imported from `iagent.authz`, so it is the same module object as `auth.py`'s) on a transport error, a 5xx, or a body that is not JSON.
  - The gate maps that class and `psycopg2.Error` to 503 `authorization_unavailable`, and `HumanTaskConfigError` to 503 `hitl_unconfigured`. An unknown exception is still a fail-closed 403.
  - `check_can_act` wraps the new function and keeps its `False` for its other callers.
- **Q13, built:** a service caller (`svc:`, or a key of `DELEGATE_ON_BEHALF_OF`) is decided only by `artifact_reads.is_entitled`, with seeded_by = `submitted_by`, and is audited `seeding_delegate`. Every other service gets 403 `not_entitled` and never reaches the dropper or task clauses, so Topaz is not asked.
- **Seal:** `tests/test_ingest_review_gate_outage_and_services.py`, 12 arms. It stubs only boundaries: Topaz at httpx's transport, the task store, and the env delegate map.
  - Against the unfixed gate: 11 red on named assertions, 1 green (the no-task control). Fixed: 12 green.
  - The matched control: Topaz up gives yes → admitted, no → 403, and the same holder with Topaz down in three modes → 503.
- **Mutants:** each was red on gov's seal, on its own arm, and every red is an `AssertionError`. Lane 1's seal stayed green under all eight.

  | mutant | reds |
  | --- | --- |
  | M1: service branch removed | 5 |
  | M2: "the submitter" rule | 1 |
  | M3: outage except → 403 | 4 |
  | M3b: store outage → 403 | 2 |
  | M4: `can_act_or_unavailable` swallows | 2 |
  | M5: gate calls `check_can_act` | 2 |
  | M6: non-JSON body is not an outage | 2 |
  | M7: `hitl_unconfigured` handler removed | 2 |

- **Consequence files, all green:** Lane 1's `test_ingest_review_card_routes` (12), `test_approval_authority_gate` (12), `test_a_delegate_reads_what_it_seeded` (29), `test_ingest_routes_admit_a_declared_delegate` (9), `test_a_document_is_promoted_on_the_approval_plane` (73), `test_steward_correction` (60), `security/test_origin_visibility` (21), `test_the_suite_is_testing_THIS_tree` (7), `test_a_delegate_cannot_read_the_case` (7).
  - Exception: `test_a_delegate_acts_on_behalf_of_a_declared_principal` is 1 red, 18 green. The red is master's own.
- **Lane 1's file is touched:** `_gate`'s stub is retargeted from `check_can_act` to `can_act_or_unavailable`, because the gate no longer calls the former.
  - Their S3 arm ("each raise → 403") now splits by class.
- **Master red, Lane 1's:** `test_J_…names_R_089` flags `update_ingest_stage`. Since `039563a3` (lane/01-193), it calls `_delegate_principals` with no R-089. The census of all 11 functions the predicate flags on #73's tree found it the only miss. #73 added the R-089 line its own gate needed.
- **Packet placed:** `2026-10-17-packet-to-lane-01-q12-q13-ruled-and-built-pr-73-two-of-your-five-arms-change.md` (cc the architect).
- **Decided by gov, flagged below as Q14–Q16:** the unconfigured-URL deny, the stranger's 503, and the undeclared `svc:` submitter.

## 2026-10-20: origin on bob's two promoted rows, the matched pair, §5.1 instance 1 sealed (#77, `01d8605b`), Q14 built (#78, `3e9b25a9`)

From the architect, via Chris: "origin on bob's two promoted rows (TI, IDT) + matched pair. ADR-0047 §5.1 note with both instances." Q6, relayed in Lane 1's 10-20 packet: "The action-route read is an instance of §5.1 ... Note it in ADR-0047 as the first instance; the stage-enum read ruled for after the 23rd is the second. Gov seals both against §5.1's wording." Lane 1 wrote the note (lane/01-197 `b3fdad7f`, "INSTANCES OF THE SEEDING-DELEGATE READ"). Gov's part is the seals.

### The origin on both rows (live, read-only)

Origin fields are on the `IngestArtifact` row. The PROMOTION self-loop is on the same row.

| row | owner | resolved_by | evidence | program | promoted_by | promotion_ref | promoted_at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TI `sha256:65b3e80d…` | SUSTAINMENT | steward | `steward_attestation:dr-771aee2b12d8c98e` | NULL | `human:bob@example.com` | `dr-771aee2b12d8c98e` | 2026-10-18T04:56:22Z |
| IDT `sha256:65992cb6…` | SUSTAINMENT | steward | `steward_attestation:dr-e0e72d0a8dee0fcc` | NULL | `human:bob@example.com` | `dr-e0e72d0a8dee0fcc` | 2026-10-18T05:04:35Z |

- **`steward_confirmed` holds on both** in the 10-17 sense: `origin_resolved_by` is "steward", and `origin_evidence` has a `steward_attestation` entry whose id equals the promotion's ref.
- Each row's evidence and promotion name the same decision record.
- Both rows were submitted by alice. Both have program NULL, so the program conjunct does not apply (Q1).
- The notices derived from them:
  - `PCN-20210316000.1`: 9 parts, `dropped_by` alice, rung steward, promoted by bob;
  - `OV-19-05`: 17 parts, the same.

### The matched pair

**Run:** live, read-only, on 199 (`938d7639`) after the window closed at 03:08Z.
- `scratchpad/live/pair.py` ran in the cortex-bff pod against `iagent-engine-o:8084`, using each user's live Topaz cells.
- It was fired three times, and the outputs are byte-identical.
- The seeded controls (`IPCN25300X`, `PCN-23-002`) are two of the 11 SUSTAINMENT notices with no `provenance_ingest_id`, from a read-only Cypher count.
- The bodies were compared by sha256[:8], with the notice id masked.

| caller | domains | TI `PCN-20210316000.1` resolve hit (candidates) | IDT `OV-19-05` resolve hit (candidates) | seeded `IPCN25300X` / `PCN-23-002` |
| --- | --- | --- | --- | --- |
| alice (dropper) | all 12 | 1 (37) | 2 (2) | 1 / 1 |
| bob (promoter) | AVIATION, DOCS, MESH, SUSTAINMENT | 1 (35) | 2 (2) | 1 / 1 |
| erin | all 12 | 1 (35) | 2 (2) | 1 / 1 |
| **carol** | AVIATION, DOCS, MESH | **0 (34)** | **0 (0)** | 1 / 1 |
| **carol + SUSTAINMENT** (the one-thing control) | + SUSTAINMENT | **1 (35)** | **2 (2)** | 1 / 1 |
| `11111111-…` (a second outsider) | DOCS, MAINTENANCE, MESH | 0 (34) | 0 (0) | 1 / 1 |

- **The pair holds on both rows, at the route that reaches the rule.**
  - `/resolve_instance` has no SUSTAINMENT prefilter, so carol reaches `visible_by_origin` there.
  - Carol is withheld both rows. The same caller id with only SUSTAINMENT added sees both, with the candidate count bob gets.
  - The withheld row is removed, not marked: 34 candidates against 35.
- **The seeded control shows the rule doing it, not the domain.** Carol does see the two seeded SUSTAINMENT notices on the same route. So the route serves her SUSTAINMENT content, and what withholds TI and IDT is the origin rule (`can_consume` on owner SUSTAINMENT).
- **Inside the audience,** bob and erin see both rows through `by_origin`; neither dropped them. Alice sees them as the dropper.
- **`/notice_parts` refuses an outsider earlier.**
  - Carol and `11111111-…` get 200 `not_entitled` with one body (`3e76fbd6`) for a promoted row, a seeded row and an unknown id alike, before any graph read. So that layer gives no existence signal.
  - With SUSTAINMENT added, carol's body equals bob's: `a3de172a`, 9 parts; `1b9acc1c`, 17 parts.
  - Unknown, inside: `unknown_notice` (`33b56465`).
- **Not reachable live: "withheld answers exactly as unknown" at `/notice_parts`.**
  - Every live user who passes the SUSTAINMENT prefilter can consume a SUSTAINMENT, program-less origin. So no live caller reaches that route's withheld branch for these rows.
  - That equality stays sealed by `tests/security/test_origin_visibility.py` only. It was not measured here.

### §5.1 instance 1: `GET /cases/{case_id}/action`, sealed, with one defect fixed (#77 → lane/01-197)

- **The defect:** an undeclared `svc:` could read a case's action record.
  - The route sent every caller that is not a declared delegate to the person gate.
  - That gate admits the dropper, a holder of every label, and a task holder.
  - `/ingest/events` admits any caller as itself, so a service can be a case's dropper. This is derived from the code, not measured live.
  - §5.1: "Every other `svc:` recipient is still refused." Q16 ruled that shape the misuse at `/source`.
- **The fix:** any other service gets the delegate's 403 `not_your_case`, before any read. Persons and declared delegates are unchanged.
  - **It changes Lane 1's route on gov's reading. It needs the architect's OK, or a revert (Q17).**
- **The seal:** `tests/test_the_action_route_reads_as_adr_0047_5_1_words_it.py`, 9 arms.
  - W1, an undeclared service is never a recipient: three service-versus-person pairs (dropper, label holder, task holder).
  - W2, the case's `seeded_by` decides: a seeder pair, and a delegate that qualifies every person way, with the person gate a spy.
  - W3, every refusal is the absent-case body, with no store read: asserted inside each refusal arm.
  - Unfixed: 3 red (the W1 service arms), 6 green. Fixed: 9 green.
- **Mutants** (each was restored and cmp'd):

  | mutant | gov | Lane 1 |
  | --- | --- | --- |
  | M1: case level admits any declared delegate | 2 | 1 |
  | M2: fix removed | 3 | 0 |
  | M3: fix refuses persons | 3 | 7 |
  | M4: delegate falls to the person gate | 5 | 1 |
  | M5: record-level check dropped | 0 | 1 |
  | M6: refusal reads the store | 3 | 0 |
  | M7: refusal body differs | 3 | 0 |

  - Under M4, the W1 service arms are red only through the absent-case reference body, which becomes 404. Their own subject is not what reds them.
  - M5 is Lane 1's arm and is deliberately not duplicated.
  - Lane 1's arms red under M1 only through their store-read assertion.
- **Consequence files, one at a time, all green:**
  - Lane 1's action-record file (13);
  - `test_the_runner_writes_the_action_record_at_released` (19);
  - `test_cases_route` (11);
  - `test_a_delegate_acts_on_behalf_of_a_declared_principal` (19);
  - `test_ingest_review_gate_outage_and_services` (12).
- **Not run:** the full suite (Lane 1's), and live.
- **Instance 2, the stage-enum read, is not built.** No route or packet names it yet. Gov seals it once it lands, after the 23rd.

### The census, and PR #76 closed

- **`gateway.py` at master `166fafc0` has 11 reads of `_delegate_principals`:**
  - 4 disclosures:
    - `GET /artifacts/{id}`;
    - the artifact list in `/ingest/{id}/status`;
    - `_ingest_review_access` (`/source`, `/extraction`);
    - `get_case_action`.
  - 1 refusal: `get_case`.
  - 1 classifier: `_is_service_caller`.
  - 5 write admissions or stamps:
    - `_admit_on_behalf_of`;
    - `/ingest/events` `seeded_by`;
    - `update_ingest_stage`;
    - `/internal/cases/{id}/seeded-by`;
    - `/internal/cases/{id}/action-record`.
- **PR #76 is closed.** I wrote its ADR note before reading Q6 in `ia-gov/sessions/`. The note named two 10-17 instances and contradicted the ruling, so I closed it as superseded. Its open questions move here as Q18 and Q19.
- **Process note:** a packet to gov can be placed in ia-gov's own `sessions/`. I now read both trees' `sessions/` before acting.

### Q14 built: an unset Topaz URL is 503 `authorization_unconfigured` (#78 → lane/01-197, `3e9b25a9`)

- **What changed:**
  - `can_act_or_unavailable` raises the new `iagent.authz.AuthorizationUnconfigured` before any HTTP.
  - The review gate answers it 503 `authorization_unconfigured`, audited.
  - `check_can_act` still returns `False` for its other callers.
- **What is unchanged:**
  - With no open task, the answer is still 403 and Topaz is not consulted.
  - The dropper and the seeding delegate never meet the URL.
  - Q15 holds: a stranger gets the same 503.
- **The seal:** five arms (seven cases), added to gov's #73 file.
  - Unfixed: 5 red, 14 green. Fixed: 19 green.
  - All nine mutants red at least one named arm, on the assertion each should break.
  - Limit: no mutant isolates arm d's delegate case.
- **Consequence files, one at a time, all rc=0:** card routes 27, quarantine evidence 24, approval authority 12, the delegate reads 29.
- **Process note:** the implementer called the runner with the test file as its first argument. That argument is the log path, and the runner truncates it, so the file went to 0 bytes. The implementer restored it from HEAD and the diff is insertions only. The runner should refuse a `.py` log argument.

## 2026-10-21: the withholding arms vs Lane 1's class-chain read. Option 1: the arms were wrong (#82, `b0d9385b`)

The directive: "Lane 1's 739b0c74 (class-chain read) turns two arms in your withholding test red. Decide today: are the arms wrong given the chain read, or is the read wrong?"

- **The red arms.** In `tests/security/test_resolve_instance_withholds_what_notice_parts_withholds.py`:
  - `test_a_component_with_no_linked_notice_is_visible_and_neo4j_is_not_asked`;
  - `test_a_candidate_that_is_not_sustainment_content_is_untouched`.

  Both asserted `drv.sessions == 0`. Run alone at `lane/01-202` (`6a10a62a`): 2 failed, 14 passed, which is Lane 1's measurement reproduced.
- **The read, checked in `main.py`:**
  - `resolve_instance` runs `_attach_class_chains` on what `_filter_sustainment_candidates` returns, so it runs after the filter and only on the survivors' class URIs.
  - `_CLASS_CHAIN_CYPHER` matches `OntologyClass` nodes only.
  - `_read_class_chains` catches every exception. It is not a visibility read and cannot produce the 503.
- **Decision: the arms were wrong.** Their subject is "Neo4j is not asked about a notice". The session count stood in for that subject while the visibility read was Neo4j's only caller.
- **The edit, one file (PR #82 → `lane/01-202`).**
  - The double speaks Neo4j's kwargs. Before, it rejected `uris=`, so the arms ran the degraded path.
  - The double sorts each statement as a notice read, a class read, or unclassified.
  - The two arms assert `_asked_about_no_notice(drv)`.
  - The one-session arm counts `notice_sessions`. It was green only because its candidate is withheld.
  - New positive control: `test_the_double_tells_a_class_read_from_a_notice_read` sorts the real `_CLASS_CHAIN_CYPHER` and `NOTICE_PARTS_CYPHER`.
  - Census: no other tracked test counts `.sessions`.
- **After the edit:** 17 passed.
- **Mutants:**

  | mutant | what it does | result |
  | --- | --- | --- |
  | N1 | an unlinked component is looked up | red |
  | N2b | a non-sustainment IRI is asked about | red |
  | N3 | one session per notice | red |
  | N4 | the chain cypher also matches a `Notice` | red |
  | N5 | the chain read carries `notice_id` | red |
  | N2 (prefix flip only) | | equivalent |

  N2 is equivalent because `notice_id_of` returns `""` for a non-notice IRI. That is a second guard, not a hole. Scripts: `mut_wh.py` and `mut_wh_n2b.py` in the session scratchpad.
- **Not run:** any other file, or the full suite (Lane 1's).
- **Packets placed in master's `sessions/`:**
  - to Lane 1: `2026-10-21-packet-to-lane-01-option-1-the-arms-were-wrong-the-chain-read-stands-pr-82.md`;
  - to the architect, with Q18–Q20 at the top and then Q17: `2026-10-21-packet-to-architect-gov-q18-q20-open-q17-open-withholding-arms-decided-option-1.md`.

## Questions for a ruling

1. **ANSWERED: built at `38cebe0f`.** A program-less steward origin skips the program conjunct.
   - The ruling's "can_consume AND program_member" cannot hold literally for a steward origin, because the steward attests a domain, not a program.
   - Engine-o applies the program conjunct only when the origin names a program. That is what makes Friday's walk work: dave or alice, in SUSTAINMENT with no program, reads it.
   - But `gateway._origin_visible_to_caller` (`gateway.py:5240`) still returns False for any origin with no program, so the BFF's AnswerArtifact path and engine-o now disagree on the same origin.
   - Align the gateway to engine-o?
2. **ANSWERED, Q2 above: built.** **A steward-ACCEPTED origin on an awaiting_origin drop dead-ends.**
   - The row is terminal (ruled 2026-10-02), the accept writes a record origin, and nothing files a `document_promotion`.
   - Under your ruling, content is visible beyond the dropper only after promotion, so the drop stays dropper-only for ever.
   - The e2e arm 2 seals that as today's behaviour. Should an accept file a `document_promotion:<owner_domain>` task?
3. **ANSWERED, Q3 above: sealed; the token is Lane 1's.** **Engine-o identifies the caller by the body-asserted `user_email`.**
   - The specialist dispatch carries it next to `entitled_domains` (`dynamic_supervisor.py:3059`), at the same trust level, since specialists get no user token.
   - The dropper rule rests on it, and so does every visibility decision via `entitled_domains`.
   - Acceptable, or does this wait for the user token to reach specialists?
4. **ANSWERED, Q4: confirmed.** **The rung's name.** The write uses the SDK's existing `resolved_by="steward"`, and the ruling's `steward_attestation` rides in `origin_evidence`. No SDK change. Confirm.
5. **ANSWERED, Q5 above: built.** **The dropper exclusion refuses PROMOTED only; a dropper may still reject**, since rejection attests nothing. A task filed before this change has no `dropped_by` and excludes nobody. Confirm both.
6. **ANSWERED, Q6: refiled in the 187 roll.** **A promotion's audience must now be `document_promotion:<D>`.** Older test audiences (`aud:sustainment-approvers`) now 422 `promotion_audience_has_no_domain`. Does any live task carry an old-shape audience? If so, it cannot be promoted until it is refiled.
7. **ANSWERED, Q7 above: traced.** **The Jena verbs are untraced** (`resolve_instance`, `instances_by_property`, `declared_query`): I have not shown whether they can return drop-derived content. Only `/notice_parts` is gated by this PR.
8. **ANSWERED, Q8 above: traced; not changed, needs a ruling.** **The doc-tools `provenance_*` writer's caller is untraced.** The read check trusts the `provenance_ingest_id` on a notice. If any other writer sets it, or a seeded notice lacks it, the content is treated as seeded and is visible.
9. **ANSWERED (above): Lane 1, in the 187 roll.** The backfill has had no live run (no rolls). It needs `BACKFILL_ACTOR` plus the ledger DSN and Neo4j env. Who runs it, and when: before or after this PR's roll? Until it runs, promoted rows with no origin are withheld from everyone but the dropper.
10. **ANSWERED, Q10 above: built.** **Carried over:** cortex-ui's lane address, and the `for:` line parsing.
11. **OPEN (2026-10-15).** **Does a `svc:` group member count as a recipient?**
    - The kind-tree seal and `validate_policy` both count it today.
    - Elsewhere it's ruled that a service identity is never a person.
    - It is latent: `users.yaml` has 11 `svc:` ids, and none of them lists a group.
    - Not built. A ruling would apply to both predicates together.
12. **ANSWERED (2026-10-17): 503, the same as #54. Built at `d53d89ca` (#73).** The review gate's outage answer (F5 above).
    - A Topaz or task-store failure answers 403 `not_entitled` to a real holder.
    - Keep 403 (fail-closed, and indistinguishable from a refusal), or answer 503 the way #54's outage classes do?
13. **ANSWERED (2026-10-17): by the delegate rule, never as the submitter; a service's task counts for nothing. Built at `d53d89ca` (#73).** A `svc:` dropper on the review gate (F6 above).
    - A delegated drop records the service as `submitted_by`, so the service can read every source it delegated.
    - Does "a service identity is never a person" exclude `submitted_by` here, leaving `on_behalf_of` as the dropper?
14. **ANSWERED (2026-10-17): "unset Topaz URL is 503 authorization_unconfigured, not 403". Built at `3e9b25a9` (#78).** An unconfigured `TOPAZ_DIRECTORY_URL` was still a deny (403), not a 503.
    - Built that way, following `check_can_view_program`, where an unset URL is False.
    - Q12 says a holder "is never told not_entitled because a dependency is down". An unset URL is misconfiguration, not an outage, but a holder still hears `not_entitled`. Should it be 503 `hitl_unconfigured`, the way an unconfigured task store already is?
15. **ANSWERED (2026-10-17): "during an outage everyone gets 503". #73 kept as built.** A stranger also gets a 503 during an outage.
    - The gate cannot decide a stranger without Topaz, so it does not try to.
    - The cost is a small oracle: a 503 tells a stranger that this ingest has an open task with an audience. With no open task, or a resolved one, the answer is still 403, and Topaz is not asked.
    - Accept, or refuse strangers earlier? There is no cheap way to tell a stranger from a holder.
16. **ANSWERED (2026-10-17): "keep 403 — a service that drops as itself without delegation is the misuse." #73 kept as built.** A `svc:` caller that seeded a drop but is not a declared delegate gets 403.
    - This is gov's reading of "because the delegate rule already grants it": `is_entitled` grants only when the seeder is also in `DELEGATE_ON_BEHALF_OF`.
    - **It is reachable, not latent.** A `svc:` caller that sends no `on_behalf_of` takes `_admit_on_behalf_of`'s non-delegated path, `(caller, None)`, and drops as itself. Under #73 it then cannot read its own drop's source or extraction. Gov did not check whether `/ingest` refuses a service elsewhere.
    - Confirm the 403, or should a service's own non-delegated drop be readable by it? If so, under which rule? It is not the delegate rule.
17. **OPEN (2026-10-20). #77 changes Lane 1's action route on gov's reading. Is that OK, or should it be reverted?**
    - An undeclared `svc:` now gets 403 `not_your_case` before any read.
    - The basis is §5.1's "Every other `svc:` recipient is still refused" and the Q16 precedent. No ruling names this route.
    - If not OK'd: revert the four lines and keep the seal with its three W1 service arms xfailed.
18. **OPEN (2026-10-20, from closed #76). Is the `/ingest/{id}/source` and `/extraction` gate a third §5.1 instance?**
    - It meets Q6's test: the record derives from the event the delegate seeded.
    - It decides a service by `is_entitled` with `seeded_by` = `submitted_by`.
    - Q6 names two instances, and this is not one of them.
19. **OPEN (2026-10-20, from closed #76). Should that gate's existence signal stay?**
    - An absent id is 404 `ingest_not_found`. A present id that is not the caller's is 403 `not_entitled`.
    - §5.1 says a delegate "answers everyone else exactly as it answers an absent id". If the gate is an instance, the two answers differ where §5.1 says they must not.
    - The other two shapes: `/artifacts/{id}` answers `empty` for both, and `/cases/{id}/action` answers 403 `not_your_case` for both.
20. **OPEN (2026-10-20). `GET /cases/{id}`: an undeclared `svc:` reaches the person gate.**
    - It refuses declared delegates (403 `delegate_reads_artifacts_only`).
    - Any other service is decided as a person: dropper, labels, or task. It then reads the whole case.
    - It is not a §5.1 instance under Q6. Refuse it the way #77 does at `/action`?
