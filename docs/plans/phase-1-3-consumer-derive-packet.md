---
id:         phase-1-3-consumer-derive-packet
status:     closed
owner:      agent
blocked-on:
closed-by:  f8837bf
code-site:  agent_fleet/utils/artifact_provenance.py, agent_fleet/restate_analyst/review_starter.py, src/iagent/defs/extraction_review_sensor.py, src/iagent/gateway.py
repo:       invincible-agent
summary:    The consumer half of the 1.3 trust key - the starter DERIVES (format_fingerprint, pipeline_version) from the fetched artifact and the caller supplies only a pointer. Held together rather than staged because a half-derived conjunction inherits the weaker component's trust. Verified 2026-08-19: 29 tests green; test_artifact_provenance_derive.py pins BOTH halves server-derived plus the refuse-loudly and supervised-floor arms.
---

# PACKET — phase 1.3 consumer half: derive the trust key from the artifact

**Status: READY TO RUN, fresh window.** The producer half landed in doc-tools (`300b8e8`, `399b691`).
This is the larger diff, it touches the starter's admission path, and it closes the ceremony's last
engineering leg.

## Why this is held together rather than staged

`(format_fingerprint, pipeline_version)` is ONE trust key. Staging would produce a key where one
component is server-derived from the artifact and the other is caller-asserted — and **a
half-derived conjunction is not half-safe**: the whole key inherits the weaker component's trust,
because a caller who can assert the version still steers which table row the lookup hits.

## The interim state, named so nobody promotes against it

**doc-tools stamps `pipeline_version`; nothing reads it yet.** That is the write-only-artifact shape,
entered DELIBERATELY and briefly. The rule's force was never "write-only artifacts must not exist" —
it is *"a write-only artifact must not be mistaken for shipped policy."* A named, resolves-on-next-
commit interval is a construction stage; the trust-table finding was a write-only artifact BELIEVED
TO BE LOAD-BEARING.

Until this lands, the trust key's second axis is **degenerate**: `PIPELINE_VERSION` is unset on every
pod, so every key is `(fingerprint, "unset")` and leg 3's upgrade-invalidation guard is
discriminating on a dimension with one member. **Do not promote a format in this gap.**

## Item 0 — ENUMERATE BOTH CALLERS (read-only, first, no code)

The derive changes what the sensor's payload IS, so the caller enumeration applies again. The last
silent contract change at this seam cost days; this one is planned, so it gets the enumeration the
unplanned one didn't.

`start_review` has **two** production callers:
1. the extraction→review sensor (Dagster) via cortex-bff `POST /reviews`
2. **the router**, as a registered mesh verb — `mesh:proposeDisposition`, real endpoint
   (`agent_fleet/restate_analyst/main.py`, the `engine_a_propose_disposition` registration)

Answer three questions before writing anything:
- What does **each** caller supply today?
- Is the pointer (`subject_ref` / `request_key`) already present on **both** paths, or must it be
  added where absent? The derive is worthless on a path that cannot name its artifact.
- Does **anything** read `format_fingerprint` / `pipeline_version` as request fields before they are
  removed? (Grep both repos + the BFF model + the passthrough pin.)

Stop-and-report if the second caller cannot supply a pointer — that is a design question, not an
implementation detail.

### EXECUTED 2026-08-06 — the answer, and a defect found on the way

**Caller 1 (sensor)** sends: `notice_id`, `doc_type`, `categories`, `impacted_parts`,
`in_scope_mpns`, `doc_needs_review`, `review_state_source`, `extraction_warnings`, `domain`,
`request_key`, `trace_id`. ~~**The pointer is already there** (`request_key` = ETag + key). Nothing
to add.~~

