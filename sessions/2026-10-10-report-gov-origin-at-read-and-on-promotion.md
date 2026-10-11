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
- **Q7, the Jena verbs.** TRACED; gate in a follow-up PR.
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
- **Q8, `provenance_ingest_id`.** TRACED; NOT CHANGED, because the ruling as worded would hide all seeded content today.
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
