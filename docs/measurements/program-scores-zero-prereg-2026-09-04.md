---
id:         program-scores-zero-prereg-2026-09-04
status:     PRE-REGISTERED 2026-09-04 22:37 CDT — WRITTEN BEFORE ANY ARTIFACT WAS READ
owner:      agent (lane 1)
repo:       invincible-agent
summary:    Program classified at conf 0.00 on the variance phrasing at 21:32, 21:47 and 21:55, having scored 0.90–0.94 on neighbouring questions the same hour. Two outcomes from one failure: at 21:47 nothing rescued it and the generalist fabricated; at 21:55 instance preemption rescued it and the routing record stayed stamped pre-override. This file records what I expect to find BEFORE looking, because the diagnosis is the thing most at risk of being fitted to whatever the first artifact happens to show.
---

# Program scores 0.00 — pre-registration

Written before opening either artifact. The commands are recorded below; the figures are not
yet known.

## The architect's hypothesis, and where I think it needs correcting

> *"it reads like the gate intermittently dropping Program from the pool the classifier sees
> (degrade-open paths are per-lookup, so a flaky served-set would do exactly this)"*

**A flaky served-set in the sense of FAILING cannot do this**, and the distinction decides
where to look. The productive-option gate degrades open in two places:

```python
_served = await _served_class_uris(...)
if _served:                        # empty  -> NO FILTER AT ALL
    _productive = [c for c in candidates if c.get("uri") in _served]
    if _productive and _unproductive:
        candidates = _productive
    elif not _productive:          # would empty the pool -> NO FILTER
        ...
```

A lookup that raises returns `frozenset()`, and an empty served-set means the pool is passed
through **unfiltered** — MORE candidates, not fewer. A total failure therefore produces the
opposite of the observed symptom.

**So for the gate to drop Program, the served-set must be non-empty AND incomplete.** The two
guards cover *empty* and *would-empty-the-pool*. There is no guard for **partially wrong**, and
a partially-wrong set is indistinguishable from a correct one at the point of use.

**And a partial result would be CACHED.** `_SERVED_CACHE` holds `(expiry, served)` with
`_SERVED_TTL_S` defaulting to 120s, keyed by domains. A single incomplete read is therefore
pinned for up to two minutes — which is the right order of magnitude for "three failures inside
25 minutes, working before and after."

## Predictions, with the evidence that would falsify each

**P1 — GATE-DROP.** `Program` is ABSENT from `subject_candidates` on the 21:47 and 21:55 draws
and PRESENT on the 22:20–22:30 draws.
*Falsified by:* Program present in the candidate set on a failing draw.

**P2 — SAMPLER.** Program is PRESENT in the candidate set on the failing draws and the
classifier scored it 0.00 anyway.
*Falsified by:* Program absent on a failing draw.

P1 and P2 are exhaustive and mutually exclusive on this evidence, which is the point of writing
them down as a pair. **If P1 holds, the gate needs a third guard; if P2 holds, this belongs in
the winner-instability packet as "now reaches the classifier at conf 0" and the gate is
exonerated.**

**P3 — the candidate COUNT is the tell, independent of Program.** The working draws are
reported as "four candidates considered". If the failing draws show a DIFFERENT count, the pool
differed and P1 is supported even before checking membership. If the count is identical and
Program is present, P2 is supported.

## What I expect NOT to find, recorded so a null result still means something

* **No `productive-option gate DROPPED` line naming Program** on the failing draws would weaken
  P1 sharply — the gate prints when it filters, so a silent gate that nonetheless dropped a
  class would mean the pool differed BEFORE the gate (i.e. Weaviate recall, not the gate).
  That is a third possibility neither P1 nor P2 covers, and it is the one I would miss if I
  only checked membership.
