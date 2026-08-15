# PCN five-beats loop — end-to-end LIVE on the rails (exhibit)

> **Key renamed since this run (M3.1 tail, 2026-08-03): the review audience is now
> `disposition_review:<compartment>`.** Left verbatim as the record of the 2026-07-24 run — beat 2
> really did show audience `pcn_disposition:SUSTAINMENT` in alice's queue. Do not copy the old key
> into a grant file; see `docs/reference/pcn-can-act-topaz-binding.md`.

Ran 2026-07-24 on sandbox `edge`. Proves the WHOLE PCN grouped-review loop closes on the live cluster —
notice → batch → grouped review in a reviewer's queue → approval → fan-out → per-part dispatch tasks in a
DIFFERENT persona's queue → durable state stamps. The batch-diff proved the front half (`start_review`
suspends on a server-authored batch); the kill-seal proved the dispatch driver in isolation; THIS run
joins them and drives the seam nobody had crossed live: **approve → fan-out → dispatch**.

The spine of "the showing." Two personas, two audiences, one approval fanned to three — the multiplayer
separation is the product thesis made observable.

## Setup — personas via the SAME sync mechanism (not hand-surgery)
- `task_grant_sync.py` (product image, cortex-bff pod) against the sandbox policy repo — the mechanism the
  discrimination seal proved. Two audiences, two personas (`+1 relations` — bob's was the only new one;
  alice's `pcn_disposition:SUSTAINMENT` persisted from the discrimination seal):
  - **alice** → `pcn_disposition:SUSTAINMENT` — the REVIEWER (grouped-review `can_act` audience).
  - **bob** → `qualification` — the QUALIFICATION ENGINEER (the dispatch queue for `dispatchQualification`).
  - Readback positive control: `checked=2 failures=0`. Both `can_act` checks resolve **true**.
- Declared in the sandbox repo (`f441af7`) so live==repo — no drift from the run.

## The five beats — each witnessed live

| beat | what | evidence (live) |
|---|---|---|
| **1 compose** | `PcnReviewStarter/start_review` over IPCN25300X, 3 in-scope MPNs (all resolve exact via engine-o `resolve_pcn_instance`, score 1.0) | `STARTED`, `count=3`, `resolved=3 unresolved=0`, funnel `input=3 residue=3 filtered=0 auto_disposed=0`, `ruleset_ref=rules@2915ddb229e4` |
| **2 review** | the ONE grouped HumanTask routes to the reviewer's queue by audience | alice `/me/human_tasks` → `grouped:IPCN25300X:alice@example.com`, audience `pcn_disposition:SUSTAINMENT`, "Review 3 affected part(s)", **pending**. It's in alice's queue *because* alice is granted that audience. |
| **3 approve** | `PcnGroupedReview/<wf>/submit_decision` accept-all (`{"overrides":{}}`) — clean because all 3 rows are verified (`needs_review=false`) | `{"status":"accepted","accepted":true,"resolved_count":3}` → promise resolves → workflow resumes |
| **4 fan-out** | one approval fans to N per-part dispatch tasks in the DISPATCH persona's queue | bob `/me/human_tasks` → **3** `pcn_disposition` tasks (`IPCN25300X:NSR01L30NXT5G` / `NSR02F30NXT5G` / `NSR05F20NXT5G`), audience `qualification`, `requested_by=alice@example.com`, each `subject_ref` the resolved component IRI, pending |
| **5 state** | each dispatched part carries a durable disposition stamp; the dashboard feeder returns it | engine-o `/pcn_parts_by_state {dispatchQualification}` → `count=3`, the 3 component IRIs, each `ref=IPCN25300X:<MPN>`, `ruleset=rules@2915ddb229e4` |

## What the join proves that the halves couldn't
- **The seam crosses live.** `submit_decision` resolving the durable promise → `run()` resumes → `fan_out_
  dispatch` inside the journaled workflow context → N keyed `PcnDispatchItem` invocations → N tasks + N
  state writes. That whole chain had only ever run in tests; here it ran on the cluster, once, cleanly.
- **Multiplayer separation is REAL, by audience.** alice's grouped review (`pcn_disposition:SUSTAINMENT`)
  and bob's dispatch tasks (`qualification`) are DIFFERENT audiences: bob never saw the review, alice never
  saw the dispatches. The compartment/queue key does the separating — the same key that discriminated in
  the `can_act` seal, now separating WORK not just permission.
- **Provenance is one hash, end to end.** `rules@2915ddb229e4` appears at beat 1 (batch), rides the
  fan-out, and is stamped on the state at beat 5 — the ruleset that proposed the disposition is the ruleset
  recorded against the dispositioned part. Nothing re-derived, nothing drifted.
- **`requested_by` earns its keep.** Every dispatch task carries `requested_by=alice@example.com` (the
  approver who resolved the batch) — the field whose absence 422'd the register live (found in the
  batch-diff, threaded in `2f1c5ca`). Without it, beat 4 parks; with it, the provenance names the human.

