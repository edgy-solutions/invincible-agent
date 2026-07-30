# Refusal routing — a refused notice is a TASK, not (only) a failed run

**Status:** DESIGN (filed 2026-07-29, not built). Raised from live operation: three notices hit
`REVIEW_STATE_UNSOURCED` at work and each one **ceased to exist** for everyone whose job is processing
notices. The refusal was real; the audience was wrong.

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
4. **Do not duplicate.** A notice refused twice must not mint two triage tasks — key the task on
   `doc_id` the way the sensor keys its runs.

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
