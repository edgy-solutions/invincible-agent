# Refusal routing — a refused notice is a TASK, not (only) a failed run

**Status:** BUILT 2026-07-30 (design filed 2026-07-29). Raised from live operation: three notices hit
`REVIEW_STATE_UNSOURCED` at work and each one **ceased to exist** for everyone whose job is processing
notices. The refusal was real; the audience was wrong.

**As built:** `classify_start_review` returns `refused_content` / `refused_systemic`; content refusals
POST to a new generic `/triage_tasks` (capability `mesh:fileTriageTask`, deny-by-default) and the run
COMPLETES; systemic refusals still fail the run. Sealed in `tests/test_refusal_routing.py`, including
the two traps that would have made it a silent no-op — see the amendments below.

## The gap

The extraction→review sensor surfaces every refusal as a **failed Dagster run**. That is correct for
*some* refusals and wrong for others, and the design does not distinguish them:

| refusal | what it is a statement about | who can act |
|---|---|---|
| BFF unreachable, token mint failed, 401/502 | the **pipeline** | data engineer ✅ Dagster |
| `RULES_NOT_FOUND`, `RULESET_INVALID` | the **deployment** (affects ALL notices) | ops ✅ Dagster |
| `REVIEW_STATE_UNSOURCED`, `NO_PARTS_EXTRACTED`, `NO_AFFECTED_PARTS` | **this notice** | the sustainment reviewer ❌ *never told* |

A vendor's PCN arrives, fails content validation, and the only trace is a red run in a tool the
reviewer does not open, phrased in pipeline vocabulary they do not speak. **This is the
invisible-dead-notice failure the sensor design explicitly rejected polling to avoid — reintroduced
through the error path.** Diodes PCN 2683 made it vivid: the extraction honestly reported "I struggled
with this document" and that sentence was visible only to the one persona who cannot act on it.

Note this is NOT fixed by the warning-banner work (`8a3a9b0`). That thread carries warnings for reviews
that *start*. A refused notice never becomes a review, so it has no card to carry a banner.

## The shape: route by WHO OWNS THE ANSWER

The mesh already owns the grammar for "a human in a specific role must look at this" — `register_task`
+ an audience. A content-refused notice is exactly that:

> **Notice PCN-2683 could not be prepared for review.**
> The extraction did not produce any affected parts (2/5 table crops failed).
> `[Re-drive]` `[Acknowledge]`

Materialized to the owning audience (`pcn_disposition:<compartment>`, or a `triage:<compartment>`
sibling), it lands in the timeline of the people who own the answer, with the refusal reason threaded
as provenance exactly as the degradation warnings now are.

**Precedent, not new machinery.** This is the unresolved-subject dispatch ruling applied to a different
unprocessable input: *open a task carrying enough context to re-link retroactively; never an orphan.*
Everything that already holds keeps holding — deny-by-default, audience-scoped recipients, the refusal
reason as auditable provenance, `NoEntitledRecipients` if the audience is empty.

## Boundaries (so this lands right-sized)

1. **Not every refusal deserves a task.** `RULES_NOT_FOUND` is a deployment condition affecting *every*
   notice; fifty identical triage tasks is worse than one loud Dagster failure. The split:
   **per-notice content problem → task to the owning audience; systemic/config problem → ops channel,
   once.** The status codes already encode this distinction — it just isn't acted on.
2. **Dagster's signal gets cleaner too.** Content refusals should record as **completed-with-refusal**,
   not failed. Reserving `failed` for infrastructure stops content problems from polluting the
   pipeline's health signal — an operational win independent of the task work.
3. **Retry semantics need one decision.** When the underlying issue is fixed (crops re-extracted, the
   form-field feature lands), does the triage task offer **re-drive** (re-fire the sensor for that
   notice — the run_key/`doc_id` idempotency already supports it) or does the human re-drop the
   document? **Recommend re-drive**: better UX, and it is one button over machinery that exists.
4. **Do not duplicate.** A notice refused twice must not mint two triage tasks.

   > **AMENDED AT BUILD TIME (2026-07-30).** This clause originally said *"key the task on `doc_id`
   > the way the sensor keys its runs."* **The sensor no longer keys its runs that way, and the
   > reason is this exact hazard.** `doc_id` is LLM-extracted, and when the header pass degrades it
   > falls back to a value that can be **identical across documents** — every PDF in one inbox
   > derived `"inbound"` (live 2026-07-30), and Dagster's run-key dedup silently ate all but the
   > first. Keying triage on it would collapse N dead notices into one task: the same silent loss,
   > reproduced *inside the cure*. Triage is keyed on the **artifact** (`sha1(source_key)`), unique
   > by construction, matching the sensor's ETag+Key run identity. `doc_id` still travels as
   > **display** — a human recognizes "PCN-2683", not a hash. See `feedback_sensor_cursor_contract`:
   > *a model-derived value must never key deterministic machinery.*
   >
   > Generalized: this design and the sensor cursor were **coupled without either document saying
   > so**. Two artifacts naming the same key had to move together, and only one of them knew why.

## Two traps found while building (neither was in the design)

