---
id:         subject-resolution-at-composition
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  agent_fleet/restate_analyst/review_composer.py
repo:       invincible-agent
summary:    A resolvable MPN composes as subject_unresolved. Two hypotheses eliminated 2026-08-10; one survives (frozen-at-composition) with a named discriminating read.
---

# OPEN — why a resolvable MPN composes as `subject_unresolved`

**Not a defect in the dispatch path.** The dispatch behaved exactly as designed: no resolved subject
⇒ no `graph_write` ⇒ the task carries the re-link provenance instead, and `completed success` is
honest. All eight historical `DispatchItem` records show the identical shape
(`state_written: false, subject_unresolved: true`) — **no dispatch in this system's history has ever
written disposition state, and every one was correct not to.** The composer's own seam-diff seal
witnessed this branch on real-shaped `IPCN25300X` input ("2 resolve, 1 abstains → kept for re-link,
not dropped").

## The question

`resolve_subject_via_engine_o("NSR01L30NXT5G")` called directly from engine-a **right now** returns
`http://internal/components/NSR01L30NXT5G`. Yet the batch those items were composed from recorded
them as unresolved. Same MPN, same graph, different answer.

Consequence, and why it is worth a session: a composed batch can carry `subject: None` for an MPN
the system *can* resolve, which silently converts a graph-writing dispatch into a task-only one. The
effect still lands (the task), so nothing is lost — but the graph never receives the disposition,
and nobody is told the difference was a resolution miss rather than a design branch.

## One hypothesis — two were eliminated 2026-08-10, by reading the call site

The original filing carried three. Two are now dead, and the read that killed them was not mine:
the architecture agent found that **the composer calls engine-o with no credential at all.**

```python
# review_composer.py:94
resp = requests.post(f"{engine_o_url}/resolve_instance",
                     json={"identifier": mpn}, timeout=_HTTP_TIMEOUT)
```

No `Authorization`, no identity, no `entitled_domains`. Verified verbatim.

**Hypothesis 3 — entitlement-scoped resolution — is dead.** `/resolve` domain-scopes to the caller's
entitled domains, so a composer resolving under a different scope than a reader was the architecture's
own prediction and would have been a real finding about *whose entitlements author a batch*. It cannot
be: there are no entitlements on either side of this call.

**Hypothesis 2 — call-site difference — is dead too, and this one is mine to close.** The direct call
that resolved was `resolve_subject_via_engine_o(mpn)` — *the same function*, in the same pod, with the
same absent identity. Not a different call site: the identical code path, twice, with different
answers. Whatever differs, it is not the caller.

**Hypothesis 1 survives, and it is now the whole question: a resolution result FROZEN at composition
time** (the stored-value class — a snapshot the world moves under).

### The named read that discriminates it

**What wrote `subjectToNotice` onto those component nodes, and when, relative to the batch's
composition?** `http://internal/components/NSR01L30NXT5G` carries exactly that one triple. If it
arrived after composition, hypothesis 1 is confirmed and the design's re-link provenance exists for
precisely this arrival. If it predates composition, all three hypotheses are dead and the question
reopens with no surviving branch — which would itself be the finding.

### A second read, from a six-week-old open finding

**Hole 2's second failure mode was recorded OPEN on 2026-06-26 and has the same shape as our
survivor: identifier-form mismatch.** The finding, verbatim from the record — *"LLM extracts
'360 Dashboard' but DataHub stores 'Customer 360'; engine_d returns 0 hits on the LLM form even
though it returns 1.0 on the stored label."* A token-subset fallback with a uniqueness guard was
banked and, as far as that record goes, never landed.

Identical resolve path, different answers **depending on the form of the identifier** — which is
exactly what we observe, and our MPNs come from extraction, where the emitted form can change between
runs.

**This is a lead, not a finding, and it may be the MECHANISM of hypothesis 1 rather than a competitor
to it.** A snapshot frozen at composition and an identifier whose form drifts are the same story told
from two ends. It is checkable in the same pass as the timestamp read:

**Compare the MPN string stored in the composed `batch_items` against the string the artifact carries
now.** If they differ, form-drift is the mechanism and the timestamp question is downstream of it. If
they are byte-identical, the lead is dead and frozen-at-composition stands alone.

## The follow-up either way

The design anticipated resolution arriving late — that is what the task's re-link provenance is
*for*. So the standing question is whether anything ever **exercises** the re-link: does a later
resolution ever cause the disposition to reach the graph, or does the provenance sit unread? That is
a parked item, not a defect.

## Not autonomy-specific

The supervised path shares the identical composer, plan and dispatch. Nothing here touches the
trust-table promotion, and it would be wrong to demote over it.
