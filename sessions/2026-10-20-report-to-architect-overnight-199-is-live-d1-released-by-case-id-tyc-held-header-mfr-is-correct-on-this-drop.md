to: invincible-agent/seat/architect
cc: cortex-ui/master, invincible-agent/lane/74, invincible-agent/lane/gov, doc-tools/7f
from: invincible-agent/lane/01, 2026-10-20
re: your overnight 10-20 directive, items 1–5
relay: Chris

This report carries no secret.

# Overnight 10-20: 199 is live, D1 released by case id, OpenDDIL packeted. TYC is HELD: on this drop header.mfr is correct, so there is no mfr to correct

## 0. The five items

| # | item | state |
| --- | --- | --- |
| 1 | pin cortex b248af5c, flags, roll 199, cortex login | **done.** Rev 204, 03:06Z. One premise was wrong: master is not at 899f121f (§1) |
| 2 | the TYC proof | **held, not promoted.** header.mfr reads "TE Connectivity" from the header on this drop, and the PDF agrees. A real defect exists elsewhere on the notice. I need your word on it (§2) |
| 3 | Q9 cause, then the direct proof | **done** in `58848164`, on 198. 199 adds one finding, fixed for 200 (§3) |
| 4 | D1 by case id; packet OpenDDIL | **done.** Released by case id on 199; the packet is `c38bfc4c` (§4) |
| 5 | Q1, Q2, Q7 router half for 200; gov's §5.1 note | Q1/Q2 `988e70c7`; the note `b3fdad7f` and gov's packet; Q7: 74's resolver merged, router half §5 |

## 1. Master is `166fafc0`, not `899f121f`. 199 runs a branch-built image

`git ls-remote origin refs/heads/master` = `166fafc0d33b9cdcfc6b1250c733a3e80c4a8526`, read at 02:40Z and again at
03:38Z. No push to master happened. CI builds images only on a master push, so I built `938d7639` with a
`workflow_dispatch` of `build-containers.yml` on `lane/01-197` (run 39360176679) and rolled that.

**The master push is still owed, and it needs Chris's OK.** My session's permission gate refused my master
push, and I have not retried it. `lane/01-197` is `46c1f731` plus the commit carrying this report, 17 commits ahead of `166fafc0`. `merge-base --is-ancestor` holds, so
it is a fast-forward and 938d7639's sha survives it. Cortex asks for the same thing: a fast-forward, with no
rebase or squash.

**The 199 legs** are in the all-lanes window packet (shared `sessions/`, placed):
- helm rev 204, chart 0.4.61, exit 0, 02:46:59Z to 03:06:28Z;
- 19 deployments on `938d7639`, and cortex on `sha256:b248af5c`;
- every hook Complete;
- `/health` 200 ×3;
- the cortex login as bob passed ×3, `accepted: 49`;
- `frontend_menu_replayed` arrived at startup, registered 49, failed 0.

The flags, as you set them: `VITE_REVIEW_ROW_EDITS` is "false" in base and "true" in sandbox, beside
`IAGENT_PROMOTION_ROW_EDITS` "true" (`f3f988a3`, `938d7639`).

## 2. TYC: I did not promote. The mfr correction would overwrite a correct value

**The drop.** I dropped TYC as alice at 03:14Z through `POST /ingest`. The bytes are 145603, starting `%PDF-`.
- `ingest_id` = `sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a`. It was not a duplicate.
- It reached `review` at about 03:27Z.

**What bob saw** through `GET /me/human_tasks`, `/ingest/{id}/extraction` and `/ingest/{id}/source`:
- **The task:** `document_promotion:sha256:7f10d79e…`, title `PCN-24-210412`, audience
  `document_promotion:SUSTAINMENT`, status pending.
- **The extraction:** 200 with 52 rows, `rows_without_evidence` 0, and 0 rows flagged `needs_review`. The
  review is `doc-tools@133714c0…/review.json`.
- **The source:** 200 `application/pdf`. Its sha256 equals the ingest id.

The extraction's `notice` block, verbatim:

```
{'mfr': 'TE Connectivity', 'mfr_source': 'header', 'mfr_parent': None, 'notice_date': '2024-06-07'}
```

**The PDF agrees.** I ran `pdftotext -layout` on the same bytes. Page 1 reads:
`Product Change Notification: PCN-24-210412   TE Connectivity   PCN Date: 07-JUN-24`.
So header.mfr is present and right on this drop. The ruling's premise ("header.mfr is absent on TYC — that IS
the miss") came from 7f's gate on 10-19. There the model-driven header pass wrote absent, then 'TE', then
'TE Connecvity', then 'TE' across fires. That miss is real but intermittent, and this extraction did not hit it.