1. **The status is not where the design assumed it was.** A 200 carries `status` at the top level, but
   a refusal is re-raised by the BFF as `HTTPException(detail=<engine body>)` and FastAPI serializes
   that as `{"detail": {...}}`. Reading only the top level sees `None` for **every** refusal — which
   was harmless while all refusals shared one fate, and silently wrong the instant routing depends on
   it. Everything would have classified systemic: the fix would ship, pass a smoke test, and change
   nothing for the reviewer. Sealed by `test_status_is_read_through_the_fastapi_detail_wrapper`, and
   mutation-proven (restoring the naive read fails 5 tests).
2. **The routing call is itself a place notices can die.** The triage POST can be denied (403, missing
   capability grant), refused (422, zero entitled recipients in the audience), or time out. Swallowing
   any of those would hide the notice behind a **green** run — strictly worse than the red run being
   replaced. So every failure of the routing call **raises**: refusals degrade to the old bad
   behaviour *loudly*, never to silence. This makes `mesh:fileTriageTask` load-bearing for
   **visibility**, not just permission — an unseeded grant quietly reverts the fix, which is why it
   ships in the same window.

## Why this is the right altitude

The alternative — "make the refusals rarer" — is what the last three fixes did (the count-parse
guards, attestation, the warning thread), and it is worth doing, but it cannot be sufficient: some
notices will always be unprocessable, and the question *"what happens to a notice we cannot prepare?"*
deserves a designed answer rather than a default one. Right now the default answer is **silence
addressed to the wrong person**.

## Wake / sequencing

Build after the vision-timeout work settles (that work reduces the *volume* of content refusals, which
changes how noisy this channel will be). Reassess the triage-audience choice then: if refusals are rare,
the reviewer audience is right; if they stay common, a dedicated `triage:` audience keeps the review
queue clean. Either way the routing decision — **content → owner, systemic → ops** — is the durable
part.

**Resolved as built.** The vision-timeout work landed first, so refusals should now be rare: triage
defaults to the domain's own review audience (`pcn_disposition:<domain>`) — the people already
responsible for these notices, and no new grant to seed. `REVIEW_TRIAGE_AUDIENCE` switches it to a
dedicated `triage:<compartment>` audience if the queue gets noisy; that audience would need a
`task_grants.yaml` entry first, and until it has one, `NoEntitledRecipients` → 422 → failed run
(loud, not silent). The switch condition is recorded next to the env var, so it stays a decision
rather than a forgotten default.

## NAMED WAKE — refusal routing relocates when the ingress goes async

**Trigger: when workflow selection lands (ADR-0034 Phase 2 / the trust lifecycle's autonomous
path).** Not a someday — a scheduled change with a named beneficiary.

Today the BFF calls `start_review` **synchronously** and the sensor classifies the response, which
is what makes the routing in this document possible: the sensor *sees* `REVIEW_STATE_UNSOURCED`
and files the triage task. The autonomous path cannot work that way — there is no human latency to
wait on, the sensor fire-and-forgets into a definition, and the ingress must be **async-shaped**.
At that point:

1. The BFF `send`s and returns 202; nobody holds a connection.
2. **The refusal routing MOVES INTO the Restate handler** — the decider that knows the refusal
   routes it, which is where it belongs anyway, and it is where the trust gate will already live.
3. This file's seal is rewritten against the two-definition shape.

**MEASURED BASELINE (2026-07-31), so the trigger is observable rather than anecdotal.** PCN-2683
composed **402 parts in 173s** against a 300s budget — comfortably inside, and the ceiling is
**content-shaped**: composition resolves a subject, checks entitlement and evaluates the ruleset
*per part*, so the cost scales with the notice. At ~0.43 s/part, the budget is exhausted somewhere
around **700 parts**, and 402-part notices are already routine.

> **Second trigger for the async wake: composition time TRENDING toward the budget** — not "someone
> hits a timeout". Watch the ratio, not the incident. The first 900-part notice, or a work-cluster
> latency profile slower than sandbox's, converts "inside the budget" into "*was* inside the
> budget" — and a ceiling discovered by breaching it is the failure this baseline exists to avoid.

**Why it is deliberately NOT done now.** The synchronous contract is not *wrong* — with the ingress
idempotency key (landed 2026-07-30) the 300s hold is a bounded wait on a **deduplicated**
invocation: ugly, but honest and safe. Doing the async conversion today would mean designing the
ingress contract **twice** — once against the current single-workflow shape, once when the gate
starts selecting between definitions — and rewriting a seal the day after it bit its first
mutation. Doing it *then* is one design.

## Remaining

- **UI:** the `extraction_refusal` task kind renders with the default queue treatment. It carries
  title/summary/subject_ref like any task, so it is visible and actionable — but the design's
  `[Re-drive]` / `[Acknowledge]` affordances are not built. **Re-drive already works** without them:
  re-uploading or re-extracting the document writes a new `review.json`, which the sensor sees by
  arrival time and fires under a new content-addressed run key.
- **Live seal:** drop one of the three known-refusing PDFs and witness the task land in a reviewer's
  queue. The offline seal covers routing and the fail-loud behaviour; it does not prove the audience
  resolves to a real human in a real cluster — that needs the composed path.