> **CORRECTED 2026-08-06 — this answer was WRONG, and the derive was built on it.** `request_key` is
> `{epoch}{ETag}-{key}`: the artifact's **IDENTITY**, minted for ingress idempotency. It is not a
> **LOCATION** and cannot be fetched — the derive asked S3 for a key with an ETag glued to the front
> and refused every notice. There WAS something to add: `artifact_uri`, a full `s3://bucket/key`,
> now emitted by the sensor beside `request_key`, forwarded by the BFF, and consumed by the derive.
>
> The error is instructive because the question above asked exactly the right thing ("is the pointer
> already present?") and got a confident wrong answer: `request_key` is artifact-derived, moves with
> the content, and the code around it already called it "the artifact pointer". Presence was checked;
> **fetchability** was not. Species entry §6 of `cross-repo-string-contracts.md`; lesson in AGENTS.md
> ("KNOWING the rule did not prevent WRITING the defect").

**Caller 2 (router) cannot invoke `start_review` at all** — not "lacks a pointer", lacks
*everything*. The supervisor's generic dispatch payload is `user_query`, `user_persona`,
`answerer_persona`, `persona`, `domain`, `entitled_domains`, `user_email`, `dynamic_schema_map`,
`user_id`, `predicate_verb_iri`, `routed_verb_iri`, `resolved_instance_id`, `resolved_subject_uri`.
`start_review` hard-requires `notice_id`, `approver`, `impacted_parts`, `doc_type` — **none are
present**, and there is zero special-casing for `ReviewStarter` anywhere in the supervisor. It would
`KeyError` → 500. Matches the registration's own note: *"the router→start_review payload adapter is
the dispatch concern of a later window."*

So the derive proceeded: one live caller, and it already carries the pointer. **The requirement is
recorded for whoever builds that adapter: it MUST supply `artifact_uri`** — a full `s3://bucket/key`
(NOT `request_key`; see the correction above) — because the admission posture is derived from it and
a caller that cannot name its artifact cannot be admitted at all. A bare key is refused rather than
resolved against `ARTIFACT_BUCKET`: tolerance would make the artifact's location depend on two
runtimes agreeing on an ambient env var.

Consequence worth stating plainly: the router-laundering threat that motivated this ruling **was not
live** — a caller that can supply nothing cannot assert a fingerprint. The ruling still stands and is
cheaper now than after an adapter exists, but the urgency rested on a caller that cannot call.

#### FOUND, NOT FIXED — `mesh:proposeDisposition` is a dead-end menu entry

The verb is registered in the SPO menu with a **real** endpoint and no adapter, so a user who picks
"propose disposition" gets a 500. The registration comment says verbs *"wake per-endpoint as each
serving endpoint becomes real (registering a verb against a stub endpoint would recreate a dead-end
menu)"* — the endpoint is not a stub, the **adapter** is missing, so the rule was satisfied in
letter and violated in effect.

Filed rather than fixed: it is outside this packet, and the fix is the adapter itself (a design
piece), not a patch. Two honest options when it is taken up — build the adapter (and supply
`artifact_uri`), or **unregister the verb until the adapter exists**, which is what the wake-per-
endpoint rule actually intends.

## Item 1 — one fingerprint function, one home

`_format_fingerprint(review, key)` currently lives in the sensor and reads ONLY `review.json`
content (`header.mfr`, `doc_type`); the `key` argument is unused, so it is already artifact-pure.

Move it to `agent_fleet/utils/` — the ONE tree both runtimes carry (engine-a flattens to
`/app/utils/`; the Dagster image has `/app/agent_fleet/utils/`). Same relocation, same reason, as
`utils/service_identity.py` and `utils/trust_table.py`.

**Consumer test pinning that sensor and starter compute IDENTICALLY.** A drift there is a silent
demotion of every promoted format: fingerprints stop matching, everything falls to the supervised
floor, safe and invisible — the passthrough class one layer down.

## Item 2 — fetch by pointer, and the failure semantics are DECIDED HERE

ReviewStarter fetches `review.json` and derives both components. The fetch is a NEW FAILURE SURFACE
ON THE ADMISSION PATH, and its semantics are ruled at design time rather than discovered:

| failure | verdict |
|---|---|
| bucket unreachable | **REFUSE, loudly** |
| object absent | **REFUSE, loudly** |
| unparseable | **REFUSE, loudly** |
| readable but schema-alien | **REFUSE, loudly** |
| well-formed, `pipeline_version` field absent | **supervised floor**, `admitted_by: policy-default-missing-provenance` |

**Fetch-or-parse failure is a REFUSAL, not a floor-fall.** The supervised floor is the honest
degradation for *provenance missing from a well-formed artifact*. It is the WRONG answer for
*couldn't read the artifact at all*, because floor-falling on a fetch failure means an S3 outage
silently converts every admission to supervised — safe, invisible, and indistinguishable from
policy. Same distinction as the LEG 0 probe's `None`-vs-`[]`: **an outage must not read as a healthy
answer.** The sensor's classify-refusal-as-failed-run path already exists for exactly this.

Both admission variants stay legible in `admitted_by`:
- `policy-default-missing-provenance` — well-formed artifact, no version stamped (the back-corpus)
- `policy-default-missing-facts` — the sibling from the passthrough finding, still open on the board

## Item 3 — flip the passthrough pin to the POINTER

The sensor stops sending `format_fingerprint` / `pipeline_version` entirely; they become derived.
`test_review_payload_passthrough` must then protect the **pointer** instead of the two facts —
otherwise the pin guards fields nothing sends and stops guarding the one thing that matters.

This shrinks the client-suppliable surface to `subject_ref` alone: **a caller can lie about exactly
one thing — WHICH artifact — and the artifact determines everything else.** That collapses the trust
question to "can the caller read that artifact," an entitlement question the system already knows
how to ask.

## Item 3b — RIDER: the registry-startup invariant (pulled forward, ruled 2026-08-05)

**Not a silence-arc citizen any more — it rides THIS window's deploy.** The argument for pulling it
forward is that the ceremony's aftermath is the first live autonomous traffic, and both exhibit
classes are deploy-time failures that would surface *during* that traffic as routing mysteries. An
invariant whose whole purpose is preventing misattributed witness failures should be standing
BEFORE the highest-stakes witness this system runs.

Both exhibits are witnessed, which is why it is well-specified rather than speculative:
1. **definitions present in the image, directory empty** — the original exhibit.
2. **service present in the image, absent from Restate's registry** — `AutonomousReview` shipped in
   the image and was still missing from `deployments list`; every `workflow_send` would have failed
   as service-not-found, and the 1.3 witness would have **measured a registration gap while looking
   like a routing failure.** That misattribution is the invariant's justification, on file.

The class, one line: **shipped is not registered — an artifact arriving in the pod proves nothing
about the runtime knowing it exists.**

Assert BOTH, fail LOUD:
- expected workflow definitions loadable **by name** from the registry at startup
- expected Restate services present in `deployments list` (startup check or deploy step)

It is small — an expected-set assertion plus a list check — and it guards the exact roll this packet
performs, since the derive rolls the starter anyway. Fix when it trips:
`restate deployments register <endpoint> --force`.

## Item 4 — the deploy piece (NOT code)

**ReviewStarter needs artifact-bucket read access** — new, read-only, scoped. Goes on the
work-translation list beside the email-claim item, because the work deploy needs the same access
under whatever its bucket story is.

If that access proves organizationally hard at work, the **signature** option is the fallback
(doc-tools signs the fingerprint at emission) — but design for DERIVE first, because it removes a
trust decision rather than securing one, and signing inherits key management plus replay-binding
(an old signature must not replay onto a new notice).

## Item 5 — re-witness legs 2 and 3 on the derived key

Same four-leg instrument, now measuring a key that means what it says:
- **leg 2** — fixture-promote against a REAL artifact's derived `(fingerprint, version)`; watch
  `AutonomousReview` start.
- **leg 3** — fixture whose promoted version mismatches the artifact's STAMPED version; watch the
  supervised floor hold. This is the first time that guard is exercised against a version that
  actually describes the producer.

Instrument discipline, unchanged and non-negotiable: route read from the **Restate journal**, table
hash read back from the **pod** before every drive, fixture **settled off** the running system
afterwards with a hash readback. And roll **both** services digest-checked — the leg-1 lesson: a
one-service roll of a two-service fact change produced a correct route for the wrong reason.

## When this lands

The ceremony's checklist is three legs, all green-or-awaiting-signature:
1. grant landed (ratification)
2. **fingerprint trust closed** (this packet)
3. deny→allow witnessed for the token-proven identity — before-picture already on file
   (`caller 'svc:review-starter' is not authorized …`)

And the key under the signature will finally be telling the truth on both axes.
