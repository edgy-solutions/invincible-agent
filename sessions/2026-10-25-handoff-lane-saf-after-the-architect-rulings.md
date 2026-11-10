---
to: invincible-agent/lane/saf
from: invincible-agent/lane/saf
date: 2026-10-25
---
# Handoff

State: #94 and #95 pushed, #81 merged into 202. Lane 1 owns builds a1, a2, a3, a4 (packet 2026-10-25-packet-to-lane-01-three-builds-...).

FORCE-PUSHES (authorised by the architect via the coordinator, trailer only, tree equal):
- lane/saf-seal-frs-knowledge-document (#94): 65026824 -> e957b198; tree bbe50cb9 before and after. Why: the trailer named a throwaway worktree (`saf-frs`); now `Lane: ia-saf/<branch>`.
- lane/saf-steward-values-meet-engine-s (#95): 3f1a74b9 -> 5ba756ca; tree 376fefab before and after. Same reason. Later pushes on #95 are ordinary.

PENDING:
- Seal wb's per-caller retrieval check (realm-authenticated for platform reads, owner-or-reviewer for drafts) and b5 (aud/iss validation) WHEN wb's PR lands. Not written yet, by order.
- Rules rolling: commit only from ia-saf; throwaway worktrees go under the scratchpad (saf-*), `-c core.longpaths=true`.
- `test_THE_TRAILER_MATCHES_THE_WORKTREE_IT_WAS_MADE_IN` is red on every branch from master, on commit 72f66e25 (`Lane: ia193/...`, not mine; ia193 is not a registered worktree). Not saf's to fix.

## Architect rulings, second round (10-25)
- a1 rule is doc-tools notice_identity.normalize_component (:138, keeps dashes), NOT `_mpn_key`; a1 arms re-pointed and the typed variants re-derived by calling it. Lane 1 vendors it; doc-tools is not made importable here.
- a4: "safety-critical" = graph property `safety_critical` (only the safety pass sets it); the two lists become a seed migration then are deleted. The first approval is RECORDED as `pending_second_approval` (7-day expiry), not held. Arms rewritten on #95.
- Open: who builds the migration and deletes the lists (saf or Lane 1).
- 72f66e25 `ia193` trailer: Lane 1 fixes via policy/lanes.yaml. #94 merged at 65026824 (old trailer); my e957b198 is orphaned; Lane 1 swaps it. I keep committing as `ia-saf/<branch>`.
- #81 task_id and the register 422 test wait for Lane 1's 208 packet.
- Scratch purge: 36 saf_* files older than 7 days deleted from the scratchpad.

## Rulings round 3 (relayed 10-27; #95 merged c415038f, #106 lanes registry on master)
- Q1: saf builds the seed migration and deletes both lists. STOPPED before deleting: the census found CRITICAL_ITEMS is also Engine S's CSI entity set (see hand-back partition); decision with the architect.
- Q2: pending lives on the task, in the ledger, not a graph node. Q3: after 7 days the next action is a fresh first approval. Arms tightened on lane/saf-safety-critical-from-the-graph.
- Q4: Lane 1 owns the two suite reds (delegate-principals test; inbox-addressed test). Leave them.
- Note: the notice graph label in promotion is `Component:{domain}` keyed on `mpn` (promotion_stores.py:274-302), not `Part`; the migration target label is a question for the architect.

## Round 4 (2026-10-27)
- PR #114 (test PR, `lane/saf-safety-critical-from-the-graph`, 3c541876) open against master, tests only.
- Architect ruled P1. Migration PR #115 (`lane/saf-safety-critical-seed`, e9ef6d46): SAFETY_ITEMS rename, CRITICAL_PART_NUMBERS deleted, `setup/safety_critical_seed.py` MATCH/SET folded into `prime_neo4j`, offline tests, a4(c) arm flipped.
- mpn form: both writers store the cell verbatim, unnormalised; records are canonical `PN-88xx`. Equal only if the cell spelling matches; a miss is logged as 0 nodes.
- Open: measures.py:248 still reads records (no graph read path); prime-time vs later Components; label span; unmatched policy.
- #114 and #115 both edit the a4 test file; second to land rebases.

## Round 5 (2026-10-28)
- #114 and #115 MERGED (in order). Follow-up PR #125 (`lane/saf-safety-critical-rule`, 8997289b): the rule `agent_fleet/safety_agent/safety_critical.py`, domain-scoped seed (`Component:SUSTAINMENT` label), unmatched stored on the `:PrimeRun` row, tests, strict-xfail census arm.
- Packet to lane/01 (cc architect) placed untracked in the master tree sessions/: promotion SETs safety_critical by the rule; census prints `safety_seed_unmatched: N`.
- QUEUE (build nothing yet): Engine S per-request check moves to the graph via SDK `is_safety_critical(mpn, domain)` served by the gateway (ADR-0060; ca owns the type, Lane 1 the route, saf the switch at measures.py:248). SAFETY_ITEMS is the interim.
- Open: rule's DOMAIN is a literal sealed equal to main.py DOMAINS by AST (main.py cannot import it without breaking the engine-scope seal's resolver).

## Round 6 (2026-10-28) -- architect rulings on #125 (do not push to its branch)
1. A checked duplicate of DOMAIN is acceptable; the AST equality test is the seal.
2. Promotion writes safety_critical=true when the rule says so, never false; clearing is human, under the second-approver rule.
3. Spelling: the rule compares both sides via normalize_component (as a1); use Lane 1's vendored copy when it lands, in a follow-up PR.
QUEUE: (a) when the vendored normalize_component is on master: follow-up PR, safety_critical() and the seed compare normalize_component(mpn) both sides (import the vendored copy; never doc-tools by path); tests: pn-8801 marked, "PN 8801" unmatched and listed. (b) BUILT as its own PR off master (never-cleared seal). (c) Engine S per-request check -> SDK is_safety_critical(mpn, domain) (ADR-0060), build nothing yet.

## Round 7 (2026-10-28): ADR-0063 safety part hand-back

Order: ADR-0063 "field kinds from OpenDDIL", design only, status PROPOSED. My part: §2 safety and §5 first slice. Nothing under docs/adr touched, nothing committed or pushed.

Packet (untracked, master tree): C:\Users\cnogr\git\invincible-agent\sessions\2026-10-28-packet-to-lane-01-adr-0063-safety-section-2-and-first-slice-section-5.md (to lane/01; cc seat/architect, doc-tools/lane/7f). It has a correction note appended after reading the four files first left unread; no result flipped.

Premise results: P1 FAIL (finding is a new source for the rule); P2 FAIL (no existing task kind fits; hazard_link_review is link verbs, safety_acceptance_direct is authored-not-triggered); P3 FAIL (no interval source; OpenDDIL sends service_due_unreleased, a different predicate); P4 PASS (1010 = OpenDDIL lab asset id); P5 PARTIAL (no on_behalf_of in Engine S, service identity refused on per-person verbs; ledger field for the episode key not located); P6 FAIL (OBTAINED_VIA is a closed degradation ladder; observed/declared/derived is another axis); P7 PASS (C:\Users\cnogr\git\openddil, not a git repo).

§5 sizing: 5.0 days = kind registration 0.5, landing 1.0, task 1.5, card/state 1.0, tests 1.0. Excludes: the OpenDDIL sender (none exists; demo hand-posts), the interval source, anything that sets safety_critical. Likeliest overrun: authoring the seeded workflow (safety_acceptance_direct is untriggered).

Open questions (numbered as in the packet): 1 finding as a new source for the rule (true only)? 2 rename slice finding to service_due_unreleased, or OpenDDIL adds an interval? 3 audience of a service-origin task (softened: audience is a role:domain string; open is whether register_task takes a service requester). 4 where the episode key lives on the ledger entry (Lane 1). 5 provenance class as a separate per-entry field beside obtained_via, never folded in (§4). 6 owner of the asset_id -> mpn -> WorkOrder join.

Queue unchanged: (a) vendored normalize_component follow-up (waits on Lane 1); (c) Engine S switch to SDK is_safety_critical (blocked on ca/Lane 1).

## Round 8 (2026-10-28): ADR-0063 rulings applied, PR #142

Rulings: 1 new workflow `safety_finding_review` (one step; confirmed / dismissed+reason / new_hazard; audience safety_finding_review:SUSTAINMENT); 2 `safety_finding` is a registry seed row (7f), not overlay; 3 register_task must accept a service with on_behalf_of (Lane 1 confirms + test).
Done: branch lane/saf-adr-0063-safety-and-slice from 2e55605c (tip had not moved); one commit acebcf2b editing only docs/adr/ADR-0063-field-kinds-from-openddil.md; PR #142 stacked on #141 (no CI gate; Lane 1 merges into #141). Slice 7.5 days = +2.5 over 5.0. Open questions 5-10 are mine with recommendations; Q3 recorded resolved; Q4, Q6 owner Lane 1. The 10-28 packet carries a superseded-by line.
Waiting: architect rules on #141/#142; Lane 1 merges #142. Queue (a), (c) unchanged.

## Round 9 (2026-10-29): architect rulings on #142 recorded

Ruled: confirmed / dismissed(reason) / new_hazard approved; Q5 agreed; Q6 yes service_due_unreleased; Q9 yes source_class beside obtained_via; Q8/Q10 Lane 1's, answered in #141; 7.5 days accepted.
Done: forward commit 84918b52 on lane/saf-adr-0063-safety-and-slice (on acebcf2b, no force), ADR file only: Open questions 5-10 marked, section 5 carries service_due_unreleased with no interval and notes 7.5 accepted, section 2 names source_class and the approved outcomes. Section 4 untouched. Pushed.
Waiting: Lane 1 merges #142 into #141. Queue (a), (c) unchanged.
Round 9 addendum: #141 moved to 3b63239c (review_shape withdrawn). Forward commit dropped the review_shape half of the section 5 prerequisite; source_class kept as ca-SDK-first per section 4 Owners. merge-tree against the new #141 tip checked on push.

## Round 10 (2026-10-29): review of Lane 1's #153 and #154 against the architect's four seals

Order: while blocked, review the merged can_drop door (#153) and review export (#154); seals: Topaz error 503 not open; batch export filtered by cells; no profile outside the catalogue; steward edits and the obtained_via rung survive every profile.
Done: seal PR #158 (lane/saf-seal-can-drop-and-review-export, 34e68e86), two new test files, tests only. Seal 1 held (unconfigured mapping and /leaf site were untested, now sealed); seal 2 held but untested against the real promoted_between (sealed); seal 3 held; seal 4 GAP: corrections are refused (409/422), never served, so edits and the rung do not come out; two strict xfails. One latent xfail (None in the wanted set). Every guard mutated with a named red and restored. Comments on #153 and #154; untracked packet to lane/01 cc architect in the master tree sessions/ (2026-10-29-packet-to-lane-01-review-of-153-and-154-...).
Waiting: Lane 1 merges #158; the architect decides whether the export should apply corrections. Queue (a), (c) unchanged.

## Round 11 (2026-10-29) -- safety_finding_review workflow spec

- PR #160, base `lane/01-adr-0063-field-kinds-from-openddil` (#141 at 9f6444df, unmoved), head
  `lane/saf-safety-finding-review-workflow` at aebf4734. Stacked: no CI gate; Lane 1 merges into #141.
- Files: policy/workflows/safety_finding_review.yaml, policy/overlays/sample/task_kinds/safety_finding_review.yaml,
  policy/task_grants.yaml (row `safety_finding_review:SUSTAINMENT` -> group `safety-engineers`),
  tests/safety/test_the_safety_finding_review_is_declared.py (5 pass; mutant dropping `dismissed`
  from reason_required -> test_dismissed_requires_a_reason red, restored).
- No steward group exists; used `safety-engineers` (has members). No group/user added.
- Missing prerequisite: nothing receives `new_hazard` and opens a hazard.
- Red at base identically, unrelated: test_overlay_verb_invokers_are_derived (1), test_every_policy_refusal_names_policy_binding_grantor (8).
- New grant row: merge, topaz_sync, then roll once on master.

## Round 12 (2026-10-30) -- architect rulings on #160 recorded

- Forward commit 31d5639c on `lane/saf-safety-finding-review-workflow` (on aebf4734), ADR-0063 only:
  s2 new_hazard reason-required + audience granted to `safety-engineers`; s5 prerequisite that
  new_hazard opens a hazard via the hazard_link_review path, inside 7.5 days.
- Finding: that path is declaration only. Nothing raises hazard_link_review or acts on new_hazard;
  human_tasks.py just stores the verb; classifyWriteUp has no code. saf builds "on new_hazard, create the hazard".
- Seal file 5 passed (exit 0). PR comment posted. Lane 1 merges #160 into #141.

## Round 13 (2026-10-30) -- new_hazard sized, slice total 9.0

- Forward commit f1c5b0d8 on #160's branch, ADR-0063 only. (b) raise the task 1.5 days (chaining table
  + one hazard_link_review definition + census/driven tests); (a) Hazard node ~5 days (> 2): deferred
  follow-on. Total 7.5 -> 9.0. Cross-lane: Lane 1 on_behalf_of in register_task (not counted).
- No other 7.5 in Lane 1's text. Seal 5 passed (exit 0). PR comment posted.

## Round 14 (2026-10-30) - audit against the architect's standing rule

Read-only audit done. Report: sessions/2026-10-30-report-saf-audit-against-the-standing-rule.md; packet to architect (cc lane/01) alongside it, both untracked.
Counts: (i) 4, (ii) 5, (iii) 4, (iv) 11. (i): I1 reason_required copy 0.5d; I2 kind template 0.5d; I3 case/task id mirror 1.0d; I4 in-code fixtures as data source 5.0d (shared with Hazard-node follow-on).
Nothing fixed, no commits. Next step: await the architect's rulings on U1-U11 and the 10-28 DOMAIN question.
Rule applies to all new work from here: config names the case, code is the mechanism.

## Round 15 (2026-10-30) - architect ruling on the new_hazard sizing

Architect, verbatim: "to: invincible-agent/lane/saf - 9.0 accepted; (a) is the follow-on as written. #141 to Proposed once Lane 1 merges #160."
Nothing to build or commit. #160 is OPEN at f1c5b0d8; #141 is a draft at 9f6444df. Lane 1 merges #160, then moves #141 to Proposed.
U9 (#160's seal hard-codes the overlay path) is left alone until the architect rules on the audit packet.

## Round 16 (2026-10-30) - architect ruling on the audit; Job 1 (U9, U11) pushed

Architect, verbatim: "fix the three measures.py items (2 days) as 0.4.73 work; entities.py in-code lists are the ADR-0063 follow-on, not now. U1/U2: an engine's own domain and persona are its identity, set at build; 10-28 stands. U9: fix now before #160 merges. U11: yes, first rule row. No other prior roll ruling is overturned. Merge the three memory copies into one." (memory merge is the coordinator's.)
Job 1 done: 1da651b1 on lane/saf-safety-finding-review-workflow (forward commit, pushed, PR 160 comment 6525818383). Seal drives human_tasks._declared_kinds() over the chart's TASK_KIND_OVERLAY_DIRS. Two mutants red by name, restored with cmp. ADR s5: predicate is the first row of the safety_finding selection table; 9.0 unchanged.
Pre-existing reds at f1c5b0d8 (not mine): test_a_delegate_acts_on_behalf_of_a_declared_principal (principals), test_adr_index_complete (ADR-0063 has no index row).
Next: Job 2 (round 17) on a new branch lane/saf-measures-reads-the-served-declarations off origin/master: I1 reason_required, I2 kind name, I3 case/task id (STOP and packet Lane 1 if it needs their code). Not started. Check first that Engine S's image can reach served policy.

## Round 17 (2026-10-30): Job 2, measures reads the served declarations

Branch lane/saf-measures-reads-the-served-declarations, PR #166 against master, tip 5133b398. 0.4.73 work, no chart bump.
- Image reachability: src/iagent is not in the flattened engine image, so the new agent_fleet/safety_agent/served_kinds.py imports only the SDK compose() and reads TASK_KIND_OVERLAY_DIRS (chart ConfigMap, envFrom) over the baked policy/overlays/. Seed dir not baked, not added. Image not widened.
- I1 done: card reason_required from the composed row. I2 done: kind is the head of the matrix acceptanceAudience. Unreadable declaration refuses naming the variable (form not counted by gov's ratchet).
- I3 STOPPED: the case-key/task-id mirror needs Lane 1's code. Strict xfail tests/safety/test_the_card_does_not_mint_its_own_case_key.py; packet in MASTER tree sessions/2026-10-30-packet-to-lane-01-the-card-mints-its-own-case-key.md (untracked, cc architect).
- Final-tip exits: tests/safety 0 (515 passed, 4 skipped, 12 xfailed); refusal ratchet 0 (24); gating manifest 0 (22). Mutants M1 (I1) and M2 (I2) each exit 1 by name, restored with cmp.
- Pre-existing, not mine: principals delegate test and test_adr_index_complete (ADR-0063 index row).
- Next: read PR #166 CI; Lane 1 merges #160 and #166.

## Round 18 (2026-10-30): Job 3, MCP seals and the post-merge review of #169/#170

#169 merged as 717f3a07 (head 85257cde), #170 as 72edfa96 (head 20c64ac2); both is-ancestor of origin/master e2c03799. Review comments posted on each.
Branch lane/saf-mcp-seals, `tests/mcp_seals/` (4 seal files + a derive helper; routes derived from gateway.app, none typed except the subject /orchestrate in seal 4).
- Seal 1 (no tool without a user token): no-token and bad-signature green on all 13; service-only token strict XFAIL (the door admits `svc:` on all 13). Packet 2026-10-30-packet-to-lane-01-the-mcp-door-admits-a-service-token.md (MASTER tree, untracked).
- Seal 2 (no untagged route): green; registry, schema, generator and committed doc agree.
- Seal 3 (refusal passes through): 403/409/422 with body green on finance_measure; two strict XFAILs: empty-body 422/200 -> 500 (finance, cdrl), and `_engine_failure` rewrapping 409/422 -> 502 (cdrl). Packet 2026-10-30-packet-to-lane-01-relay-envelope-defects-finance-empty-body-and-cdrl-rewrap.md.
- Seal 4 (audit line names the user): green; `on_behalf_of` is ABSENT on /orchestrate on master (pinned).
- Mutants (gateway.py/generator edited, restored with cmp, no tracked diff): M1 /cases door removed -> seal 1 exit 1; M2 generator filter admits all -> seal 2 exit 1; M3 finance relay status -> 502 -> seal 3 exit 1; M4 audit who=current_user.id -> seal 4 exit 1.
- Pre-existing reds on clean master (not mine): finance test_both_export_routes_shape_through_the_ONE_helper; security engine_o_caller_is_classified + two q8 flips; routing test_a_pick_gets_a_row merge + test_s3_the_catalogue_is_the_reviewed_list. test_every_archetype_cortex_can_draw reads the sibling cortex-ui checkout (red here on MODEL_EXPLANATION, skipped in a scratch worktree).
- Env: `uv sync --extra agent-fleet` was needed in ia-saf (SDK 0.9.10 -> 0.9.12, master imports review_coverage).

## Round 19 (2026-10-31): the architect rules on #175

Ruling: "seal 3 reading accepted: same status, every key kept, advice keys may be added. #175 merges when green; seal 1 is Lane 1's P1." Seal 3 already asserts it (status equal; engine keys a subset of the relayed keys). No code change. Comment posted on #175; CI green (20 success, 3 skipped); it merges at 2a8adb9b. Relay packet annotated with the ruling (untracked).
Seal 1 (the service-token door) is Lane 1's P1: its strict xfail flips when they fix it, and Lane 1 deletes the marker in their fix PR. Nothing further for lane/saf unless a seal goes red after the merge.

## Round 20 (2026-10-31): Job 4, seal review of #181 and #182

Comments: #181 https://github.com/edgy-solutions/invincible-agent/pull/181#issuecomment-6549177480 ,
#182 https://github.com/edgy-solutions/invincible-agent/pull/182#issuecomment-6549253525 (merged 258c89ad
before I finished). Throwaway worktrees only; nothing committed to either branch. Seal files live in the
comments (details blocks). Packets (untracked, master tree sessions/): to lane/fin and to lane/01, cc architect.

- #181a holds at 6 doors x 8 real httpx failure forms (48/48); the PR's double only raises ConnectionError; the
  fin template door has no route-level test (mutant outage->[] leaves the PR green).
- #181b pickers omit (8/8); omission is byte-identical to "no readers" (P4 red) and all-or-nothing per owner.
- Adjacent: can_read_recipient admits {"check":"false"} (P5, 3 of 7). Not in #181's diff.
- #182a holds on a 9,408-ref corpus derived from the SDK; PR tests leave two mutants green (y1-only bound, null note).
- #182b DEFECT: steward_correction.normalize_evidence_ref (runner) accepts pixels; P2 5 failed on d141a81d; inverse fix green.
- Standing rule clean on both; one stale docstring on #182.
- Mutants all restored with cmp; the worktrees are r181/r182 under the scratchpad.
- Round 20 addendum: packet to lane/gov (cc architect) for the can_read_recipient truthy-string check fail-open, master tree sessions/2026-10-31-packet-to-gov-can-read-recipient-admits-a-truthy-string-check.md; one-line pointer comment on #181.

## Round 21 (2026-10-31): architect rulings on Job 4
- #181: outage = 503, no readers = 403 (ruled). Head still 2a3385f0; picker/offer answer 200 [] on both, a ruled defect in the diff. Seal P6: 18 failed, exit 1; 6 doors still 48/48; illustrative mutant 18 passed. Appended to the fin packet; comment posted on #181.
- #182: null `note` refused at the BFF is right; SDK/runner align in ca's v0.9.13. Comment on #182; one line added to the lane/01 pixels packet.
- Nothing committed or pushed. Review worktree r181b in the scratchpad (can be removed).

## Round 22 (Job 5)
- #187 audit test restated; stacked PR #192 (7b423929) base lane branch of #187; comment posted on #187.
- Review export P6 seal: PR #194 (48e81153) on lane/saf-review-export-outage-seal; list/null 200 = 500 and string check admits held as strict xfail; packet to lane/01 cc architect: sessions/2026-10-31-packet-to-lane-01-cc-architect-a-json-list-or-null-200-from-topaz-is-a-500-on-the-export-rails.md (untracked, master tree).
- #187 finding: s2 batch-403 test passes on master, fails on #187 (door replaces not_entitled_to_export_batch); /interview/stream alias has no door (unmeasured).

## Round 23 (Job 6)
- Catalogue seal list: item_kind + review_shape added (ruling 2026-11-02), mutant red, PR above on lane/saf-catalogue-rules-item-kind-and-review-shape. routing suite red only on test_a_pick_gets_a_row merge-order (also red on master).
- Removed scratch worktrees w187 and wm (clean, shas on remote; wm remote has a master merge on top of 48e81153). wc worktree remains until the PR lands.

## Round 24 (Job 7: identity seals ahead of #213)

- PR #218, `lane/saf-identity-seals`, sha 548718691b8f, test-only, base master 121272dc. Three seals in `tests/identity/` plus `_identity_support.py`.
- Matrix (master / #213 4eb35d06): seal 1 16 pass + 1 strict xfail / same; seal 2 5 pass / 5 pass; seal 3 5 pass + 4 strict xfail / same. Mutants all exit 1, restored with cmp.
- Defect for Lane 1 (xfail in seal 1): action-record records any on_behalf_of as owner for the case runner. Seal 3 is ruled-not-built (no `pipeline:` principal anywhere). Packet: master-tree `sessions/2026-11-03-packet-to-lane-01-cc-architect-identity-seals-one-defect-on-action-record-and-the-pipeline-principal-unbuilt.md` (untracked).
- Engine S: no safety seal red on #213; only red is the Engine O classification test, also red on master. The two FRACAS verbs change from 422 no_person to filtered answers.
- Comment on #213: issuecomment-6595499639.
- Next: when Lane 1 rules/fixes action-record or builds the pipeline principal, delete the strict xfail markers (they XPASS-fail by design).
- Test-run quirk: pytest collection dies with FileNotFoundError on a `socratic-*` dir in the real Temp (another process); retry, use `--basetemp`.

## Round 25 (Job 8)
- PR #236, branch lane/saf-case-runner-routes-are-bound-by-the-delegate-list, sha eb21c33c: seal 1 extended to every case-runner person-naming route. 3 strict xfails (action-record on_behalf_of, summary seeded_by, origin/write approver_sub); 2 plain passes (action-record seeded_by, seeded-by). Census derived from handler source; undecided fails.
- Mutant (check at summary seeded_by): XPASS(strict), exit 1; restored, cmp clean.
- Final tip exits: tests/identity 0; refusal ratchet (tests/security/test_every_policy_refusal_names_policy_binding_grantor.py) 0; gating manifest 0.
- Open for architect: confirm exclusions of register requested_by and origin/write dropped_by. Packet to Lane 1 appended (untracked).

## Round 26 (Job 9)
- PR #239, branch lane/saf-register-takes-the-requester-from-the-token, sha 9dffaf8b, cut from #236 head eb21c33c, base master. #236 untouched, merges first.
- Register requested_by ruled IN: 2 strict xfails (fix a caller gate, fix b token-not-body). Control passes. Old pinning test replaced. dropped_by exclusion marked agreed.
- Mutants: (a) alone flips only leg a (exit 1); (b) alone flips only leg b (exit 1); cmp clean.
- Final tip exits: tests/identity 0, refusal ratchet 0, gating manifest 0.
- Finding: origin/write route->writer membership-flag wiring unasserted by any test; writer-side and 503 are sealed. Not written; reported.
- Packet to Lane 1 amended (untracked); corrected the earlier "case-runner-only" claim.

## Round 27 (Job 10)
- Branch lane/saf-origin-write-refuses-a-non-member-dropper, new file tests/identity/test_origin_write_refuses_a_dropper_who_is_not_a_program_member.py. Real route + real write_origin; stubs only the PDP and graph writer. Legs 1-3 pass; leg 4 null/empty pass; missing program key = 500 KeyError, strict xfail.
- Mutants: M1 (member=True hard-coded) reds leg1 + leg4 null/empty, exit 1; M2 (wrong subject) reds leg3, exit 1; cmp clean.
- Exits: new file, test_origin_writer, test_origin_write_route, tests/identity, refusal ratchet all 0.
- Packet amended: five markers (3 from #236 + 2 from #239) plus the new missing-program one.

## Round 28 - document grants in the gate's form

PR #264 (a4a00e38, lane/saf-document-grants-in-the-form-the-gate-matches). Engine W and E send the chunk's source_url/uri/doc_id verbatim; no expansion anywhere. Two mil#wpn-* rows rewritten to the full mil-namespace IRI (derived from the ttl prefix). Seal added; mutant exit 1. grant_sync prune revokes a mismatched live reader (tested on a double). TM-1H: sync, unchanged here. Order: merge, Chris runs grant_sync, read-only check alice survived. Unmeasured on baseline: gov ratchet and sandbox-grantor tests fail locally on the installed iagent_mesh lacking PartialRefusal. Roll-21 doc says live holds "mil#wpn-*": if literal, Chris's pre-sync read decides.

## Round 29 - #264 re-run and the #263 merge

Chris's ruling: TM-1H syncs as is; train #263 then #264; grant_sync is Chris's, in the morning. Stale venv was the cause of the gov/sandbox reds: after `uv sync --extra agent-fleet` the SDK is the v0.9.13 tag (PartialRefusal imports; the dist version string still says 0.9.12). Merged origin/master (incl. #263) into #264 as a forward merge, 13abd2cc; conflict only in the shipped-yaml pinned list (dataset count now 4). Exit codes on that tip: gov ratchet 0, sandbox grantor 0, paths rail + service identity + fin resolver 0, grant_sync + seal 0. ia-saf is left checked out on the #264 branch.

## Round 30 - every read carries a principal; a delegate attaches only to its own case

Branch lane/saf-every-read-carries-a-principal-and-a-delegate-attaches-only-its-own-case, one PR (both parts are test-only seals with no shared upstream). "#6" is dag-tools#6 (gateway verified on_behalf_of, ADR-0064 step 2), not invincible-agent#6. Shapes derived from dag_tools.audit.tag (`<kind>:<value>`, kinds pipeline/user, JSON key `principal`) and the broker's `subject`. Part A: pinned edgy-dag-tools 0.11.0 lacks the modules, so arms are strict xfail on module presence (6 xfailed); against a dag-tools checkout 5 pass and the naming-nobody arm fails (ticket subject=None under observe) = defect, packet to dag-tools/lane/01. Mutants (strip tag; strip ticket subject) exit 1, restored with cmp. Part B: a foreign delegate attaches to a case it did not seed (200, no caller on the attach) = strict xfail, packet to invincible-agent/lane/01 cc architect; controls (seeding delegate, person) pass. Gov ratchet 24 passed, no new refusal site. Both 10-17 saf packets read: informational, nothing open.

## Round 31 - the foreign-delegate arm pins the ruled code

Stacked on #287 (still open at 64b1e2eb), branch lane/saf-the-foreign-delegate-refusal-names-delegate-not-seeder. Chris ruled #287 accepted; Lane 1 fixes the attach caller and refuses with `delegate_not_seeder`. The strict xfail now asserts `detail["error"] == "delegate_not_seeder"` as well as the status, so a different code stays red instead of XPASSing. Mutant (a double refusing 403 `not_the_seeder`): exit 1; the ruled code: exit 0; file restored with cmp. Note for the arm: a working-tree file here is CRLF, so a text mutation must read in text mode. Committed the eight 10-18 to 10-30 notes. Still open in them, not acted on: (1) 10-18 haz-1003 packet asks saf to check whether the draft card's review_request.task_id is the short or long form (`risk-acceptance-HAZ-1003` vs `...-medium~1:acceptance`); (2) 10-21 case-id packet asks saf to update tests/safety/test_fracas_cards_conform.py to the ruled KNOWLEDGE_DOCUMENT archetype for FailureRecordSet (4 reds) or tell the architect it must stay a ranking; (3) 10-18 Q3/Q4 packet is Lane 1's reading with two read-only live checks, nothing addressed to saf to do; (4) 10-30 audit: architect rulings on U1-U11 and I1-I4 pending. The three roll packets are informational.

## Round 32 - FailureRecordSet is a document; the HAZ-1003 task id

Stacked on #291 (#287 and #291 open). Architect ruling via Chris: update the fracas seal to KNOWLEDGE_DOCUMENT; the long task-id form is the contract. (1) The seal was ALREADY updated: #94 (saf's seal into lane/01-202-frs-flip) and #105 (the flip, seal re-trailered) are merged to master, so tests/safety/test_fracas_cards_conform.py is 14 passed on this base and the four reds do not exist anywhere now (they were on the flip branch before the seal landed). Nothing to edit. Mutant: capabilities.py row for FailureRecordSet pointed back at CONTRIBUTION_RANKING (text mode, utf-8, applied): exit 1, the same four tests as Lane 1 named; restored with cmp. No packet to Lane 1: the flip is on master. (2) Measured by driving the real builder `measures.draft_risk_assessment(HAZ-1003)`: task_id is the SHORT form `risk-acceptance-HAZ-1003`. Expected `risk-acceptance-HAZ-1003-medium~1:acceptance` is derived from acceptance_workflow_id + workflow_runner._child_key(case, 1) + the definition's human_await step id. DEFECT in Engine S's own builder (measures.py:520): strict xfail seal added (tests/safety/test_the_draft_card_task_id_is_the_minted_task_id.py), NOT fixed; reported to the coordinator for a ruling on who fixes it. Mutant (builder patched to the long form): the strict xfail XPASSes, exit 1; restored with cmp. On the Windows box open files with encoding utf-8 when mutating measures.py (cp1252 default crashed my first mutation, so it did not apply).

## Round 33 - the draft card's task_id comes from the runner

Stacked on #295 (#287, #291, #295 open). Chris: the card omits task_id until the task exists (absent, not null), filled from the runner's answer; Engine S copies no format. Done: measures.py builds neither task_id nor case_id (I3's `_case_id` mirror removed; the owner stamps case_id via acceptance_request.with_minted_ids). Seals replace the task-id file: (a) the drafted card has no task_id key; mutants None and the short form both red; (b) strict xfail, the gateway dispatch records no task id (Lane 1's; packet placed): XPASSes when filled from the runner's answer, stays red when rebuilt from the case key; (c) no id-format string literal anywhere in safety_agent (form-based AST detector, positive-controlled against planted copies; short form back = red). Deleted the two seals that pinned the mirror (case_id equality, I3 xfail): their premise is gone. Readers: cortex-ui tolerates absent and null (str() -> undefined, falls back to "(no task id)"); its derived fixture has the old short form (cortex's to re-derive); SDK has none; no in-repo reader. Pre-existing and not mine: tests/safety/test_engine_scope_exists_in_policy.py fails on base (finance_agent endpoint_url without a verb segment). Mutations done in text mode, utf-8, newline preserved, each asserted applied, restored with cmp.

## Round 34 - every route a review_request leaves by is sealed to the minted case_id

Forward commit on #301. Chris accepted removing Engine S's case_id on condition of the route test; the broker read-principal seal in #287 stands untouched. Census by AST over src/ (functions calling review_request_of / with_minted_ids or naming the keys review_request / subtask_review_request): two stamping routes, direct (gateway `_stream_direct_outcome`) and ordinary (supervisor `_log_subtask_review_request_asset`, read back by gateway `_project_review_request` / `_open_acceptances_from_run`); `/orchestrate` and `/interview/stream` are one function so both doors share them. Not exits: `review_request_of`, walk_census `_review_request` / `walk` (read the rendered turn). The no_match fallback answers from the generalist, never Engine S. Every route stamps; no xfail and no packet to Lane 1 needed.

Seal: tests/safety/test_every_route_a_review_request_leaves_by_passes_with_minted_ids.py drives each route with the real draft (no case_id) and asserts the minted key on the outgoing card, plus a census arm (found set == covered set; with_minted_ids callers == the two stampers) and a planted-route control. Wiring mutants (text mode, utf-8, applied asserted, cmp restored): dropping with_minted_ids in the gateway direct path reds the direct arm and the census; dropping it in the supervisor reds the ordinary arm and the census.

Exit codes on the tip: tests/safety/ exit 1 (533 passed, 4 skipped, 12 xfailed, 1 failed: fin's `test_engine_scope_exists_in_policy.py::test_THE_VERB_IS_IN_THE_PATH_not_in_the_body`, red on the base too, not mine); gov ratchet exit 0 (24 passed); new seal exit 0 (4 passed).

STANDING ITEM: when Lane 1 fills task_id from the runner's answer (packet 2026-11-07 to lane/01), arm (b) of test_the_draft_card_task_id_is_the_minted_task_id.py XPASSes strict: flip it to a plain assertion then. Arms (a) and (c) and the new route seal stay valid on that fix (the engine card still has no task_id; the route seal asserts case_id only), so no arm fails twice and no other control line needs removing. Today nothing changes.

## Round 35 - re-landing #301 on master

#295 merged into master at 2026-11-08T00:44Z. #301 then merged at 03:40Z into its stacked base (`lane/saf-failurerecordset-is-a-document-and-the-haz-1003-task-id-form`), merge commit 3c440a83, not into master; 96db1a4e (the Engine S fix) and a224425c (the route seal and round 34) are not on master. Recovery by forward commits only: origin/master merged into this branch (clean, no conflicts), new PR with base master; the dead base branch is untouched and nothing on master changed. Merged-tip exit codes: tests/safety/ 1 (533 passed, 4 skipped, 12 xfailed, 1 failed: fin's `test_THE_VERB_IS_IN_THE_PATH_not_in_the_body`, red on the base too); gov ratchet 0 (24 passed); route seal 0 (4 passed). The round 34 standing item (flip arm (b) when Lane 1 fills task_id) is unchanged.

## Round 36 - the ticket carries its id, issue time and as-of (draft, built against 62581a65)

RULINGS, verbatim.
11-08: "#311 merges when green; Lane 1 confirms 96db1a4e is an ancestor of master before calling it landed and deletes the dead base branch. fin owns the endpoint_url red."
v0.13.0: "ticket seals verify against v0.13.0 (PR #33, cut tonight); nothing else changes."
Latest: "ticket seals built against dag-tools 62581a65, to verify at v0.13.0."

(96db1a4e is an ancestor of origin/master as of this round; #311 landed.)

The job: tests/test_every_brokered_read_carries_a_principal.py (#287's seal) gains the ticket-identity arms against dag-tools 62581a65 (#31's merge on dag-tools master). Names read from `dag_tools/domain_broker/ticket_identity.py` (`TicketIdentity.fields()`): `ticket_id`, `issued_at`, `as_of` (plus `as_of_source`), stamped at the broker's `resolve_asset` seam and relayed by the gateway, whose TICKET_ISSUED line names the ticket id against the subject it minted for. All three match the ruling. New arms: each field on the relayed ticket (parametrized), distinct ids per read and as_of is the data's version not the clock, an absent as_of is None never the issue time, and the principal the ticket is minted for (the TICKET_ISSUED subject = the broker's subject) is the query tag's principal. The existing arms are kept, and the strict xfail for an authorize naming nobody still xfails at 62581a65 (not fixed there). Arms are strict xfail on the new module's presence (`needs_identity`); the pin stays edgy-dag-tools==0.11.0 and was not moved.

Measured against a throwaway checkout of 62581a65: 11 passed, 1 xfailed (the nobody arm). Against the pin: 12 xfailed. Mutants (text mode, utf-8, asserted applied, checkout verified clean after): drop ticket_id reds 3 arms; drop issued_at reds 3; drop as_of reds 3 (the version is advertised as `snapshot_id` so a producer's own `as_of` key cannot mask the drop; the first draft of the fixture did mask it and the mutant survived until changed); the log's subject disagreeing reds the new agree arm; the gateway handing the broker another subject reds 4 arms.

PENDING VERIFICATION (a later order, not this job): when `git ls-remote --tags origin` in dag-tools shows refs/tags/v0.13.0, run the three gate checks (tag exists; 62581a65 is an ancestor; tagged pyproject reads 0.13.0), re-derive the three names at the tag, re-run the arms and mutants there. If all match, mark the PR ready and send the packet (first line: for Chris; addressed to invincible-agent/seat/architect) saying the seal is ready for the pin move to 0.13.0. No packet before that.

## Round 37 - the ticket seal verified at v0.13.0

Gate: the v0.13.0 tag (a lightweight tag) is bed53b9c4ff005e91f60ce3db7b41d5033121d65 and peels to the same commit; 62581a65 is an ancestor of it; the pyproject at the tag reads version 0.13.0. `ticket_identity.py` at the tag is byte-identical to 62581a65's; the names are `ticket_id`, `issued_at`, `as_of`. The gateway and broker main modules have no diff between 62581a65 and the tag. Throwaway checkout of the tag: 11 passed, 1 xfailed (the nobody-authorize arm), the same as the 62581a65 run. All five mutants (drop each field; the log subject disagreeing; the broker handed another subject) turn their arms red exactly as before (3, 3, 3, 1, 4 failures); the checkout was clean afterwards and has been removed. #330 marked ready; packet to the architect seat for Chris placed untracked in the master sessions/. The pin was not moved. Move PR must remove the `needs_*` module-presence markers (they XPASS on the move).
