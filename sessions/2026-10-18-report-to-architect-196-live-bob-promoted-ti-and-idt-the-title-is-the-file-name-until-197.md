to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-18
relay: Chris
This report carries no secret.

# Report: lane 01. 196 is live; bob promoted TI and IDT with real rows; the title is the file name until 197 (2026-10-18)

## The seven questions (for your morning ruling)

1. **Rejected rows.** The reject act's quarantine moves the whole prefix to `rejected/<ingest_id>/`
   and rewrites no ref. So a rejected row's extraction becomes unreadable, for audit too. Should
   `/extraction` and `/source` follow a rejected row into `rejected/`? (7f agrees the zero-row
   path is untouched: an `extraction_empty` row is `failed`, not quarantined.)
2. **The door's ContentType.** The door sets none, so the store holds `binary/octet-stream`.
   Should it set `application/pdf` from the kind? Should it also check for `%PDF-` at the door?
3. **The grouped review's three codes.** Should `parts_list_unusable` and
   `superseded_or_duplicate` take the four names? Cortex and I both left them unchanged.
4. **Cortex's reading of "rows=0".** Cortex also holds Promote when the extraction failed. Is that
   what you meant?
5. **The wrong-value gap.** document_promotion has no row-edit wire, and 196 refuses `row_edits`
   there. Until a wire exists, a steward who sees a wrong value can only promote it, reject it with
   a code that does not fit, or leave it. Which, for now?
6. **ADR-0047 §5.1.** Is the 10-17 action-route ruling the §5.1 delegate read?
7. **saf Q3/Q4: the fix shape.** The cause, read from the code and not measured, is that the
   subject resolves to the class the question is about (`FailureRecord`, `RiskAssessment`), and
   no verb takes those as input. The shapes: (a) resolve the asked-of class, (b) widen the
   declarations (risks the authority-ranking trap), (c) accept it. Detail in saf's packet.

## 1. 195 and 196

**195 was already rolled, and 196 is on top of it.** Your directive says 195 is unrolled; that
was my unsent report's fault, not the state.
- 195 is helm rev 200, image `c2b1110f`, chart 0.4.55, rolled 00:46Z 10-18. It carries the
  FRACAS fix, D1–D3, #70, fin's four, gov's #73 and #75.
- `c2b1110f` is an ancestor of 196 (`5034aa05`), measured with `merge-base --is-ancestor`. So
  no separate 195 roll was needed.

What 196 adds:

| item | sha | what |
| --- | --- | --- |
| G, reject codes | `bff5c3af` | `/act` accepts exactly `not_a_notice`, `unreadable`, `parts_unusable`, `duplicate`. Any other code is 422 `reject_code_unknown` with `codes`. `row_edits` on document_promotion is 422 `row_edits_not_for_kind`. |
| E1, zero rows | `9a23cae3` | The stage POST for review with zero part rows, counted by the server, is 422 `extraction_empty`. The row is written `failed:extraction_empty` and no promotion is filed. |
| F2, case_id | `3f3a0994` | Case-runner tasks carry `case_id`. A task holder may read that case. The join is on `case_id`, never `subject_ref`. |
| cortex pin, b3bdab7 | `02240539` | the deep links; chart 0.4.56 |
| cortex pin, 1f5482f | `3bfd3142` | Promote held, the four codes, `?idp=openddil`; chart 0.4.57 |
| packets | `5034aa05` | the OpenDDIL packets; master fast-forwarded to it so CI would build it |

**196 is live: helm rev 201, chart 0.4.57, image `5034aa05`, deployed 04:24Z.**
- Before the roll: no Dagster runs in flight. Two `supervisor_query_job` runs from another lane
  started at 03:58Z, so I waited until they finished at 04:00Z and rolled after that.
- The first attempt refused before any render, because the gitignored secret values file was
  missing from this worktree. I copied it in from the 195 worktree, checked by hash prefix only:
  all three copies are identical. The script's refusal is the guard working.
- Every hook completed. `prime-substrate` took about 16 minutes (04:07Z to 04:23Z), and every ontology reported
  SUCCESS.
- After the roll:
  - every invincible-agent deployment runs the `5034aa05` tag and is ready 1/1
  - cortex-ui runs `1f3ae4ed`
  - doc-tools runs 7f's `ac853308` (#141), in their own release
  - BFF `/health` answered 200 three times, in-pod
