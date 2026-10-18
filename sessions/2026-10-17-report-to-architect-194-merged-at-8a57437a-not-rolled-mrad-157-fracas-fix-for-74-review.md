# Report: 194 merged to master at 8a57437a, not rolled; MRAD reads 157, not 112; FRACAS no_person fix on lane/01-195 for 74's review

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, invincible-agent/lane/saf, doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01 (worktree `ia195`, branch `lane/01-195`), 2026-10-17

re: your 194 list (items 1 to 6), its addendum (7f's five, cortex's evidence_ref), and the Day 2
docs-pool addendum.

## Where things stand

| | |
|---|---|
| master | `5d8800e0` → `8a57437af272c14915ed94e303d8a748ad2fb6ae` (fast-forward) |
| sandbox | **unchanged**: revision 198, `31d0590e…`, chart 0.4.53, cortex `cc2ad9cc…`. Nothing of 194 is rolled |
| lane/01-193 | `35a1d4b9` (the Day 2 LEG 3 change) is pushed and **held**: you ruled no roll of the docs leg before the OpenDDIL case renders, so it is not on master |
| lane/01-195 | the item 4 fix, for 74's review (below). `9b23135` (MODEL skeleton) is held for 195 as you said |

## 194 item by item

1. **Persona-token e2e run: not run. The premise is false.** doc-tools has no `master` branch;
   it has `main` and `origin/main` only. I searched every one of its 215 refs for a TI PCN, IDT PDN
   or OV-19-05 PDF and found none. The only match is a test, `tests/test_ti_pcn_live_miss.py`,
   which carries no PDF. The two PDFs exist only in the sandbox object store
   (`sustainment/inbound/TI_PCN_20210316000.pdf`, `IDT_PDN_OV-19-05.pdf`). The run also needs a
   persona token, and the one script that mints one (`pcn_retry.py`, which reads a persona's
   password from a configmap) was refused by the permission classifier earlier. **Ask, to Chris:**
   the source for the two PDFs (or a ruling that the store copies are the fixtures), and an
   approved way to mint the persona token.

2. **MRAD re-ingest: done. MAINTENANCE_INSTANCES holds 157, not 112, and is exactly the union of the
   six current per-document graphs.** Full packet to 7f and 74:
   `doc-tools/sessions/2026-10-17-packet-to-7f-mrad-re-ingest-six-rows-six-runs-success-maintenance-instances-157-not-112.md`.
   - **Disclosure.** I had written ten rows when the addendum's "six, not ten" arrived. The four
     superseded rows were withdrawn as `failed:superseded_by_later_drop` 53 seconds later, before
     any sensor tick saw them. The tick that launched launched exactly six runs.
   - Six runs, `ingest_retry_sensor_xml` → `xml_graph_sync_job`, all SUCCESS.
   - MAINTENANCE_INSTANCES: absent before, 157 triples after (38 subjects). The six-graph union
     minus the graph is 0, and the graph minus the union is 0.
   - Why not 112: two per-document graphs grew from the same bytes, 520A 14→35 and 720A 19→45. 112
     was the 10-13 extractor's union over ten graphs. Which doc-tools change derives more is 7f's to
     name; I did not look.

3. **Merge order: done, in your order.** saf #65 `47729380`, 74 #66 `457cb7a8`, fin #67 `fc8ed8ab`,
   then #69 `fef8e587`, saf #68 `75f2ce01`, then the cortex pin `9c3f06fe` (68f56bb →
   `sha256:5d5b5dbb…`, chart 0.4.54; full tag 200, short tag and altered digest 404, the `8fe23fc`
   control still `cc2ad9cc`). Then `039563a3` (the addendum, below) merged by sha as `8a57437a`.
   Pre-merge gate on `8a57437a`, 61 consuming files one at a time: 59 green, 1 exit 5 (one skip,
   nothing else collected), and 1 red, `test_no_legacy_dns_references.py`, the known arm (item 6).

4. **FRACAS no_person: built on lane/01-195, for 74's review.** `9f4e9395` on `lane/01-195`, pushed, not merged.
   The supervisor redeems the caller's token only for verbs in `_CALLER_IDENTITY_VERBS`; every other
   dispatch is `svc:supervisor`, and Engine S reads the asker only from the bearer
   (`measures.py:508`), so `_visible_records` raised `NoPerson`. Two verbs join the set, derived
   from code through the engine's own `VERBS` table: `whatFailedOnThisPart` and
   `failureTrendForThisPlatformByMonth`. Not a flip of every dispatch. Seal: 4 passed (behavioural,
   a control differing only in the verb, an ast join seal over the class, and a detector mutant);
   removing `whatFailedOnThisPart` reds arms 1 and 3 on assertions. Review packet in `ia-74/sessions/`.
   **One red blocks the merge, held for you:** `test_seed_canvas_takes_the_template_as_a_slot.py`
   caps the set at `len <= 4` ("short and argued", `64e975bb`, pre-trailer; fin last touched the
   file). It is now 5. Proposal: raise the cap to 5 and cite this ruling. I have not.
   No other `NoPerson`-style refusal exists outside Engine S.

   **saf's Q3, why PROCESS_ENGINEER·MAINTENANCE for bob: routing did not pick it.** Those two
   values are legacy defaults that the gateway writes into every supervisor run config:
   - `gateway.py:5994`, `_launch_supervisor_job(..., persona: str = "PROCESS_ENGINEER")`; the
     `/interview/stream` launch does not pass `persona`.
   - `gateway.py:6898`, `domain = "MAINTENANCE"  # legacy default; supervisor will route by predicate`.
   - cortex-ui sends only `active_persona` and `active_domains` (`useInterviewAgent.ts:673-679`),
     which become the config's `user_persona` (SAFETY_ENGINEER for bob) and `entitled_domains`.
     Routing reads those.
   - In the supervisor, `config.persona` is never read. `config.domain` is read only in
     `create_task_plan` (`dynamic_supervisor.py:198`, `:220`), the legacy fan-out, as
     `plan.get("domain") or config.domain`. So the one place the default can still steer is a
     legacy plan that names no domain; on saf's walk the verb was chosen by predicate.
   I changed nothing. If you want the misleading fields gone, the smallest change is to stop the
   gateway writing them; that is a run-config contract change and yours to rule.

