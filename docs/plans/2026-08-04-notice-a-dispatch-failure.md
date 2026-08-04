# Notice A — the approval landed, the dispatches died 160ms later (root cause + rulings)

**The first human-driven approval through the definition-driven runner found the one defect no
machine-driven witness could see.** Filed before any fix, with the instrument corrections in the
same document as the finding.

## What happened

Alice approved `M32-A-WITNESS` at **21:40:38.552Z** through the UI → `/act`. The workflow resumed,
fanned out two `DispatchItem` invocations, and returned:

```json
{"status": "DISPATCHED", "count": 2,
 "dispatched_keys": ["M32-A-WITNESS:NSR01L30NXT5G", "M32-A-WITNESS:MPN-NEEDSREVIEW"]}
```

Both dispatches **failed 160–280ms later**:

```
M32-A-WITNESS:NSR01L30NXT5G    failure  [403] access denied (401) registering pcn dispatch task
                                        (audience 'qualification') -> cortex-bff:8090;
                                        failing (state released)
M32-A-WITNESS:MPN-NEEDSREVIEW  failure  [403] access denied (401) ... (audience 'procurement')
M32-B-SEAL / M32-C-KILLSEAL    success  (both parts, both notices)
```

No task rows, no `dispatched` markers, no graph state. The projection still reads `approved`.

## ROOT CAUSE — a credential captured at review start, used after human latency

The review's `user_jwt` is captured when the review STARTS and stored in workflow state; the
dispatch driver reuses it to mint the per-part task at APPROVAL time. A grouped review is
**designed to suspend for human latency** — hours, days, a weekend. So a token captured at start is
*routinely* stale when the approval arrives. A began ~20:0x and was approved at 21:40 — roughly
ninety minutes. The token had expired; cortex-bff returned 401; the driver mapped it to
TerminalError and released state.

**Every layer behaved correctly.** 401 → fail-and-release is the sealed rule (a persistent auth
denial is a FAILURE that releases, never a transient that parks). Nothing is corrupt, nothing
partially applied.

### Why no seal caught it — the suite's LATENCY BLIND SPOT
B and C succeeded because seals resolve in **minutes**. This defect only exists at **human speed**.
Every automated witness in the suite resolves at machine latency, so the suite is *structurally*
incapable of seeing it. That is a class, not an oversight: **a defect whose trigger is elapsed time
cannot be found by witnesses that never elapse.**

## RULING 1 — the fix is NOT a longer-lived credential

The runbook's standing follow-up says *"a long-lived-enough service credential is what keeps it from
going stale."* **That is the wrong fix and this document supersedes it.** Lifetime-tuning to outlast
human reviewers converges on effectively unbounded tokens stored durably in journals — a
credential-at-rest surface that grows to match the slowest reviewer.

**The fix is MINT AT USE, under the ACTING identity.** The dispatch mint happens *after* an
authorized human decision has resolved the promise. The actor at that moment is the pipeline
completing an approved workflow — so the mint runs under `svc:review-starter`'s own identity via a
client-credentials mint at dispatch time. Fresh by construction; no stored credential; no lifetime
knob.

