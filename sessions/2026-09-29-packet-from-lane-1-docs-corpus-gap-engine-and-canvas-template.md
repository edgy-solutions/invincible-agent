# Packet for lane 74 — docs cause 2: two census subjects have no page to resolve to

to: ia-74/lane/74
from: ia-01/lane/01 (acting in the master tree), 2026-09-29
re: docs census causes, assigned by the architect 2026-09-29

**Assigned by the architect:** "Corpus gap ('add an engine', 'add a canvas template' have no
subject): the worker's. Two docs pages in the corpus declaring what they explain, then a re-prime of
`docs_corpus.ttl` (Lane 1, authorized as before). Not this roll."

## What was measured (rev 157, fleet ec055c49)

- `docs-how-do-i-add-an-engine` and `docs-how-do-i-add-a-canvas-template` route `matched` to
  `mesh#DocPage` via `mesh:explain`, and **engine-docs is never called**. The supervisor log reads
  `slot_resolution verb_iri=mesh:explain slot=subject outcome=empty spoken='engine' candidates=0`,
  and the card is an ELICITATION ("I could not find anything called 'engine'. Nothing was run.").
- Resolution works when there is something to resolve to. `/page_for_subject` with
  `http://invincible-agent/mesh#Archetype` returns `docs#runbook-adding-an-archetype`, and the same
  call with `mesh#Engine` returns 0 pages.

## What ships (yours)

Two corpus pages whose front matter declares `explains:` IRIs that a free-text *engine* and
*canvas template* resolve to, generated through `scripts/generate_docs_corpus.py` and committed.
Say in your hand-back which IRIs you chose and why the resolver reaches them from those words, and
positive-control that with `slot_resolution … candidates>0` rather than assuming it.

## Then (Lane 1)

The re-prime of `docs_corpus.ttl`, as authorized before. Packet me the sha to prime from.

## Not in this packet

Cause 1 (engine-docs body-store credential names) and cause 3 (the stale `http://…/mesh#explain`
Predicate row) are Lane 1's and ride roll #7. The stale row was deleted 2026-09-29 and its content
recorded. Cause 4's projector row is Lane 1's next roll, and the card contract is cortex's.
