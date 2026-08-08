# IDENTITY vs LOCATION — the `artifact_uri` repair, witnessed. CLOSED.

The admission posture is derived from the artifact's **LOCATION** (`artifact_uri`, a full
`s3://bucket/key`), never from its **IDENTITY** (`request_key` = `{epoch}{ETag}-{key}`, minted for
ingress idempotency). Three commits: the repair, the error surface it exposed, and a wedge found
while driving the composed path.

Discovery credit for the original find goes to the reviewing agent, which traced the live 422 past
the artifact to the field choice instead of stopping at "the artifact is unreadable".

---

## 1. The defect

`derive_provenance` was handed `request_key`. It is artifact-derived, it moves when the content
moves, and the surrounding comments already called it "the artifact pointer" — so it *reads* like a
location. It is not one. The fetch asked S3 for a key with an ETag glued to the front, and **every
derive refused**, which the refuse-not-floor ruling correctly turned into a loud 422 rather than a
silent supervise.

**Why no test caught it — three self-references, zero contact with the emitter:**
1. the parser documented the producer format as `<etag>:<key>` (COLON). The sensor has always
   emitted a DASH. The format was **invented**;
2. the fixture asserted the same invention, so parser and test agreed with each other and neither
   ever agreed with the producer;
3. the live witness hand-supplied a bare key in the shape the parser expected, so the composed
   sensor path was never driven.

Each is survivable alone. Together they close a loop that touches the producer nowhere, and a closed
loop can be arbitrarily wrong while every member of it is consistent.

The three-jobs rule was filed in `AGENTS.md` **using `request_key` as its worked example**, hours
before the derive was written against it. Knowing the rule did not prevent writing the defect — that
is the entry in the board, and the defence it implies is a mechanism, not attention.

## 2. The repair

| hop | change |
|---|---|
| sensor `start_review_op` | emits `artifact_uri = f"s3://{bucket}/{key}"` **beside** `request_key` |
| `build_start_review_payload` | carries it as its own payload field |
| cortex-bff | declares it on `ReviewStartRequest` **and** forwards it (a rebuilding hop) |
| `ReviewStarter` | derives from it |
| `parse_pointer` | accepts ONLY the full URI |

**Bare-key tolerance was removed, not kept.** Resolving a bare key against `ARTIFACT_BUCKET` made the
artifact's location depend on two runtimes agreeing on an ambient env var — a cross-repo string
contract smuggled in as a fallback. Tolerance IS the coupling.

**Refusals name their precondition.** `ArtifactUnreadable.reason` ∈ `malformed_pointer`,
`artifact_absent`, `store_unreachable`, `unparseable`, `schema_alien`. Same verdict, different
destination for the reader.

## 3. What the offline seals do differently

`tests/test_artifact_uri_contract.py` builds its payload **by calling the sensor's own
`build_start_review_payload`**, never by hand — the author who confuses the two fields writes the
fixture the same way. The field choice is pinned at the **call site**
(`test_the_derive_reads_the_POINTER_field_not_the_IDENTITY_field`), because a file-level substring
check passes on the prose *about* the field.

Every seal was shown RED by break-on-purpose and restored byte-identical:

| mutation | goes red |
|---|---|
| starter derives from `request_key` again | 3 × `test_review_starter` + the call-site pin |
| BFF drops `artifact_uri` on the forward | the passthrough pin |
| sensor stops emitting `artifact_uri` | 7 tests across 3 suites |

**Also fixed, red at HEAD:** three tests in `test_review_starter.py` had been failing since 1.3
landed — the fixture named no artifact, so the derive refused before composition was reached. Same
class, one layer up. `_wire` now injects the derive as a fourth seam, and the stub **asserts which
field it was handed**, so the conflation cannot walk back in under a green suite.

---

## 4. LIVE — refusal legibility, four pointers

Driven through `POST /reviews` from the dagster-user-code pod, each leg with a distinct
`request_key` (two legs sharing one would ATTACH to the first's stored result — the trap that ate a
leg of the previous witness).

| leg | pointer | HTTP | reason surfaced |
|---|---|---|---|
| absent | `""` | **422** | *no artifact_uri supplied — the admission posture is derived FROM the artifact* |
| **identity-as-pointer** | `epoch\|abc123def456-sustainment/…/review.json` | **422** | *…is not an s3:// URI… **(If this looks like an idempotency key such as `<etag>-<key>`, it is: identity and location are different fields.)*** |
| bare key | `sustainment/…/review.json` | **422** | *…a bare key is refused rather than resolved against an ambient bucket…* |
| absent object | `s3://processing-artifacts/…/NO_SUCH_WITNESS/review.json` | **422** | *does not exist (NoSuchKey) — the store answered and said so, so this is a bad pointer or a missing object, **NOT an outage*** |