- After the roll there was no zombie run. The one STARTED run was a fresh query, 33 s old.

## 2. MRAD tie-break (Directive D): the supersede holds both ways

| row | revision | run | total | OLD label/URL | NEW label/URL | subject triples |
| --- | --- | --- | --- | --- | --- | --- |
| pre-state | | | 157 | 0 / 0 | 1 / 1 | 7 |
| A | 941A `7d9c7437` | `a22fc3fd`, SUCCESS | 157 | 1 / 1 | 0 / 0 | 7 |
| B | 941A `bdf04c5f` | `00279c45`, SUCCESS 02:31Z | 157 | 0 / 0 | 1 / 1 | 7 |

7f read both rows with an unchanged probe. Exactly one label and one URL at every step. Row A
shows the supersede replaces when an older revision arrives after a newer one; row B shows it
replaces on the way back too, rather than accumulating.
- **Read the counts, not the probe's verdict line.** It prints `NOTHING LANDED` for row B. 7f
  says that line is row-A-directional and left it unchanged so the three readings stay comparable.
- **Both rows ran as attempt 3, not 2.** The retry takes the attempt from the row's own counter.

**Still unproven: the PDF retry relaunch.** `ingest_retry_sensor` exists for PDF but has never
been seen launching anything. 7f owns that measurement, on the first real `extraction_empty` row
after 196 and doc-tools `ac853308` are both live.

## 3. The PCN item: bob promotes TI and IDT on 196

**Verdict: both notices went from drop to promoted, with real rows. The card meets the standard
on rows, the PDF and evidence, and misses it on the title.** The title is the file name, not the
notice id. 197 is the fix.

**Measured through the API, not the browser.** alice and bob were minted with the allowed rule
form, and each port-forward lived for one call. Cortex's PCN walk needs the alice and bob
passwords, which I do not hold. So "what the card would draw" below applies cortex's rules to
the served data; I did not see it rendered.

| | TI `PCN#20210316000.1` | IDT `OV-19-05` |
| --- | --- | --- |
| dropped by alice, `/ingest`, `content_kind=pcn` | 04:31Z, 480972 B, `65b3e80d` | 04:53Z, 129620 B, `65992cb6` |
| reached `review` | 04:53Z (22 min) | 05:01Z (8 min) |
| bob's task, `/me/human_tasks` | `document_promotion:sha256:65b3e80d…`, pending | `document_promotion:sha256:65992cb6…`, pending |
| task title and `/extraction` `notice_id` | `TI_PCN_20210316000` | `IDT_PDN_OV-19-05` |
| `/extraction` as bob | 200: 9 parts, 9 rows, `rows_without_evidence` 0 | 200: 17 parts, 34 rows (`affected_mpn` and `ltb_date` per part), `rows_without_evidence` 0 |
| row evidence | all 9 `text_layer_cell`, page 3, each its own cell bbox, in pt | 17 `unique` and 17 `inherited_doc_level`, page 1, **one bbox shared by all 34**, 41% of the page, in px |
| `/source` as bob | 200 `application/pdf`, 480972 B, `%PDF-1.5`, the dropped sha | 200 `application/pdf`, 129620 B, `%PDF-1.6`, the dropped sha |
| bob promotes, `/act` | 200, `dr-771aee2b12d8c98e`, 04:56Z | 200, `dr-e0e72d0a8dee0fcc`, 05:04Z |
| row afterwards, read as alice | `promoted` | `promoted` |

Against cortex's step-3 standard:

| standard | TI | IDT |
| --- | --- | --- |
| title = notice id | **missed.** It shows the file stem. `review.json` has `doc_id_raw` `PCN#20210316000.1` | **missed.** The same: `doc_id_raw` is `OV-19-05` |
| rows drawn | met: 9 rows | met: 34 rows |
| PDF `ready` | met | met |
| row 1 outlined | met, with a solid outline on its own cell | **met only literally.** Each row gets the same dashed region, so the outline does not say which row is which |

Four things the walk showed:
- **The title.** The cortex check "title = notice id" passes against the server's `notice_id`,
  because both read the same field. That field is the file stem. 197 moves the three sites to
  `doc_id_raw`. #141 now fills it, and 7f's doc-tools `ac853308` is live, so 197 will change what
  the card shows.
