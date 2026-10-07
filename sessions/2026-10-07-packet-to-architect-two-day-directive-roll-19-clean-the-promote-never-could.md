    from: ia-01/lane/01
    to:   seat/architect (relayed by Chris)
    date: 2026-10-07
    re:   the two-day directive (items 1-5)

# Roll #19 is clean; a document filed through the stage route can never be promoted

## Short form

- **Item 1:**
  - Roll #19 is CLEAN and leg 11 is green.
  - PCN26-119 reached `review` on bob's queue, and bob's promote was refused 422: the task
    payload lacks the decision record's fields.
  - That is a Lane 1 join defect that no seal covered. It is sealed now. The fix needs one field
    from doc-tools, and a packet to 7f proposes it.
  - Hop 5 (alice asks, `provenance_floor`) has not run.
  - The six data modules are held: the door has no file kind for them.
- **Roll #20:** clean, but it shipped a defect: a first-time event 500s at the door and `GET /cases/<unknown>` 503s. Fixed, gated and rolled as #20b (3e6d9e9f, rev 177). Clean, and `/cases` 404s live.
- **Item 2:** BLOCKED. Minting the OpenDDIL delegate's token was refused by the session's
  classifier, and I will not route around that. It needs Chris.
- **Item 3:** all five pieces are built and integrated on `lane/01-roll20` (merged to master a0c2ba18, full-suite gate met).
  Rolled as #20 (see "Roll #20" below).
- **Item 4:** the flag-on branch is pushed. Roll #21 also needs `extraEgress` in the untracked
  secret values file.
- **Item 5:** the CLAUDE.md lines are on master here. Packets are placed in the other three repos.

## Item 1 -- roll #19, then the fresh-notice drop

**Roll #19** (914c7faa plus grants):
- REAL_EXIT=0; helm revision 175; all 19 deployments on 914c7faa.
- The task-grant-sync hook added 1 relation and read back 16/16. The liaison grant landed, so
  Chris does not need to run the sync by hand.
- Leg 11: exit 0, with 39 CLEAN, 0 Traceback, 3 EMPTY-UNDECIDED (datahub-gms, domain-broker,
  the pub-tools code location), 1 scaled to 0, and the controls present.

**PCN26-119:**
- It went received -> extracting -> review by about 04:04Z, and doc-tools' `ingress_user_sensor`
  is RUNNING.
- The promotion task sits on bob's queue (18 rows, 1 match).
- Promote as bob, with a reason:
  1. First try: 422 `invalid_decision_for_kind`. My probe sent `approved`, and this kind takes
     `promoted`/`rejected`. The comment on `HumanTaskActRequest.decision` (gateway.py:646) still
     says "approved | rejected"; it is stale.
  2. Second try: 422 `promotion_payload_invalid`. The payload is missing object_ref,
     content_kind, pipeline_version, format_fingerprint, standing and extraction_ref.
- **Cause:**
  - `update_ingest_stage` files `{ingest_id, domain, dropped_by}`.
  - `promotion.subject_from_payload` requires the decision record's subject, and the reason is
    sound: "a record that cannot say what was reviewed is not evidence".
  - Both sides were sealed alone; the join between them was not. So **no document filed through
    POST /ingest/{id}/stage has ever been promotable or rejectable.**
- **Sealed:**
  - A strict xfail, pinned to `PromotionRefused`, is on `lane/01-roll20` @ 635c62ea.
  - Positive control: a filer carrying every field turns it XPASS(strict), which is red.
- **Fix, proposed rather than built:**
  - Lane 1 can supply `object_ref`, `content_kind` and `standing` (`supervised`, since a human
    reviews it).
  - `extraction_ref`, `pipeline_version` and `format_fingerprint` describe doc-tools'
    extraction. Under ADR-0034 the last two must be derived from the artifact, not asserted by
    the caller.
  - So the contract is one field: doc-tools names its extraction (`extraction_ref`) on the
    `review` post, and Lane 1 reads the rest from that artifact.
  - Packet: `doc-tools/sessions/2026-10-07-packet-to-7f-the-review-stage-must-name-its-extraction.md`.
  - **Ruling wanted:** is `standing: supervised` right for a human-reviewed user drop?
- The capture is in cortex-ui's sessions (`2026-10-07-payload-ingest-pcn26-119-rev-175.json`).
  Hop 5 has not run.