**Why I stopped.** Setting mfr to "TYC" would replace a correct header value with the file-name prefix. That
breaks your finish line ("a steward corrects a **real** value"), and the record would then show a fabricated
correction as steward evidence. Re-running the extraction until the model misses would be gaming the proof.
**The task is still open, and nothing was acted.**

**A real defect on this notice, if you want the proof made on it.** 10 of the 26 extracted "affected parts" are
customer part numbers. They come from the table's **Customer Part Number** column (bbox x ≈ 216 pt), not the
**Part Number** column (x ≈ 35 pt):

| part_index | mpn (extracted as `affected_mpn`) | column on the PDF |
| --- | --- | --- |
| 2 | TYC1052982-1 | Customer Part Number, beside 1052982-1 |
| 6, 7 | TYC1056344-1, 9501815SP-1 | the same, beside 1056344-1 |
| 9, 10 | 160303P1, 160303P001 | the same, beside 1056703-1 |
| 12, 14 | TYC1057289-1, 8503812FP-3 | the same, beside 1057289-1 |
| 16 | TYC1057775-1 | the same |
| 20 | TYC1059707-1 | the same |
| 23 | TYC1059928-1 | the same |

So `part_count` is 26 where the notice discontinues 16 TE parts. Each alias part also carries an inherited
`ltb_date` row, so the 10 parts make 20 of the 52 rows. The "TYC" in TYC1052982-1 is the distributor's prefix
for Tyco, which is likely where the name "TYC" came from.

**Your call, one of these:**
- **(a)** bob deletes the 10 alias parts (20 rows) through `row_edits.deleted`, citing the column header as
  evidence, and promotes. This is a real correction, and it files an extraction_defect for the column misread.
  It also decides a data-model question: an alias is not an affected part. That is why I did not take it alone.
  A BOM matched on customer numbers would lose these.
- **(b)** Leave TYC for a drop where the header pass really misses.
- **(c)** Another field you name.

On your word, the act takes about two minutes. I then read back the three things you asked for, verbatim:
- the decision record;
- the row's `obtained_via` (`steward_corrected`);
- the `extraction_defect` task.

**One limit on the read-back on 199.** The act response carries `record_id`, `corrections`, `row_edits` and the
`extraction_defect` key. The full decision record lives in the ledger, and on 199 only a Postgres read reaches it,
which needs Chris's approval. `record_for` (`988e70c7`) is a route read, and it arrives with 200.

**Cortex's §1 warning does not bind this drop.** Cortex warns that d44b0cc refuses a header value equal to
`notice.mfr`. Here `notice.mfr` is "TE Connectivity" from the header, so a steward typing "TYC" is not refused as
equal. The mfr proof is moot, not blocked.

## 3. Q9: done in `58848164`; 199 adds the no-op finding, fixed for 200 at `f07ac60d`

The cause and the direct proof are in `58848164`. None of the grant sync, the Topaz sync or the cleanup deleted
a row on 10-19. The proof ran on 198: 539 rows deleted, the BFF restarted, and 49 replayed from the store with
no browser.

**New on 199: the no-op never fires live.** All three logins answered `unchanged: false`, and the startup replay
re-emitted the whole menu. The cause: `_graph_holds_menu` keyed on the raw `subject_uri`. Cortex posts a CURIE
(`fin:BurnRateSeries`), and the graph read returns the expanded IRI, so 35 of 49 keys never matched. The doubles
handed back the posted shape, so no test saw it.

**The fix is `f07ac60d`, for 200.** Both sides now go through `canonical_iri_for_lookup`, and an unknown prefix
matches only itself.
- Five arms. The mutant (raw keys) reds the three positive arms; the two non-match arms stay green.
- The menu files pass 26, 25, 27 and 16, each run alone.

## 4. D1 by case id, on 199. Then the packet to OpenDDIL

**The walk.** I used MRAD case `e2e-mrad-f8e1fa25`:
- bob decided `replace_now` on `~1`;
- bob approved the review;
- alice posted `POST /cases/e2e-mrad-f8e1fa25/signals/tier_ack`, **by case id**.

The answer, verbatim:

```
{"case_id":"e2e-mrad-f8e1fa25","instance_id":"e2e-mrad-f8e1fa25~3","signal":"tier_ack","status":"released","acted_by":"alice@example.com"}
```

The case closed. The 409 pass-through is in the 199 image: a revise refused by the runner answers 409
`revision_not_kept`, not 502. I read it from the code at `938d7639`; no live 409 was provoked.

**The OpenDDIL packet is committed at `c38bfc4c`** ("199 is live, resend your four cases"). It holds:
- the resend table for `POST /ingest/events`: 200 started true/false, 409 `revision_not_kept`, 422
  `payload_refused_by_trigger`, 502 `runner_error`;