The second leg is the defect itself, refused with the message that would have ended the original
debugging session in one read.

`store_unreachable` is **sealed offline only** — witnessing it means taking MinIO down, which is not
worth a sandbox outage. Stated rather than implied.

### The finding this leg produced: the reason never reached the caller

The first run of these four legs returned **four identical opaque 502s**:

```
{"detail": {"error": "review_start_failed", "code": 422}}
```

`gateway.py` read `rr.status_code` and **discarded the body**, while Restate had answered 422 with
the complete reason every time. The entire refusal taxonomy was computed correctly and destroyed one
hop from the only reader who needs it. **Legibility that stops at the pod boundary is not
legibility** — and it is precisely why the earlier session was sent to S3 to debug a caller-side
field mistake.

Fixed: the message is forwarded, and a TERMINAL refusal keeps its own 4xx (it is a statement about
the REQUEST, not a transport failure; 502 told every caller the gateway was broken). Sensor routing
is unchanged — `classify_start_review` maps a 422 with no recognised content status to
`refused_systemic` exactly as it mapped the old 502.

## 5. LIVE — the composed path, sensor-emitted

```
ADMISSION notice=IPCN25300X-R2 format=onsemi/unknown/v1 pipeline=(none) rung=supervised
          table=trust@1c45c6dc296e admitted_by=policy-default-missing-provenance
          derived_from=s3://processing-artifacts/sustainment/inbound/zz_look/generated/zz_look_pdf/review.json
          -> grouped_review
```

`derived_from` is a **full URI built by the sensor**, carried by the BFF, fetched by the starter.
Nothing hand-supplied at any hop — the composed-path seal the original work never had.

`pipeline=(none)` + `admitted_by=policy-default-missing-provenance` is the **designed** state: the
artifact carries no producer stamp, so it takes the floor and says so. Unchanged until doc-tools
rebuilds and re-extracts.

Deploy litany, all four rungs: rollout → digest changed (cortex-bff `b00f2f77`→`8595c021`,
dagster-control-plane `197a3091`→`4d9e4397`, restate-analyst `a6c3e2d2`→`6ff606cb`) → code grepped
present in each pod → behaviour witnessed above. `:latest` is mutable, so rungs 2 and 3 are not
optional.

**Settlement:** the witness artifact was removed and confirmed absent by `head_object`; the bucket is
back to its 16 real artifacts.

---

## 6. Found on the way: the sensor has been WEDGED, not idle

Driving the composed path required the sensor to fire, and it would not. The cursor had **changed
format** — bare S3 key → `<iso>|<key>` — and the value already persisted in Dagster's cursor storage
had not. Every tick compared across the two forms:

```
"2026-08-07T03:31:28+00:00|sustainment/…"  >  "sustainment/inbound/zz_look/…"    ->  False
```

`'2' < 's'`, so the comparison is False for **every** object, forever. Verified in-pod: 17 artifacts
under the prefix, **0 considered new** — while the daemon logged *"no new extractions (review.json)
after cursor …"* every thirty seconds. Nothing was red. The sensor had dispatched nothing since the
change landed.

**The migration bug wore the costume of the bug the migration fixed.** The lexicographic cursor was
replaced *precisely because* its failure mode was silent skipping.

Fixed by `_migrate_cursor`: translate faithfully when the old cursor's object still exists (its
`LastModified` is exactly the timestamp the new form should carry — nothing re-fires, nothing is
newly skipped), and **refuse loudly** when it does not, because both guesses are bad. The wedge is
reported as `CURSOR WEDGED — not idle`, never in the healthy sensor's words.

Witnessed live:
```
CURSOR MIGRATED (pre-LastModified form):
  'sustainment/inbound/zz_look/generated/zz_look_pdf/review.json'
  -> '2026-07-29T22:00:59+00:00|sustainment/inbound/zz_look/generated/zz_look_pdf/review.json'
```

**The seal's first version did not bite** — it asserted against the sensor's *source* that the wedge
branch preceded the idle branch, and deleting the migration CALL left both strings in the surviving
`try`/`except` with all 13 tests green. It now drives the sensor via `build_sensor_context`; both
mutations go red.

---

## 7. Filed, NOT fixed — two gaps the unwedging exposed

Unwedging released a **9-artifact backlog at once**. The sandbox saturated (user-code gRPC
health-check timeouts, cortex-bff liveness probe failures), and **6 of 9 runs were reaped** by run
monitoring — *"marked as failed from outside the execution context"*. Both survivors are accounted
for: one produced the ADMISSION line above; the other returned `NO_PARTS_EXTRACTED` and routed a
triage task before reaching the starter, so it correctly has no admission line.