**The six mock modules as `s1000d-data-module`: held.**
- The door accepts `kind` pdf|cad only (`ingest_status.KINDS`). An XML data module would have to
  be labelled `pdf`, which is false at the door and would fail in doc-tools' PDF extraction.
  That makes six stranded live rows for nothing.
- Even past review, the promote is blocked twice over:
  - the payload defect above;
  - `document_promotion:MAINTENANCE` -> liaison, a non-interactive user with no credentials, so
    only OpenDDIL's delegate can act, and that is item 2's blocker.
- The modules are on doc-tools `feat/s1000d-week2-walk-seal` (351c223), not on main.
- `s1000d_fault_walk` is `stub: true`, retired by 7f Phase 2(e). Walking from the live graph, the
  rehearsal x3 plus one refusal, and the DMC in `label` all wait on that.
- **Ruling wanted:** is an XML leaf added to the door's file kinds, or do data modules enter
  through doc-tools' own walk ingest?

## Item 2 -- idempotency measurement: BLOCKED

The delegate is `svc:openddil`. Getting its token meant reading Keycloak admin material, and the
classifier refused it as credential exploration. I stopped there and will not pursue it by
another route.

To run it, Chris mints the delegate token, or tells me where a sanctioned one is. The probe then
POSTs the synthetic `maintenance-fault-event` twice and expects 200, the same case_id, and one
case. The OpenDDIL reply, with the time and the revisions/status caveats, follows the
measurement.

## Item 3 -- roll #20 branches

All are pushed, and each was red-checked on its named arm. Integration: `lane/01-roll20` @
635c62ea, from master 2b6fe0f6.

| piece | branch @ sha | note |
| --- | --- | --- |
| GET /cases/{id} as cortex's WorkflowCasePayload | `lane/01-cases` 73ab540d | |
| event status record; a repeat event_id -> keep_revision | `lane/01-event-status` caf94a75 | `case_opened` out of band; a repeat goes to `/revise`; 400 -> 422, 409/404 -> 409 `revision_not_kept` |
| POST /ingest/{id}/retry | `lane/01-ingest-retry` 75ee59a5 | shares the find-or-file helper with the stage route |
| awaiting_origin for domainless rows at review | `lane/01-awaiting-origin` 71657018 | explicit `domain: null` (pydantic fields_set) -> no task; an omitted key stays 422 |
| Topaz manifest + member-sync hooks | already in | `topaz-manifest-load-job.yaml`, `task-grant-sync-job.yaml`, both enabled in sandbox |

Integration merge (9fbe283c):
- **Conflicts:** `ALL_STATUSES` carries both new out-of-band statuses. The domainless decision
  stays in the stage route, ahead of the shared helper. `awaiting_origin` joins retry's terminal
  set, red-checked on `[awaiting_origin]`.
- **Area tests:** 201 passed.
- **Full suite (gate):** compared by failure identity against master 2b6fe0f6, run alone. Master had 52 failed and 6513 passed; the branch had 53 failed and 6576 passed. The one new red was the endpoint-gating manifest (two undeclared routes), fixed at a0c2ba18; the file passes alone (22). The SDK-pin arm is parametrized by worktree name, so it is one pre-existing failure. Fast-forwarded master 2b6fe0f6 -> a0c2ba18 and pushed. The worktrees ia-01-cases, ia-01-event-status, ia-01-ingest-retry, ia-01-awaiting-origin and ia-01-roll20 STAY: their trailers name them, and test_every_commit_names_its_lane reds once a named worktree is removed.
- **Consumers told:** cortex-ui has a placed packet (`case_opened` is out of band, so its parity
  test stays green). 7f has the awaiting-origin packet: no pdf/engineering-document/doors-export
  rows until 7f's domainless arm asserts the ruled set.

### Roll #20

Roll #20 is CLEAN on the fleet. Its first live probe found a defect that roll #20 shipped.

- **Roll:** a0c2ba18 (CI image build green); REAL_EXIT=0, 04:54:51Z -> 05:24:27Z; helm
  revision 176 deployed; 19 deployments on a0c2ba18, all 1/1.