**The conflation that caused the bug:** the stored `user_jwt` was carrying two different facts at
once — **provenance** (who approved; belongs in the decision record) and **authorization to execute
effects** (the pipeline's own entitlement). Those are separate, and the token's legitimate job ends
where the human's action ends. Threading it into post-decision machinery is what broke.

**Feasibility confirmed, not assumed:** `mint_service_token()` already exists and is proven
(`src/iagent/defs/extraction_review_sensor.py:401`, the sensor's per-run mint), and engine-a already
carries `REVIEW_STARTER_CLIENT_ID`, `REVIEW_STARTER_CLIENT_SECRET` and `KEYCLOAK_REALM_URL` in its
environment — verified on the running pod. The helper lives in the sensor module, so the port is a
code move, **not a deploy/config change.**

## RULING 2 — the failure gets an EMISSION, not only a probe

A detection join is the backstop; this failure deserves surfacing at the moment it happens. **A
dispatch that terminally fails after an approval should mint a triage row** — the
`extraction_refusal` shape already exists and is proven, and *"approved but effects failed"* is
exactly a refusal one stage later.

The invariant currently broken is the most consequential dual-surface lie yet: **a review whose row
says `approved` while its effects silently died — a human believes their decision executed, and
nothing anywhere disagrees with them.** The only record was a Restate journal nobody reads.

## RULING 3 — rename the status in the same commit

`DISPATCHED` was returned by a workflow whose two dispatches both failed within 160ms. The
demonstration is complete; no further argument is needed.

- Honest return for fire-and-forget emission: **`RESOLVED`** with **`dispatch_enqueued: 2`**.
- A stronger claim would require the workflow to AWAIT outcomes — a design change nobody has ordered.

**Rule (general):** a status field asserts what its author WITNESSED. `ctx.object_send` is
fire-and-forget by construction, so the workflow *cannot* know delivery — `DISPATCHED` was journaled
intent wearing an effect's name. Intent-only statuses get renamed, or they never get cited as proof.
Same class as the M2 upload reporting `[OK]` while every ingest failed.

## Notice A's repair is CLEAN — this is not damage

- **Alice's approval is durable, real, and correctly recorded.** The human decision does not need to
  be re-asked.
- **Fail-and-release did exactly its job:** state was released, so **no dedup markers exist**. Once
  the identity fix lands, re-firing A's two dispatches mints cleanly with **no double-dispatch
  hazard**.

That is the first live claim on what fail-and-release was purchased for: the failure mode it buys is
*safe to retry*.

## INSTRUMENT CORRECTIONS — three of my zeros measured the probe, not the system

Filed beside the finding so nobody re-cites them:

1. **"0 `DispatchItem` invocations, ever."** WRONG, and it was my strongest-sounding evidence.
   `restate invocations list` shows **live** invocations only. `sys_invocation_status` holds
   completed and failed ones — where both of A's dispatches sit, with their failure text.
2. **"0 graph triples for the parts."** Non-discriminating. B and C wrote none either
   (`state_written: false`, `subject_unresolved: true`), so graph-state absence never separated
   success from failure.
3. **`sys_idempotency` 0 rows.** Non-discriminating — empty for B and C too.

Only two instruments discriminated: the **VirtualObject `dispatched` markers** and
**`sys_invocation_status.completion_failure`**. The uniform-zero rule held: four zeros with no
positive control was measuring the instrument, and the B/C control is what broke the tie.

## Test gap to close

**A seal that resolves a review with a deliberately expired or near-expiry token** — injecting the
staleness instead of waiting for it. Same move as the kill-seal: don't wait for the failure
condition, manufacture it under witness. Turns "ninety minutes of wall clock" into a fixture.

## Parked — its own ledger item, not part of this fix

A's two parts routed to **different audiences**: `NSR01L30NXT5G` → `qualification`,
`MPN-NEEDSREVIEW` → `procurement`. That is per-part routing doing something interesting and
unexamined. It did not cause this failure (both died at auth, before audience resolution mattered)
and it must not ride along in a JWT fix.

## SERIAL FAILURES MASK — re-verify the whole path after a fix, not just past the repaired step

The 401 hid a SECOND, independent defect. Alice dispositioned `MPN-NEEDSREVIEW` as last-time-buy;
`dispatchLTB` routes to the `procurement` audience — which had **never been granted in sandbox** and
resolved to `[]`. Had the credential been valid, that dispatch would have died on
`NoEntitledRecipients` instead. Fixing the first failure REVEALED the second; nothing found it while
the first was in the way.

**The rule (operational sibling of the probe checklist): after any fix, walk the remaining path's
PRECONDITIONS before executing it.** Concretely here: read the audience resolution *before* the
re-fire, rather than firing and watching it fail. That is the false-RED discipline running
**prospectively** — do not manufacture a red you can already see. Each `idempotency_key` is a finite
identity budget; burning one to witness a predictable failure spends evidence on a fact already in
hand.

## CREDENTIAL-AT-REST IS A DISCLOSURE CLASS, NOT ONLY A STALENESS CLASS

The rule was born abstract — *a durable journal is a time machine* — and died literal. Recovering the
original dispatch payloads for the re-fire meant reading the Restate journal, and **the expired JWT
was still sitting in it, fully legible, an hour after it died** (`sys_journal`, `entry_json`, the
`Input` command). Recoverable by exactly the read performed here, by anyone with journal access.

So: **journals are readable state with a retention window. Anything secret-shaped that ever touches a
journaled payload is DISCLOSED for that window regardless of its expiry.** Expiry limits what the
credential can DO; it does nothing about what the credential REVEALS. The guard asserting `user_jwt`
cannot return to the payload therefore protects a disclosure class, not merely a staleness class —
and that is the stronger reason it must stay.

## Order — EXECUTED 2026-08-04

1. ~~**File**~~ (this document) — `13d98b3`
2. ~~**Fix** — mint-at-use in the dispatch driver~~ — `0c222c3`
3. ~~**Re-fire** A's two dispatches~~ — **DONE, two-of-two**:
   - engine-a rolled; digest CHANGED (`7fa91164…` ≠ `b21c7d47…`), fix confirmed in the RUNNING image,
     live mint returning a real token — verified before touching A.
   - Per the ruling: **purge the spent failed invocations, never mint a new key.** The
     `notice:mpn` key IS the exactly-once identity; a variant key would put two identities in the
     space for one real dispatch. Purged with reason, re-fired under the SAME key, both parts.
   - `NSR01L30NXT5G` → `qualification` → bob · `MPN-NEEDSREVIEW` → `procurement` → bob;
     both `completion_result: success`, both `dispatched` markers present.
   - Blocked mid-way by the masked defect above; `procurement` granted through the rails
     (first live LTB disposition) and resolution verified non-empty BEFORE the second re-fire.
4. **Follow-up commit** — the triage-mint on terminal post-approval dispatch failure + the status rename
5. **Seal** — expired-token injection into the suite

## PARKED ITEM RESOLVED — the two-audience split was correct all along

A's parts routed to different audiences because **alice dispositioned them differently**:
`dispatchQualification` → `qualification`, `dispatchLTB` → `procurement`. Per-part routing executing
the dispatch design, not an anomaly. The audience was ungranted only because no live decision had
ever routed there — the same wake-per-need shape as the disposition verbs that waited per-endpoint.

---

**The epitaph:** the first human-driven approval through the definition-driven runner found the one
bug no machine-driven witness could — which is the best available argument that the demo needed a
human in it.