1. ~~**A reaped run permanently skips its artifact, silently.**~~ **RULED AND CLOSED 2026-08-08 —
   see §8.** Sequenced *before* the ceremony: an autonomous pipeline whose intake can silently drop
   notices under load is not the pipeline a signature vouches for. The sensor consumed the `run_key`
   before the run died, so Dagster's dedup would never re-dispatch it — the same silent-loss shape
   the content-addressed `run_key` was adopted to prevent, entering through the run's *death* rather
   than its key.
2. **The sensor dispatches an unbounded backlog in one tick.** Any cursor reset, first enable, or
   unwedging stampedes. A run-queue concurrency limit on `start_review_job` is the obvious lever;
   picking the number is an operational decision, not a patch.

Neither is caused by this repair; both were revealed by it, and neither is in this packet's scope.
For **these particular** artifacts the outcome is benign — the reaped six are prior sessions'
unsettled witness fixtures (`witness_cropfail`, `witness_norender`, `witness_summon`) and extraction
experiments (`diodes_bbox`, `FULLGREEN`, `diodes_tier1`), not notices anyone is waiting on. Re-driving
them would file reviews into humans' queues for experiments. **That those fixtures were still in the
bucket at all is its own small finding**: settlement discipline was not applied to them when they
were created.

---

## 8. RULED AND CLOSED — at-least-once intake (2026-08-08)

Filed above as a gap; **ruled a correctness defect on the ceremony's own admission path and sequenced
before the signature** — an autonomous pipeline whose intake can silently drop notices under load is
not the pipeline a signature vouches for.

`run_key` was consumed at DISPATCH, not at COMPLETION, and the cursor had already advanced past the
object, so a reaped run dropped its notice permanently with no retry, no log, no trace.

**A reap is not a failure.** This pipeline deliberately fails a run on a systemic refusal — a loud
red run for ops, intended, once — and retrying that just re-refuses until a human fixes the grant.
A reap is the opposite: the execution was lost and no verdict was reached. The discriminant was
**validated against both categories in real run history before any code was written**:

| category | shape | live count |
|---|---|---|
| reaped | `FAILURE`, **zero** `STEP_FAILURE` events | 6/6 |
| designed failure | `FAILURE` **with** a `STEP_FAILURE` event | 3/3 |

`run.status` says `FAILURE` for both and cannot tell them apart.

### Witnessed live

| leg | observation |
|---|---|
| dispatch | attempt 1 tagged `review/artifact_key` + `review/attempt`, run_key **unchanged** (`{etag}-{key}`) |
| reap | failed from outside the execution context → `FAILURE`, classified **REAPED** |
| **re-arm** | attempt 2 dispatched, run_key `…#a2` — the notice that would have been lost |
| settle | attempt 2 **SUCCESS** |
| terminate | exactly 2 tagged runs; **no attempt 3** |
| **residue** | 9 untagged failures before and after — **none re-armed** |

The witness artifact was an **honest empty** (no parts, not doc-flagged) on purpose: it exercises
dispatch → reap → re-arm → settle end to end while filing nothing into a human's queue. Removed
afterward and confirmed absent; the bucket is back to its 16 real artifacts.

**Untagged history is invisible to the re-arm, by construction.** The tag *is* the opt-in boundary,
so the six reaped runs that exposed the defect — prior sessions' unsettled fixtures and extraction
experiments — can never be re-driven into humans' queues, and no epoch, cutoff, or deletion of
anyone else's residue was needed to bound it safely.

### Two defects the break-on-purpose pass found in my own work

1. **The in-flight guard was decoration.** A redundant `latest.status != FAILURE` check absorbed the
   mutation, so deleting the guard left the suite green — and the test agreed with it by giving the
   live run the *higher* attempt number. A guard a mutation cannot reach is not a guard.
   Restructured so it is load-bearing, and the test now constructs the case that needs it.
2. **`context.instance` RAISES when no instance ref was provided** — it does not return `None`, so
   `getattr(..., None)` was a false guard and the re-arm was one attribute access from becoming a
   *precondition* for first delivery. Found by two unrelated cursor tests going red, which is the
   wrong way to find it; it now has its own pin.

All six mutations bite; restores byte-identical.

### One legibility note for operators

The `RE-ARMING …` and `DISPATCH EXHAUSTED …` lines go to the **sensor's per-tick log**, not to the
daemon's stdout — they do not appear in `kubectl logs deploy/iagent-dagster-daemon`. An operator
looking for them in the obvious place will not find them. Stated rather than discovered later.

## What remains

Unchanged by this work: `pipeline_version` reads `(none)` on every real notice until **doc-tools is
rebuilt and re-runs an extraction**. Until then every notice takes the floor as
`policy-default-missing-provenance` — correct, legible, and the honest state. The remaining gap is
corpus, not code.
