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
