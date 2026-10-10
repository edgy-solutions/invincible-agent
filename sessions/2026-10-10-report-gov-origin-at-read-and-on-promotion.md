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

## Questions for a ruling

1. **A program-less steward origin skips the program conjunct.**
   - The ruling's "can_consume AND program_member" cannot hold literally for a steward origin, because the steward attests a domain, not a program.
   - Engine-o applies the program conjunct only when the origin names a program. That is what makes Friday's walk work: dave or alice, in SUSTAINMENT with no program, reads it.
   - But `gateway._origin_visible_to_caller` (`gateway.py:5240`) still returns False for any origin with no program, so the BFF's AnswerArtifact path and engine-o now disagree on the same origin.
   - Align the gateway to engine-o?
2. **A steward-ACCEPTED origin on an awaiting_origin drop dead-ends.**
   - The row is terminal (ruled 2026-10-02), the accept writes a record origin, and nothing files a `document_promotion`.
   - Under your ruling, content is visible beyond the dropper only after promotion, so the drop stays dropper-only for ever.
   - The e2e arm 2 seals that as today's behaviour. Should an accept file a `document_promotion:<owner_domain>` task?
3. **Engine-o identifies the caller by the body-asserted `user_email`.**
   - The specialist dispatch carries it next to `entitled_domains` (`dynamic_supervisor.py:3059`), at the same trust level, since specialists get no user token.
   - The dropper rule rests on it, and so does every visibility decision via `entitled_domains`.
   - Acceptable, or does this wait for the user token to reach specialists?
4. **The rung's name.** The write uses the SDK's existing `resolved_by="steward"`, and the ruling's `steward_attestation` rides in `origin_evidence`. No SDK change. Confirm.
5. **The dropper exclusion refuses PROMOTED only; a dropper may still reject**, since rejection attests nothing. A task filed before this change has no `dropped_by` and excludes nobody. Confirm both.
6. **A promotion's audience must now be `document_promotion:<D>`.** Older test audiences (`aud:sustainment-approvers`) now 422 `promotion_audience_has_no_domain`. Does any live task carry an old-shape audience? If so, it cannot be promoted until it is refiled.
7. **The Jena verbs are untraced** (`resolve_instance`, `instances_by_property`, `declared_query`): I have not shown whether they can return drop-derived content. Only `/notice_parts` is gated by this PR.
8. **The doc-tools `provenance_*` writer's caller is untraced.** The read check trusts the `provenance_ingest_id` on a notice. If any other writer sets it, or a seeded notice lacks it, the content is treated as seeded and is visible.
9. **The backfill has had no live run** (no rolls). It needs `BACKFILL_ACTOR` plus the ledger DSN and Neo4j env. Who runs it, and when: before or after this PR's roll? Until it runs, promoted rows with no origin are withheld from everyone but the dropper.
10. **Carried over:** cortex-ui's lane address, and the `for:` line parsing.
