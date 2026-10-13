# Report: roll 188 is live on `c9091040`. The door 400s, the watchdog failed 15 stale rows (not 5), notice_id is on the wire, and **xml passes the door but doc-tools' sensor only takes pdf**

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01, 2026-10-13
re: your 2026-10-13 ruling (cad / roll 188 without the poller / notice_id now) and the 10-12
ruling 1–4

## The roll line

- **helm revision:** 191, deployed, chart `0.4.45`. Revisions 189 and 190 were 187's.
- **fleet image:** `c9091040`, on all 19 invincible-agent deployments, each 1/1. The full-sha tag
  resolves; the abbreviated tag is not found.
- **frontend:** cortex-ui `88a65d4`. The running pod's imageID is `sha256:7b2b612913c7…`.
- **master:** `28645d6b..c9091040`, fast-forward. The set was merged by sha on `lane/01-rev188`,
  each part `--no-ff`:
  - step-1 `86d2dccb` (an event case runs as its dropper);
  - Q4 `2fc5f96d` (a member list keeps its menu);
  - the failure branch `6d5c791f`:
    - `failure` on the row;
    - the watchdog (600 s / 30 s, chart values);
    - the retry route;
    - `GET /ingest/retries`;
    - the door 400;
    - the xml overlay row;
    - `notice_id`.
- **gate:** 33 test files, one at a time, against the merged tree. These are the merges' own
  files, every consumer of `slot_disposition`, every ingest file and both chart seals. All
  exit 0. `helm template` and the dry run exit 0.
- **Dagster:** before the roll, 0 runs were QUEUED, STARTING or STARTED.

## Not in 188: SDK v0.9.10. It reds our own seal, and the fix is yours to rule

v0.9.10 adds a sixth `obtained_via` rung, `steward-corrected`, and places it LAST (farthest from
truth). Our `src/iagent/provenance.py` has five rungs.
`tests/test_the_answer_carries_its_provenance_floor.py:147` asserts that the two are equal, and
line 125 asserts that `user-drop` is last. So the re-pin is a ranking change, not a version bump.
**Where does `steward-corrected` rank?** The SDK puts it below `user-drop`, which makes a
steward's correction the least-trusted source an answer can cite. Everything else in
v0.9.8..v0.9.10 is additive: `parent_link_field`, `SystemOfRecordQuery`, `ExtractionDefect`,
`WorkflowDefinition`. Today's pins: 14 engines are on `v0.9.8`; the root, restate_analyst and
safety_agent are on `60e56c97`, which is older than v0.9.8. Both pins are ancestors of v0.9.10.

## Live, measured on 191

| check | result |
| --- | --- |
| kindless drop | **400** `content_kind_required`. `registered`: doors-export, engineering-document, pcn, pdf, pdn, s1000d-data-module, xml |
| `content_kind=cad` | **400** `kind_unregistered` |
| `content_kind=xml` | **200**, `received`. The status carries `"notice_id": null` |
| `GET /ingest/retries` as alice | **403** `not_doc_tools` |
| retry of a timed-out row | **200**, back to `received` with `attempt` 2; `failure` cleared |
| the retried row, and the xml probe drop | both failed `timeout` again in the same watchdog pass, 622 s after the retry (600 s plus at most one 30 s tick). The retried row reads `attempt` 2. This is Finding 2, measured |
| a failed row on the wire | `failure: {reason_code: "timeout", step: "received", run_id: null, pin_digest: null, failed_at, reason}` |

**The Postgres smoke you asked for.** Before the roll, I evaluated the same `jsonb_build_object`
read-only against the live database. It keeps both a literal `NULL` and `NULL::text` as JSON
`null`; it does not drop the key. The live table had no `run_id` column yet; the 188 BFF's
migration added it. The first watchdog pass then wrote exactly that shape, in one UPDATE.

## Finding 1: the first watchdog pass failed 15 rows, not 5

Those 15 were every document row at `received`:
- the five pcn pdfs you ruled on (736499f2, fa231498, 0096a523, c75116ec, 734d9c94), aged 20 h
  to 12 days;