## Residue ruling — BUILD SUBSTRATE, cleaned before the rehearsal (explicit; revises the open-of-window ruling)
When this window opened the question "demo artifact or test run?" was settled **test run, clean after** —
the demo mints fresh during the rehearsal with BFF + dashboard live, no seam. This run's output is a
genuine disposition's genuine output AND it usefully feeds the next two build windows, which tempts a
reframe to "leave it standing." Recorded here as a REVISION, not a closing-paragraph slide:
- **KEEP now** as substrate for the BFF-wiring + dashboard windows: 3 parts in `dispatchQualification`
  (dashboard feeder renders exactly these), 3 pending qualification tasks in bob's queue (HITL records the
  qualification view acts on), alice→SUSTAINMENT + bob→qualification DECLARED in the sandbox repo (`f441af7`).
- **CLEAN before the five-beats rehearsal** — a NAMED pre-rehearsal step, so the demo mints fresh (honors
  the original ruling). The failure it prevents is concrete: re-running `IPCN25300X` against live residue
  either (a) idempotency collapses it into the day-old tasks → demo shows stale `requested_by` timestamps,
  or (b) yields SIX parts in `dispatchQualification` + duplicate tasks in bob's queue — both are seams in
  the exact artifact the demo displays. Clean = clear the 3 state stamps + cancel the 3 tasks (and reset
  the workflow key) before beat 1 of the rehearsal.
- **WAKE:** the five-beats rehearsal session begins with this cleanup, or re-rules read-only-replay. Not
  the unexamined middle.

## Follow-up observed (not M1 — filed, not fixed)
The dispatch queue key is a PLAIN persona name (`qualification`), not `task_kind:compartment` like the
review audience (`pcn_disposition:SUSTAINMENT`). So dispatch/qualification WORK isn't compartment-isolated
the way REVIEW is. **Wake trigger (sharpened):** not "when a second COMPARTMENT ships" but **the first day
two kinds of work share the `qualification` queue** — i.e. when any SECOND audience/consumer reads that
queue, whether or not the second thing is a compartment. The isolation gap bites on shared consumption,
earlier than multi-compartment. Revisit `qualify:<compartment>` (or a consumer-scoped key) then. Declared
in the sandbox repo note; deny-by-default holds regardless (no grant ⇒ no queue).

## Bug-arc closure — `requested_by`: found → fixed → classified → LOAD-BEARING
The strongest form of the arc thesis (the live session catching not just a bug but a missing FEATURE
wearing a bug's clothes):

| bug (live-only) | found | fixed | classified | now |
|---|---|---|---|---|
| `ruleset_ref` whole-graph hash → co-tenancy drift | batch-diff | content-only hash (`51b146b`) | co-tenancy-stable provenance | the one hash shown end-to-end (beats 1→5) |
| `rdflib` missing from image | load 500 | pyproject+lock (`d3b3c2e`) | test-env==image-env rule | suite runs `--frozen`, no overlay |
| **`requested_by` absent** | **register 422 → park** | **thread approver (`2f1c5ca`)** | **register contract, not detail** | **LOAD-BEARING: names the human on every dispatch task (beat 4 provenance)** |

`requested_by` is the exemplar: a 422 that looked like a wiring miss was a provenance requirement the
design hadn't stated. The live session didn't patch a bug — it surfaced a feature the offline seals
couldn't have named, because only the real register contract demanded it.