* **`fallback_reason`** on 21:47 should be `no_verb_classified` (the architect's note says "no
  verb classified" at 21:32). On 21:55 the record reportedly says subject unknown — if the
  stored `fallback_reason` on 21:55 is instead absent or `matched`, then the card's header is
  reading a DIFFERENT field than the one I am about to inspect, and the provenance defect is
  in the projection rather than the capture point.

## Commands

```
# artifacts, by time window
MATCH (a:AnswerArtifact) WHERE a.created_at >= <21:00 ms> AND a.created_at <= <23:00 ms>
RETURN a.id, a.created_at, a.question_text, a.routing_inline, a.resolved_intent
ORDER BY a.created_at

# the deployed engine-o's own view of the pool, per draw
POST /resolve  (the variance phrasing, caller's domains)  x N
```

## The standing risk this file exists to name

The engine-cost lane's numbers and mine disagree about what a "draw" is unless the pool is
recorded per draw. **Four things per draw:** the winner, the candidate SET, set disjointness
across draws, and whether the winner carries a verb in that scope. A run scored on winners
alone cannot distinguish P1 from P2 — both produce "Program, 0.00".

---

## ADDENDUM — written after reading the artifacts, BEFORE the live probe

Sequencing stated plainly: P1–P3 above were written before any artifact was opened. P4 below
was written after reading the eight artifacts and before running a single live draw.

**The artifacts refute P1 and P2 together.** `classify_called: false` on every failing draw —
the classifier was never called, so "Program scored 0.00" is not a score, it is the default
zero of a classification that did not run. And `candidate_count: 0` means the gate could not
have run either: it is guarded by `if candidates:`, and its second guard REFUSES to empty a
pool. The gate can only ever shrink 6 to fewer; it cannot produce 0. **The gate is exonerated
and the sampler is untouched.** The failure is upstream of both: class recall returned nothing.

**P4 — PHRASING-DETERMINISTIC, NOT INTERMITTENT.** The two zero-candidate draws are the SAME
question (*"why are we over budget on Notional Program Meridian"*), asked twice. Every other
phrasing that night returned 6 candidates and routed to Engine F. That question was never
retried later, so **nothing in the evidence establishes non-determinism on the resolver at
all** — the appearance of flakiness comes from the SECOND decision in the run, not the first.

*Predicts:* N draws of *"why are we over budget…"* return 0 candidates on every draw, and N
draws of *"what is driving the cost variance…"* return 6 on every draw.
*Falsified by:* any split within a phrasing.

**If P4 holds, the reframe is total.** This is not non-determinism to be chased with repeated
draws; it is a recall gap on one phrasing — a fixable, testable, deterministic hole — and the
only non-determinism in the story lives in the rescue path that sometimes hides it.

**P5 — TWO ROUTING DECISIONS PER RUN, and the two capture races pick different winners.**
`subtask_routing_decision` is emitted for EVERY decision including failures;
`subtask_graph_trace` is emitted ONLY when the subject grounded and compatible verbs exist
(dynamic_supervisor.py:1519). Both are first-wins in the gateway. Artifacts 4 and 5 each hold
an UNKNOWN routing record AND a grounded trace (Program → `mesh:finVarianceAnalysis`), which
is impossible from one decision. So there were at least two, **and the routing record was
claimed by the failing one while the trace was claimed by the succeeding one.**

That is a sharper defect than "stamped pre-override": the two races have DIFFERENT ELIGIBILITY
RULES, so they select different subtasks by construction, and the failure-eligible race is the
one feeding the header a human reads.

---

# RESULTS — every prediction refuted except P5, which was right for the wrong reason

## The cause: `/resolve` read timeout under parallel-subtask contention

```
02:44:47 task_0  resolve_subject failed ... Read timed out (read timeout=30)
                 routing_decision subject_uri=UNKNOWN fallback_reason=subject_unknown
02:44:48 task_1  routing_decision subject_uri=fin#Program conf=0.97 compatible_count=6
                 verb_iri=mesh:finVarianceAnalysis verb_conf=0.94
```

**The run FANS OUT INTO TWO PARALLEL SUBTASKS**, each posting its own `/resolve` to engine-o at
the same moment. Engine-o's BAML calls run 8–30s against Ollama. One subtask times out at 30s;
the other succeeds. `Program conf 0.00` is **the default value of a call that never returned** —
not a score, not a sampler draw, not a dropped candidate.

Confirmed against the deployed engine-o, 7 draws of the exact failing phrasing, serially:
winner `fin#Program` every time, conf 0.92–0.95, candidate set identical on every draw
(`ControlAccount, FundingLine, PerformanceMeasurementBaseline, Program`). **Zero set
disjointness. The resolver is deterministic on this input.** The variable is contention.

## Refuted

* **P1 (gate-drop)** — refuted twice over. `candidate_count: 0` means the gate never ran
  (`if candidates:`), and the logs show it running NORMALLY on the succeeding subtask:
  `productive-option gate DROPPED 4 unserved class(es) (domains=['PROGRAM_FINANCE'])`. The gate
  worked correctly throughout.
* **P2 (sampler)** — refuted. `classify_called: false`; the classifier was never reached.
* **P4 (phrasing-deterministic)** — refuted. The failing phrasing resolves 7/7 now.
* **The architect's "instance preemption rescued it"** — refuted. Preemption DID fire
  (`match=exact, provider=engine_fin_finance`) but on the subtask that was already succeeding.
  It rescued nothing; the other subtask had already timed out and been recorded.

## P5 confirmed — and the mechanism is worse than a race

Two subtasks, two `subtask_routing_decision` materializations, and the gateway takes
**first-wins**. But the winner is not random:

| run | first to materialize | that subtask's outcome | recorded |
|---|---|---|---|
| e82b3031 (21:47) | task_0 @ 02:44:47 | **timed out** | UNKNOWN |
| 2a627ea7 (21:55) | task_1 @ 02:52:28 | **timed out** | UNKNOWN |

**A 30-second timeout completes SOONER than a resolve→classify chain that takes 44 seconds.**
So whenever one subtask fails and another succeeds slowly, the failure wins the race *by
construction*. This is not a coin flip weighted toward failure — it is a rule that systematically
prefers the record saying "not grounded".

## And the card is selected by a DIFFERENT rule

* **Routing record** → first subtask to *materialize* (arrival time).
* **Rendered card** → `task_0` (task index).

| artifact | task_0 | task_1 | card shown | record shown | agree? |
|---|---|---|---|---|---|
| 4 (21:47) | **timed out** → Engine A | succeeded → Engine F | Engine A fabrication | task_0, TRUE | yes |
| 5 (21:55) | succeeded → Engine F | **timed out** | Engine F variance tree | task_1, FALSE | **no** |

**The two rules agree only when task_0 also finishes first.** That is the entire provenance
defect, and it explains both nights' observations from one mechanism: at 21:47 the card and the
record described the same failing subtask (wrong answer, honest record); at 21:55 they described
different subtasks (right answer, false record).

**The record was never stale and never stamped pre-override.** It is ACCURATE about a subtask
whose answer nobody saw — which is why nothing in the capture path looks broken.

## The fix this implies

Not "add a post-dispatch capture point". **Select the routing record by the same rule that
selects the card** — the subtask whose answer is rendered — or render every subtask's decision.
Adding a later capture point to a first-wins race leaves the race.

## Separate defect found in passing, NOT the cause

At 02:26:45 ExtractIntent received:

```
show me CPI and SPI over time for Notional Program Meridian Artifact 155 of 184
```

**UI chrome ("Artifact 155 of 184") is concatenated into the question text**, and the extractor
duly returned `entity_refs: ["Notional Program Meridian Artifact 155"]` — a corrupted referent.
The failing "over budget" draws were CLEAN, so this did not cause them. Filed on its own.
