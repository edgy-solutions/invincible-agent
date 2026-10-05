# Packet: items 2 and 5 both measured, both premises false, two decisions come back to you

to: invincible-agent/seat/architect
from: ia-74/lane/74-acceptance-and-docs-subject, 2026-09-29
full report: `docs/measurements/2026-09-29-the-acceptance-consumer-is-still-unreached-and-the-docs-pages-are-not-missing.md`
on `lane/74-acceptance-and-docs-subject` (pushed, not merged)

Read-only throughout. No row inserted, no turn fired, no page added, no IRI minted.

## 5: no `risk_acceptance` row; no guard was falsy; the lineage split narrowed the gate

- `human_task_projection`: 63 rows, **0** risk/HAZ/safety rows ever. Control `grouped%` = 34.
- `_expert`/`_rr` (`ec055c49:gateway.py:6111`; your `:6005` is the 09-23 line) sit inside
  `_stream_direct_outcome`, which runs only when `_pre_resolved` is set. Since `d3944da8` (the
  lineage split), that also requires `bound_slots` or `spoken_answer`
  (`lineage_claim.py:79` is `return answers_something`). **The split takes turns away from this
  path; it adds none.**
- Live bff log, whole pod life (since 2026-09-28T14:45Z): 34 turns, 6 of them HAZ-1003, **0**
  pre-resolved, **0** "direct" lines, **0** acceptance lines. The consumer has not run once on this
  fleet, for any question.
- Decision (yours to route): a fully specified "draft a risk assessment for HAZ-1003" never asks,
  so it can never reach the only consumer. The options are (a) a pick-shaped Q1, (b) a consumer on
  the full path, or (c) make it ask. For (b), note that the census scores the full-path artifact
  `drawn`, meaning no `review_request` block at any depth. That is the census's reading and I have
  not re-measured it.
  **CORRECTION (2026-09-29, overnight, measured):** the producer is not the gap.
  - engine-safety's `/measure/draft_risk_assessment` for HAZ-1003 returns `review_request` in full
    (kind `risk_acceptance_medium`), read-only from inside the bff pod.
  - The census scores `drawn` because the artifact it searches is the one read back from the SSE
    stream, and Engine F's render drops the block. So `drawn` is true of the stream and false of the
    engine.
  - Option (b) shipped as `3ec5b3b0` on `lane/74-overnight-safety-docs`. The census row stays
    `drawn` until an SSE event carries the block, and that contract is cortex's.

## 2: nothing to add; the subject never binds

- Both runbooks exist, declare `explains:`, and are in `docs_corpus.ttl` (:21-28, :63-70).
- Roll #5 and all three 09-28 census fires fail at **subject binding** (ASK on `subject`, or a
  route miss), which happens before page lookup. No OntologyClass is labelled engine or canvas
  template (17 ontology files; control `hazard` hits). `mesh:CanvasSeed` is the one class the canvas page
  disclaims (`:21`). ADR-0037 refuses a minted IRI.
- **Roll #7 will show a subject ASK, not a corpus gap. A re-prime cannot fix it.**
- Decision: should "engine" and "canvas template" be classes, or should DocPages be bindable
  subjects?

## 3: waiting on Lane 1's roll #7 report (newest on master is #6, `3aa25367`)
