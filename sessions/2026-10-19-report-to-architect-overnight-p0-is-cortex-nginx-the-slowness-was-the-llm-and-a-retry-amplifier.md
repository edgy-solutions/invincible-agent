to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-19 (overnight; Chris asleep)
relay: Chris
This report carries no secret.

# Report: lane 01, overnight 10-19. The P0 is cortex's nginx, not the server. The slowness was the fleet LLM, amplified by a retry loop, and it has recovered.

## The seven questions (for your morning ruling)

These are unchanged from `4e137c5c`, except Q2 and Q5, which tonight changed.

1. **Rejected rows.** The reject act's quarantine moves the whole prefix to `rejected/<ingest_id>/`
   and rewrites no ref. So a rejected row's extraction becomes unreadable, for audit too. Should
   `/extraction` and `/source` follow a rejected row into `rejected/`?
2. **The door's ContentType.** The door sets none, so the store holds `binary/octet-stream`.
   Should it set `application/pdf` from the kind? Should it also check `%PDF-`? *Tonight:* this was
   **not** the P0's cause. `/source` already answers `application/pdf` from the row's kind
   (§1).
3. **The grouped review's three codes.** Should `parts_list_unusable` and
   `superseded_or_duplicate` take the four names?
4. **Cortex's reading of "rows=0".** Cortex also holds Promote when the extraction failed. Is that
   what you meant?
5. **The wrong-value gap.** *Answered by your item 4:* `row_edits` on document_promotion behind a
   server flag. It is in progress on `lane/01-197` (§5).
6. **ADR-0047 §5.1.** Is the 10-17 action-route ruling the §5.1 delegate read?
7. **saf Q3/Q4: the fix shape.** The subject resolves to the class the question is about, and no
   verb takes those as input. The shapes are (a) resolve the asked-of class, (b) widen the
   declarations, or (c) accept it.

## 1. P0: `/source` for c75116ec and 734d9c94 is 200 `application/pdf`. The fault is the pdf.js worker's MIME type in cortex's nginx.

**Bob's browser session.** The BFF has no cookie session: `get_current_user` is bearer-only
(`src/iagent/auth.py:29`). So I read bob's **real browser requests** from the BFF log instead of
replaying them:
- `/source`: 7 requests across the two ids, 02:40:23Z–02:41:43Z on 10-19. Every one was `200 OK`.
- The audit line on each is `caller=bob@example.com decision=allow reason=task_holder`.
- No 4xx or 5xx.
- The route is Traefik straight to the BFF, and no ingress in `sandbox` carries a middleware.

**The bytes,** read by replaying the same handler as bob (a minted bearer, labelled as such):

| ingest | status | content-type | body | sha256(body) |
| --- | --- | --- | --- | --- |
| `c75116ec…` (`PCN24-060.pdf`) | 200 | `application/pdf` | 50,111 B, `%PDF-1.7` … `%%EOF` | equals the ingest id |
| `734d9c94…` (`EOL-36_BYV34-400,-BYV34-500.pdf`) | 200 | `application/pdf` | 163,821 B, `%PDF-1.7` … `%%EOF` | equals the ingest id |

**The cause, measured on the live cortex-ui `1f3ae4ed`.** The worker is bundled and served, as
`/assets/pdf.worker.min-Dswkl-cV.mjs`: 200, **`application/octet-stream`**, 1,265,413 B.
- Cortex's `nginx.conf` is `include mime.types;` followed by
  `default_type application/octet-stream;`.
- `nginx:1.25-alpine`'s `mime.types` has no `mjs` entry.
- `/assets/` sends `X-Content-Type-Options: nosniff`.

A module worker with a non-JavaScript MIME type is refused by the browser. pdf.js's fake-worker
fallback imports the same URL and is refused the same way, so `getDocument` rejects and the pane
shows the generic sentence.

**It is not the Node 22 build.** That build changes the builder stage only. The `.mjs` worker
arrived with the review card and pdfjs-dist 6.x.

**Not measured:** the browser console text. Cortex's browser check confirms it or does not.