- **Leg 11:** exit 0. 39 CLEAN, 0 Traceback/DIRTY/ERROR, 3 EMPTY-UNDECIDED (the same three as
  #19), tika scaled to 0, controls present.
- **Live probe (read only):**
  - `GET /ingest/{PCN26-119}/status`: alice 200 `review`; bob 404.
  - `POST .../retry`: alice 200 `ALREADY_FILED`; bob 404 with an identical body.
  - `GET /cases/<unknown>`: **503 `runner_unavailable`, expected 404.**
- **Cause, measured:** for an unknown key, the runner's shared `case` handler answers **200 with
  an EMPTY body** (content-length 0). `ctx.get` returns None, and Restate serialises None as
  nothing.
  - `_fetch_case` expected a 404, so `resp.json()` raised, and the route maps that to 503.
  - **The same read sits in `POST /ingest/events`' repeat detection, outside any try.** So every
    FIRST-TIME event_id would 500 at the door: the item-2 path and OpenDDIL's live path.
  - The bff log shows no event since roll #20, so nothing has been lost yet.
  - Root of the miss: both test doubles invented "absent". One answered 404; the other's
    `.json()` returned None. Neither spoke the wire.
- **Fix:** `lane/01-case-empty`, from a0c2ba18. One helper reads an empty 200 as None and is used
  at all three sites. The doubles now speak the real empty body, and one arm per site uses a real
  `httpx.Response`. Pushed at `3e6d9e9f`. Three red-checks, each on a named arm: reverting `_fetch_case` reds the real-wire 404 arm; reverting the events read reds the real-wire arm plus four existing first-event arms (the doubles now speak httpx); dropping the 503 wrapper reds the non-JSON arm. Area: 113 passed, 1 xfailed. Full suite run alone, compared by failure identity with roll #20: 52 failed, 6583 passed. No new failure except the SDK-pin arm under the new worktree name, a known pre-existing failure. The gating-manifest red is gone. Master fast-forwarded a0c2ba18 -> 3e6d9e9f and pushed. The worktree ia-01-case-empty STAYS, because its trailer names it.

**Roll #20b (corrective, 3e6d9e9f): CLEAN.**
- REAL_EXIT=0, 06:09:14Z -> 06:39:03Z; helm revision 177; 19 deployments on 3e6d9e9f.
- Leg 11: exit 0. 39 CLEAN, 0 Traceback/DIRTY/ERROR, the same 3 EMPTY-UNDECIDED, tika scaled to 0.
- Live re-probe:
  - `GET /cases/<unknown>`: **404 `case not found`** (was 503).
  - Status and retry are unchanged: alice 200 `review` / 200 `ALREADY_FILED`; bob 404 / 404.
- The events door's first-event path is fixed in code and sealed against a real `httpx.Response`.
  It has NOT been exercised live: that needs the delegate (item 2).
- Roll #21 (NetworkPolicy) keeps its number. #20b is a corrective roll, not a directive item.
- **Consequence for item 2:** the idempotency measurement must run AFTER this fix rolls, or its
  first POST measures this defect rather than idempotency.

## Item 4 -- NetworkPolicy on

- `lane/01-np-on` @ cac1d07b, pushed, not rolled. Render: 0 NetworkPolicies on the base chart,
  20 with sandbox values.
- **Before roll #21:** `extraEgress` (the object store and the model endpoint) must be in the
  untracked `values-sandbox.secret.yaml`, or the policies cut those flows.
- The census then runs flag-on, so a cut-off engine shows up as a routing miss.
- Roll #21 goes only after #19 and #20 are both clean.

## Item 5 -- CLAUDE.md

- On master here at 2b6fe0f6.
- Packets placed (not committed) for the owning lanes of cortex-ui, doc-tools and
  iagent-mesh-sdk. doc-tools has no CLAUDE.md yet.

## Other findings

- No `maint_fault_approval:*` grants exist, so the decide step has no recipients.
- No maintenance-bridge entitlement holders exist.
- The "Release Helm Charts" workflow failed on a16e2391. I have not investigated it.
- Two classifier refusals this run:
  - the OpenDDIL go-ahead packet (sensitive detail), which Chris relays himself;
  - the delegate token (above).
- **Disk:** drive C hit 0 bytes free mid-run, and an implementer's writes failed with ENOSPC. It now holds about 3.7 GB of ~935 GB. Lane 1's venvs are hardlinks into the uv cache, so deleting six of them freed only about 0.2 GB. The consumer is outside Lane 1. The uv cache (11.7 GB) and TEMP (10.9 GB) were left alone: clearing them is Chris's call. Another ENOSPC would break a full-suite gate or a roll mid-flight.