- **IDT's evidence is a region, not a row.** It is still evidence and is labelled as such
  (`unique`, dashed amber). A steward cannot check one part against its line from this card. That
  is a doc-tools extraction property, and I am passing it to 7f. I have not judged it.
- **The verb.** `approved` on document_promotion is 422 `invalid_decision_for_kind`; the verb is
  `promoted`. The refusal names the allowed set, so a client cannot get this wrong silently.
- **After the promote, bob cannot re-open the document.** `/extraction` and `/source` answer 403
  `not_entitled`, "only the dropper or a holder of the open promotion task". That is the rule
  working. The steward who promoted reads the decision record, not the document.

## 4. F1: the brokered walk row passes, with one finding

`operator.atlantia`, cortex-ui `2f31206`. All five steps passed: creds, broker-screen,
broker-upstream, first-login, and the cell (MECHANIC/MAINTENANCE).

**It passed only with OpenDDIL's leaf pinned as well.** With the sandbox pin alone, the broker's
redirect to OpenDDIL's login failed with `ERR_CERT_AUTHORITY_INVALID`. OpenDDIL's IdP serves a
leaf signed by "OpenDDIL Lab Internal CA". The second pin is an exact SPKI pin, within the 10-14
ruling. A person whose browser does not trust that CA stops at a certificate warning, and the
`?idp` marker does not change that. This is with OpenDDIL and cortex, in packets.

## 5. E3: the two zero-row rows

Both stored objects are real 606-byte `%PDF-1.4` files, and 7f measured the same first sixteen
bytes. The door was right to accept them. Two observations feed questions 1 and 2:
- the stored ContentType is `binary/octet-stream`, because the door sets none
- since the reject at 01:20Z both are under `rejected/`, so `/source` answers 404 and
  `/extraction` resolves to nothing

## 6. saf Q3/Q4 and the task-list read path

**Q3/Q4.** The packet is placed in saf's `sessions/`, and its fix shape is question 7. It is a
reading of the code, not a measurement. It names two read-only checks that would measure it:
- the eligibility trace of run `02fe5689`
- `/find_compatible_verbs` on `FailureRecord` versus `SafetyCriticalItem`

**Task-list read path: confirmed, on 196, with one name to check.** saf's walk left Q1 open: "I
did not read `human_tasks`, so whether a task row exists is UNMEASURED". bob's
`GET /me/human_tasks`, read at 04:51Z, returns the row:

| field | value |
| --- | --- |
| `task_id` | `risk-acceptance-HAZ-1003-medium~1:acceptance` |
| `workflow_id` | `risk-acceptance-HAZ-1003-medium~1` |
| `kind` | `risk_acceptance_medium` |
| `audience` | `risk_acceptance_medium:SUSTAINMENT` |
| `status` | pending |
| `case_id` | null, which is correct: a standalone workflow, not a case task |

- **The name to check.** saf's digest quotes the draft's `review_request.task_id` as
  `risk-acceptance-HAZ-1003`. The row's `task_id` is longer. I did not read the draft card
  itself, so I cannot say whether the field is short or saf shortened it. If the card sends `/act`
  the short form, the act will not find the task. That is saf's to check against the card.
- **Not a census.** bob holds HAZ-1003 (medium) and HAZ-1008 (low) only. HAZ-1001 (serious) and
  HAZ-1007 (high) are other audiences. I did not read them as their holders.

## 7. Next, in 197, and what waits

- **notice_id from `doc_id_raw`, never `manifest.doc_id`.** Three sites: `/extraction`, the status
  row, and the promotion payload, which feeds the decision record. doc-tools `ac853308` (#141) is
  now live, so the change shows on screen at once. Tonight's two cards are the before-picture:
  `TI_PCN_20210316000` should read `PCN#20210316000.1`, and `IDT_PDN_OV-19-05` should read
  `OV-19-05`.
- **Packets placed tonight:**
  - 7f: IDT's shared evidence region
  - saf: the `task_id` name to check against the draft card
- **Waiting, not blocking:**
  - the broker logins for the other users
  - a Topaz sync after the roll
  - the alice and bob walk passwords, if you want the card seen in a browser and not only read
    from the API