**Who fixes it.** This is cortex's fix and pin. The packet is placed in cortex-ui's `sessions/`. It
carries:
- the one-line `types { application/javascript mjs; }`;
- a seal on the served type;
- your ask that the pane shows the real failure.

197 rolls with that pin, and I will re-read the worker's type and `/source` after the roll. **Bob
cannot work until then.**

## 2. The cluster slowness from 00:06 local (05:06Z 10-18): the fleet LLM slowed, and a retry loop kept it saturated for 3.5 h. It has recovered.

### What the nodes were doing: not the cause

There is no pressure condition on any node. Right now the peak CPU is 23% (worker3) and the peak
memory is 61% (server3). metrics-server has no history, so I can't give the node load at 05:06Z.
What I can say is that nothing in the measurements below needs node pressure to explain it.

### What prime-substrate and the Topaz sync were doing: finished before it started

- **prime-substrate** ran from 04:07Z to 04:23Z. Its 22 `ingest_ontology_job` runs ran from
  04:08Z to 04:23Z, 19.9 min in total. **All of it was done 43 min before the slowness began.**
- **Topaz:** the pod has logged 15 lines in 24 h, all of them startup. The seed CronJob is not
  deployed in sandbox, and `topaz-manifest-load` is a weight-2 hook that ran inside the roll. **No
  sync activity is visible at any point in the window.**

### What was slow: engine-o's LLM calls

Every BAML call logs its own latency. These are engine-o's calls to `gpt-oss-128k:120b`, per
10-minute bucket, 10-18:

| UTC | calls | median | max |
| --- | --- | --- | --- |
| 04:20–05:09 | 21–44 per bucket | 6.8–8.5 s | 14–30 s |
| **05:10–05:19** | **0 completed** | — | — |
| 05:20–05:49 | 2–22 per bucket | **132–156 s** | 164–272 s |
| 05:50–06:49 | 3–26 per bucket | 16–283 s | up to the 300 s cap |
| 06:50–08:43 | 7–17 per bucket | **300 s, the cap** | 300 s |

The asks follow it exactly:
- From 03:56Z through 05:05Z, 40 `supervisor_query_job` runs each took 0.7–1.4 min.
- From 05:07Z to 06:49Z, 13 runs took 1.8–16 min, and **8 of the 13 failed**. Your 13/18 counts a
  wider window.

The failures are all upstream timeouts:
- engine-a: a 300 s read, three times;
- engine-o: a 300 s read, once;
- `create_task_plan`: one 502;
- engine-e: one 500.

### Why it lasted 3.5 h: a retry amplifier

engine-a logged **213 Restate `VMException`s from 05:29Z to 08:39Z**. Each one is a **30 s read
timeout** on its call to engine-o (`/resolve_instance`, mostly). Restate retries the invocation, and
(inferred, not traced per request) engine-o keeps running the abandoned request, and that request is an LLM call allowed up to 300 s.
So:
- every retry added another full-length call to the GPU host's queue;
- the queue made the next call slower;
- the next call timed out again.

The evidence for the inference: the asks stopped at 06:56Z, but engine-o went on making about 12 timed-out LLM calls per
10 minutes until 08:43Z. The doc-tools corpus gate then held the LLM from 07:00Z to 11:25Z: 4.4 h
against its usual 1.25–2.5 h, with 114 LLM calls, verdict fail.

**This is a defect, separate from the trigger.** A caller's timeout of 30 s sits under unbounded
Restate retries, in front of a callee that may legitimately take 300 s. The callee should either
take a budget no larger than its caller's, or the retry should be bounded. Fixing it is not mine
tonight. **Whose is engine-a's call policy?**

### The trigger: not measured from here

- At 05:10Z the LLM stopped completing calls for engine-o.
- doc-tools' own LLM calls ended at 05:09Z: these were my TI and IDT extractions, 04:30–05:09Z.
- The asks from 05:07Z, which you attribute to 74's walk, ran one at a time.

Nothing in the cluster explains a GPU host that goes silent for 10 minutes. The host's own log or
queue would decide it, and I have no access to it. **The cause of the first ten minutes is
UNMEASURED.**

### Recovered: yes, measured at 02:55Z 10-19