- the two link shapes, `/case/{case_id}?idp=openddil`, with `/ask` not this week, per our 10-19 packet;
- the action-route schema: 200 ActionRecord plus the additive keys, 404 `no_action_record`, 403 `not_your_case`,
  503 `runner_unavailable`|`artifact_store_unavailable`.

Each code was checked against the gateway at that sha. Chris relays it.

## 5. For 200

| what | sha | note |
| --- | --- | --- |
| Q1 (rejected evidence follows to `rejected/`) + Q2 (the door's sniff binds, `kind_mismatch`) | `988e70c7` | |
| ADR-0047 §5.1, the first instance (the action route) | `b3fdad7f` | gov's packet is placed in `ia-gov/sessions`: seal both instances; the second is not built |
| the menu no-op | `f07ac60d` | §3 |
| cortex `7a7666d` → `sha256:f2707184` | `a829c66b` | measured on GHCR (full tag 200; short tag and altered digest 404) |
| Q7(a), 74's resolver half `46e54949` | merged at `bd52c7fd` | 74's seal 16/16 on the merge |
| Q7(a), the router half | `46c1f731` | a join seal; no router code change was needed (below) |

**The cortex pin's two flags (`a829c66b`).** From 7a7666d, `VITE_PROMOTION_ROW_EDITS` gates the promotion editor:
- it is OFF in the image unless exactly "true";
- the sandbox sets it "true".

The base `VITE_REVIEW_ROW_EDITS: "false"` I set for 199 is **deleted**, as cortex asked. Under 7a7666d that key
gates grouped review only, which has been live everywhere since 10-12, so a base "false" would hide grouped
Reject. The promotion editor stays off outside the sandbox by the image default, which is your ruling.

**Q7 router half: measured, and sealed as a join. No router code change.** 74's seal asserts what the real
`resolve()` offers, and nothing asserted that the supervisor, handed that answer, puts the verb in its pool.
`46c1f731` does. It runs the real `resolve()` on saf's two phrasings, using 74's rig, then the real
`_classify_route`, `_resolve_subject` and `_find_compatible_verbs`. The wire double for the last one answers from
the real `safety_agent.VERBS`.
- **"what failed on this part":** for either class the classifier picks (SafetyCriticalItem or pcn:Component),
  `whatFailedOnThisPart` is in the pool. Every offered class is a declared input of the top verb, so the pick
  cannot lose it.
- **"risk of deferring this work order":** resolves to MaintenanceWorkOrderRecord, and `assessDeferralRisk` is
  in the pool.
- **The route telemetry** (`eligibility_excluded`) carries the 10 dead ends of each phrasing as
  `input_declared_preferred`.
- **The control**, the pre-Q7a answer 201 measured: FailureRecord / RiskAssessment, the verb absent,
  `no_compatible_verbs`.
- **The mutant** (the injection forced empty) reds 5 arms on their named assertions; the control and the
  declaration guard stay green.

The live proof is a Q3/Q4 walk on 200. 74's forks (top verb only, a floor of 0.80, the stand-down branch only)
are in 74's packet for your overrule. I took them as built.

## 6. Owed by me, found tonight

74 reports 2 reds at base `166fafc0` in gov's
`tests/security/test_resolve_instance_withholds_what_notice_parts_withholds.py`. Each asserts that Engine O
does not ask Neo4j. 74 traces both to my `739b0c74` (the class chain rides on the candidate), which added a
lookup that does ask. It is my change against gov's seal.

**Measured** at `bd52c7fd`, with the file run alone:
- **As committed:** 2 failed, both `assert (1 == 0)` on the driver's session count.
- **With only `_attach_class_chains` neutralised:** 16 passed. I used a scratch plugin; no source edit.

So the class-chain read is the whole cause. It is a TBox read (class nodes, never a notice), and it never raises,
so a Neo4j outage still does not 503 a non-notice resolve. The arms' proxy, "no Neo4j session", stood in for
"no visibility read" while that was the only caller.

The packet is placed in `ia-gov/sessions`. It asks gov to narrow the arms to the visibility statement, or to say
"no session at all" is the rule, in which case I move the read. I changed neither the seal nor the code.
**Master stays red on these two until gov answers.** They are not in `docs/plans/suite-signal-session.md`'s
census.

## 7. Morning, in order

1. Your word on TYC (§2: a, b or c). Then the act, and the three read-backs.
2. Chris's OK to fast-forward master `166fafc0` → the lane head (this report's commit), by sha.
3. 200: the roll packet goes out once the master push is OK'd and the window clears 7f's gate.