- **ten `s1000d-data-module` xml drops** by alice, from 10-08 and 10-09, aged 110 to 120 h.

The rule you ruled ("no stage move within 600 s") is literally true of all fifteen, so I did not
hold the roll. Finding 2 is why the ten were stuck.

## Finding 2: xml passes the door, then doc-tools' sensor silently drops it

You asked me to confirm that xml passes. **It passes the door, then stops at the next hop.**
- **The sensor.** doc-tools `ingress_user_sensor` (origin/main `2961ab9`,
  `doc_tools/definitions.py:141`) has
  `s3_filter=r"^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$"`.
- **The live drop.** After my xml probe drop, the daemon logged `ingress_user_sensor skipped:
  All 2 new objects filtered out by patterns`. That is the file and its sidecar.
- **Every non-pdf user drop goes the same way.** It is accepted, never picked up, and failed
  `timeout` 600 s later. The ten s1000d drops are this, five days old.
- **A retry does not help.** It re-opens the row; the sensor still will not see the object, and
  7f's poller launches the pdf job.

The watchdog now makes this visible: alice sees `failed / timeout` with Retry. Before 188 the
row sat at `received` for ever. That is honest, but Retry is a false promise for these rows.

**This is 7f's surface, and the question is yours.** Either:
- (a) the sensor takes `ingress-user/xml/` (and `cad/`, when that row lands), routed to the
  classified stage as your cad ruling says; or
- (b) the door refuses a kind whose format no sensor takes, so that `registered` means
  "will be processed", not only "is known".

Today the door's list and the sensor's regex are two independent statements of what is accepted,
and no test joins them. I have changed nothing here.

**The cad row has the same problem.** 7f's `KIND_MAPPING` row plus my overlay row gets a cad drop
past the door, and into the same filter.

## Finding 3: the two content-kind registries disagree, and nothing seals them

The door reads `CONTENT_KIND_OVERLAY_DIRS`, which is our `policy/overlays/openddil-lab/content_kinds/`,
not doc-tools' `registry/content_kinds/`.
- **xml:** it was in doc-tools' registry and not in ours. I added it at `90f0651b`, mirroring
  passes and outputs, domain null. An arm drives the door against the real shipped overlay.
- **work-instruction:** it is in doc-tools' registry (domain `manufacturing`) and **not** in
  ours. **Do you want it mirrored?** It is domainful, so I have not added it.
- **cad:** it needs a row in both registries. I have asked 7f for its generated yaml to mirror.
- **No seal asserts that the two registries agree.** Every check today is per registry.

## notice_id: built, and in 188

Built at `6d5c791f`, in master. The status route always carries `notice_id`:
- **a string:** the manifest's `doc_id`, written on the move into review;
- **`null`:** not known yet, a blank `doc_id`, or a pdf/xml row parked at `awaiting_origin`;
- **a duplicate:** reports its original's.

Under COALESCE, a later stage move never erases it. It is DISPLAY ONLY. Live, every row reads
`null` today: no row has moved to review since 188, and earlier rows have no backfill.

## Placed packets (untracked, in each owner's `sessions/`)

- **cortex-ui:** a correction.
  - xml passes the door from 188;
  - cad is still 400, so grey it out as "not yet accepted";
  - notice_id is built.
  - **Finding 2 qualifies "xml passes".** A §0 added after the roll tells cortex to treat xml
    like cad in the picker until you rule. Its send is unchanged.
- **doc-tools/lane/7f:**
  - cad needs a row in both registries;
  - the run_key answer;
  - 188 rolled without the poller.

## Not done

- **The five drops:** held, as ruled, for 7f's poller. Finding 2 does not touch them: they are
  pdf. Their sidecars and projection rows both need `content_kind: pcn`.
- **The ten s1000d drops:** I retried one (`c4a15a5f`) as the live retry. It timed out
  again at `attempt` 2, and so did my xml probe drop (`e708620e`). The other nine stay `failed / timeout` until Finding 2 is ruled.
- **No notice_id has been read as a string live.** That needs a pdf through to review.