5. **Cosine probe: recorded** at `71a98495`
   (`docs(measure): the mesh:explain cosine probe, taken once -- DocPage ranks 16 to 146, never top 5`).

6. **cortex's SPKI pin: sent** (packet in `cortex-ui/sessions/`), with the `evidence_ref.quality`
   table and the 68f56bb pin status. The pin is public and already committed at
   `docs/runbooks/rolling-a-service.md:267`; re-measured three times against the served leaf.
   **The two reds, and a correction to my 193 report:**
   - **Cluster-DNS string test: Lane 1's own.** My 193 report said "other lanes'". It is not:
     `f4c01b45` carries `Lane: ia-01-netpol/lane/01-netpol`. The literal at
     `tests/test_networkpolicy_flows_survive.py:44` (`_FQDN`) is a cluster-DNS
     suffix the test strips from hostnames, a documentary use, not a call. **Proposal:** an
     allowlist entry for that one line in `test_no_legacy_dns_references.py`. I have not made it;
     widening a ratchet is yours to approve.
   - **`CASE_RUNNER_CLIENT_ID`: lane 74.** The test came in `525c8539`
     (`ia-74/lane/74-acceptance-requester`); the env read at `service_identity.py:112` came in
     `606525ad` (`ia-74/lane/74-origin-chains`).

## The addendum (7f's five, cortex)

- **(1) s1000d skips the document_promotion filing on the stage route: built and on master**
  (`039563a3`, in `8a57437a`; `tests/test_stage_kind_skips_promotion.py`, 3 passed). A delegate's
  drop is written `promoted`, a user's `awaiting_origin`, and the response carries
  `task_status: NO_TASK_KIND_SKIPS_PROMOTION`. **One gap, reported, not fixed:** the later exit from
  `awaiting_origin` (`_file_promotion_if_ready`) never reads the content kind. So when a steward
  supplies the origin on a user-dropped s1000d row, a `document_promotion` task is still filed
  then. Whether that is wanted (the origin step is the human review) or not is yours to rule.
- **(2) Six rows, latest per DMC:** done, see item 2.
- **(5) The pool leg reads the referent flag:** built, `35a1d4b9` on lane/01-193, held. The live
  property is **`universal_referent`** (snake_case) on the referent node, not `universalReferent`;
  the leg reads `coalesce(ref.universal_referent, false) = true`. Only `mesh#Thing` carries it
  live.
- **cortex: `evidence_ref.quality`:** built and on master. `text_layer_cell` → `"cell"`, any
  `region_*` → `"region"`, anything else (including `derived`) → `null`. `obtained_via` is
  doc-tools' `match_method`, unchanged, so a derived row reads `obtained_via: "derived"`. Only
  `parts[i].*` items are rows, so header-level derived fields never appear. Not rolled.

## Day 2 docs pool addendum

1. **Built on lane/01-193 (`35a1d4b9`), held.** The seal's first half holds: "how do I add an
   engine" as agent-user puts DocPage's verb in the candidate list. **The control conflicts with
   the existing contract, so I have not asserted "pool unchanged".** `mesh:explain` declares
   `domains: []`, so it passes every domain's entitlement filter, and
   `tests/routing/test_find_compatible_verbs_via_mesh_graph.py` already asserts explain IS in a
   COST-entitled pool. An ordinary cost ask therefore gains exactly one universal candidate, by
   design. The control as written ("pool unchanged") would contradict that seal. **Ruling needed:**
   either the control is "the pool gains only the universal verb" (my recommendation: it agrees with
   the existing seal and can be asserted exactly), or explain should not
   enter non-docs pools, which changes the existing seal.
2. **Cosine probe: recorded** (`71a98495`).
3. **`test_citation_paths.py`: fixed** at `f63f3b94` (the four dead links were not the four
   allowlisted ones).
4. **Walk "how do I add an engine": not run.** It needs `35a1d4b9` live, and you ruled no roll of it
   before the OpenDDIL case renders.

## Overnight priorities

Neither (A) OpenDDIL end to end nor (B) the PCN/PDN steward review is closer from this window
except through the review card's `quality` key (B) and the cortex pin, both on master and unrolled.
The next roll carries `8a57437a`; I will not roll until you say so, since 194 changes the stage
route and the cortex image together.

## Asks

1. Chris: the PDF source and a persona-token method for item 1.
2. You: the Day 2 control (pool gains only the universal verb, or explain leaves non-docs pools).
3. You: the allowlist entry for Lane 1's own DNS literal.
4. You: whether a steward's origin on a user-dropped s1000d row should file a promotion task.
5. You and 74: the identity-set cap (4 → 5) so `9f4e9395` can merge.
6. You: whether to roll `8a57437a` now.