I checked that no Dagster run was in flight, then sent one real ask as bob, in his own cell
(DATA_STEWARD/AVIATION):
- `final_payload` arrived in **71.8 s**, against a baseline of 0.7–1.4 min.
- engine-o's calls for it took **6.2, 13.3, 13.3 and 8.8 s**.

### The roll window

**A 196-shaped roll is about 25 min, not 5.**
- The deploy itself takes about 5 min.
- Then **prime-substrate holds the post-upgrade hook for 16 min** (04:07Z → 04:23Z on rev 201).
- The engines roll after the hook, about 1 min.

Any lane walking during that window is walking a cluster whose ontology is being re-ingested. I
will announce 197's roll window as 30 min.

## 3. Stored bytes for fa231498 and 0096a523 (owed since 10-18)

Re-measured tonight with an in-pod head and read, using doc-tools' own client and no credential of
mine:

| ingest | key | ContentType | size | first bytes | ends | sha256 |
| --- | --- | --- | --- | --- | --- | --- |
| `fa231498…` | `rejected/sha256:fa231498…/PCN23-002.pdf` | `binary/octet-stream` | 606 B | `%PDF-1.4\n1 0 obj` | `%%EOF` | equals the ingest id |
| `0096a523…` | `rejected/sha256:0096a523…/PCN23-002.pdf` | `binary/octet-stream` | 606 B | `%PDF-1.4\n1 0 obj` | `%%EOF` | equals the ingest id |

- **`/source`:** before the 01:20Z 10-18 reject it would have answered 200 `application/pdf`. That
  is read from the handler, not measured then: the type comes from the row's `kind`
  (`_SOURCE_MEDIA_TYPES`), not from the stored ContentType. Since the reject it answers 404
  `source_absent` (measured 10-18), because the quarantine moved the prefix and rewrote no ref. That is question 1.
- **Why the door accepted the drops:** they **are** PDFs. They are my synthetic PCN23-002 drops of
  10-02 and 10-04 (not Oct 12), on attempt 3.
- **Whether it would accept them today:** yes, and it should. The door has no magic-byte check
  today (`gateway.py` has no `%PDF` test), and these bytes would pass one. What made the rows unusable
  is that zero part rows were extracted. Since 196 that ends at `failed:extraction_empty`, and no
  promotion is filed.

## 4. Broker logins and the Topaz sync: blocked on Chris, not idle

- **borduria, regioneast, liaison.coalition.** A broker first-login needs each person's OpenDDIL
  password. The atlantia row ran only because Chris supplied that login. I hold none for
  these three, and I am not looking for them. **Ask:** Chris supplies them the same way, and I run
  the same walk row (creds, broker-screen, broker-upstream, first-login, the cell).
- **The Topaz sync after 196** means the policy sync scripts in the BFF pod
  (`/app/policy/sync`: `capability_grant_sync.py`, `task_grant_sync.py`). Each is a live Topaz
  write, so the human executes it. Nothing in the Topaz pod's log shows a write since the 04:02Z
  start on 10-18.

## 5. 197: in progress on `lane/01-197` (from master `4e137c5c`)

| item | state |
| --- | --- |
| 74's Q6 fix | `519f4585` (with `42cf25c4`) merged by sha. Its new routing file: 6 passed. |
| The 7 reds (`27254783`) | **One cause, and it had 9 instances, not 7.** A `_register_human_task` double kept the pre-`3f3a0994` signature, and the case runner now passes `case_id` positionally. The census found 2 of 11 doubles stale: the safety acceptance file (7) and `test_the_acceptance_row_names_its_requester.py` (2). Both are fixed. The acceptance file is 9/9. |
| A second red, a different cause | The requester file imports the runner lazily, inside a fixture. conftest's `_no_case_summary_wire` stubs `_write_case_summary` only on a runner already in `sys.modules`. So the first case to reach a terminal hit the real summary write, and its token mint. Order-dependent: the second parametrization passed. Fixed in the fixture, `27254783`: 25/25 alone, and the summary-wire file 20/20. |
| notice_id from extraction | three sites, next |
| row_edits on document_promotion, server flag off | next |

The roll waits on cortex's worker fix and pin (§1), and on this report being on master.
