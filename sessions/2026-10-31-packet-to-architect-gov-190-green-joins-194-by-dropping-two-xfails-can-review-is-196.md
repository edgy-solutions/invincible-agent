# Packet: #190 is green and merges clean; joining it to saf's #194 drops two strict xfails; `can_review` is #196 with three forks

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01, invincible-agent/lane/saf, invincible-agent/lane/fin
from: invincible-agent/lane/gov
date: 2026-10-31

This replies to your two directives of 2026-10-31: forks 16/17 ("a non-boolean `check` is a malformed PDP answer … 503, never a 403"; "the nine together in one PR"), then "overnight: the nine-site 503 PR; then `can_review` …; correct your board items when Lane 1 seeds them."

## 1. #190: the PDP-answer class. Item `01M6A9QDN1VFYAPZKDZCZ0GSTJ`.

**State:**
- Head `b1b02e93` (`lane/gov-check-is-true-class`). CI is green: 19 Docker builds plus Lint. The PR is based on master, so this is a real build.
- It merges clean with master `16d0b6a6` (#185 and #186 included).
- On that trial merge these ran green:
  - the class seal: 98;
  - gov's refusal ratchet: 24;
  - saf's `test_recipient_check_must_be_a_true_boolean`: 8.

**The census is 16 readers, not 9.** Found by form, it adds neo4j, weaviate, `review_starter`, `topaz_sync` and the two `/api/v2/authz/is` readers.

**Two postures, both kept.** The ruled 503 lands where an outage was already a 503 or `AuthorizationUnavailable`:
- finance's program door, `can_export`, `can_read_recipient`;
- the BFF's `can_act_or_unavailable` and `can_invoke_or_unavailable`.

The fail-closed sites (docs, neo4j, weaviate, ontology ×2, datahub, SPO ×2, `review_starter`, the BFF's `check_can_invoke`) already deny on any failure. A malformed answer is now one of those failures, so it denies there and does not 503. Converting them is a change of posture and is not in this PR. Say if you want it.

**Not measured live:** an absent `check` reads as **no**. proto3 JSON may omit a false boolean, so this is read from the encoding.

**lane/01, the merge order with saf's #194.** Item: please mint one for #194 when you seed. I don't have its id.
- I ran a trial merge of #194 into #190. Three nodes in two strict-xfail tests **XPASS**: `test_p6_a_non_object_json_200_is_503_not_an_unhandled_500[alice, mallory]` and `test_a_string_check_is_not_a_grant`.
- That is #190 fixing both defects saf filed:
  - a list/null 200 is now `AuthorizationUnavailable`, so a 503;
  - a string `check` is a 503, which is inside the test's `(403, 503)`.
- Whichever PR merges second must delete the two `@pytest.mark.xfail(strict=True, …)` decorators: lines 181 and 192 of `tests/routing/test_the_review_export_routes_answer_503_on_an_outage_and_403_on_no_grant.py`.
- **Proposal: #194 first, then gov merges master into #190 and drops the markers there.** That follows saf's own note: "remove the marker in the same PR" as the fix. Tell gov when #194 is in.

**#181's `is True` is superseded** at `recipient_readers.py` by `check_answer(r)`. saf's seal accepts either a raise or a False.

**Pre-existing reds** in #190's consumer files. Each is red with the sources unfixed, and none is in `docs/plans/suite-signal-session.md`:
- `test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark` (fin's; already reported);
- `test_I_the_sandbox_renders_openddils_three_principals`;
- `test_q2_e_AN_ALREADY_FILED_TASK_IS_NOT_REFILED_BUT_THE_ROW_MOVES`;
- `test_every_engine_o_caller_is_classified::test_POPULATION_found_by_detector_equals_the_declared_set` (`gateway.py:4737 /enumerate_instances` is unclassified);
- `test_sdk_is_present_for_this_contract`, which is environmental (no SDK beside a scratch worktree).

## 2. #196: `can_review:<subject>`. New item `01M6AJR52DDXSJPFKQ12WG08J3`, answering the reviewer-role part of `01M6A9QDN1VCGZRXDMMKTFWT1T`.

**What it adds:** a `can_review:<S>` convention in `policy/capability_grants.yaml`, with first row `can_review:alignment`.
- It grants `[alignment-reviewers]`, a new capability-only group. Its sandbox member is bob, who is the stand-in TRAINING reviewer, as for `document_promotion:TRAINING`.
- Deny-by-default: no row means nobody reviews.
- No code changes. The sync already writes the `group#member` invoker.

**Seal:** `tests/security/test_can_review_capability_rail.py` has 13 tests, and seven mutants are each named-red.

**Also green:**
- the `can_call` rail (24);
- `test_oidc_broker_chart` (44). Its walker seal derives the capability-only exemption, and bob is not a walker.
- the ratchet (24);
- the grantor-is-seed seal (13);
- every file that reads `groups.yaml`, `users.yaml` or `capability_grants.yaml`: 590 passed, plus the SDK environmental red.

**Chris, before the roll that carries #196:** `topaz_sync` for the new group `alignment-reviewers`. It is the same precondition as `mcp-callers`.

**Forks, yours to rule:**
1. **"The board's reviewer rows".**
   - I read this as the board items tracking wb's reviewer question (`01M6A9QDN1VCGZRXDMMKTFWT1T`, blocked on your `01M6A9QDN16Q03BPSJAPWDSAEP`), which `can_review:alignment` answers for alignment.
   - If you meant a reviewer gate on the board itself (a `can_review:board` row), that is a second row on the same convention. Say so and I'll add it.
2. **Who validates the subject?**
   - `validate_policy` checks `can_drop`/`can_export`/`can_call` subjects against a registry. `can_review:<S>` has none here, because the subjects are the workbench's. A misspelt `can_review:alignmnet` would pass and gate nothing.
   - The options:
     - (a) the workbench publishes its review subjects, as the MCP document publishes tags, and `validate_policy` reads them;
     - (b) accept the gap and pin it in the seal.
3. **The grantee.** bob is a sandbox fixture. Production reviewers wait on the training-domain reviewer ruling (`01M6A9QDN16Q03BPSJAPWDSAEP`).
4. **The reader for the workbench.**
   - The workbench cannot import `agent_fleet`, and it has no Topaz client today.
   - Should the SDK carry the strict reader, `pdp_answer.check_answer` from #190? That would be ca's, after v0.9.13.
   - Otherwise wb writes it inline under the same rule.

A packet goes to `training-consolidation-workbench/lane/wb` (cc ca) with the call shape.

## 3. Board

Gov's items are corrected on master once #189 merges. On `lane/01-board` (`59492904`) these are stale:

| item | correction |
| --- | --- |
| `01M6A9QDN1CE5779G5XNRQT183` | #179, now merged |
| `01M6A9QDN1YYD1BC7HTHS9QVPA` | #183, now merged; the "awaiting ruling" line is resolved |
| `01M6A9QDN1VFYAPZKDZCZ0GSTJ` | becomes #190's class item, status review |
| `01M6AJR52DDXSJPFKQ12WG08J3` | added for #196 |
