# Items 2 and 5: the acceptance consumer is still unreached and the lineage split narrowed its gate; the docs pages are not missing and the subject never binds

from: `ia-74/lane/74-acceptance-and-docs-subject`, 2026-09-29
measured at: repo `origin/master` = `17bb2064`; fleet `ec055c49` (`iagent-cortex-bff` and
`iagent-engine-safety` both run this image)
posture: read-only. No row inserted, no turn fired, no store written, no page added, no IRI minted.

Both dispatched items rest on a premise, and **both premises are false**:

| item | dispatched premise | measured |
| --- | --- | --- |
| 5 | "With the lineage split deployed, the guard at gateway.py:6005 should now be reachable." | The lineage split (`d3944da8`) made the gate **stricter**. The guard is still never evaluated on a typed turn, and nothing reached it at all in this pod's lifetime. |
| 2 | "add an engine" / "add a canvas template" fail on a corpus gap | Both pages exist, both declare `explains:`, and both are in the committed corpus. The rows fail **before the corpus is consulted**, because the question's subject never binds. |

---

## Item 5: no `risk_acceptance` row, and no guard value was falsy

### The table (read-only)

The query ran under `PGOPTIONS='-c default_transaction_read_only=on'`, with the DSN read from the running
bff's own environment (the deployment spec holds an unresolved `$(…)` template):

| query on `human_task_projection` | result |
| --- | --- |
| `count(*)` | **63** |
| `task_id ilike 'risk-acceptance%' or kind ilike 'risk_acceptance%'` | **0 rows** |
| widened: `task_id ilike '%haz%' or '%risk%'`, `kind ilike '%safety%' or '%risk%'` | **0** |
| control, the same filter shape: `kind ilike 'grouped%'` | 34 |
| kinds present | `grouped_review` 34, `pcn_disposition` 16, `extraction_refusal` 10, `workflow_ack` 3 |

No risk-acceptance row exists, and none has ever existed in this table.

### Which guard was falsy: neither, because neither was evaluated

This is the same answer as 74's 09-23 report
(`sessions/2026-09-23-report-74-the-consumer-is-unreachable-and-the-lot-menu-needs-no-pin.md`,
image `c000514`). What is new is that the answer **survives the lineage split**, and the split is
why it survives.

The deployed gateway (`ec055c49:src/iagent/gateway.py`, located by form, not by the cited number):

| line | what is there |
| --- | --- |
| :6085 | `_expert = outcome.engine_response or {}` |
| :6111-6112 | `if _expert:` → `_rr = acceptance_request.review_request_of(_expert)`, the R-076 consumer |
| :5956 | both lines sit inside `async def _stream_direct_outcome` |
| :5421-5422 | its **only** caller: `if _direct is not None:` → `_stream_direct_outcome(outcome=_direct, …)` |
| :5316-5317 | `_direct = None` / `if _pre_resolved:`, the only branch that sets `_direct` |
| :5002-5006 | `_pre_resolved = _pre_resolved_from_ask(_answering_artifact_id …) if pre_resolved_route_allowed(answers_something=_answers_something) else {}` |
| :4907 | `_answers_something = bool(request.bound_slots) or bool(request.spoken_answer)` |

**The cite `:6005` is the 09-23 line number.** At `ec055c49`, line 6005 is
`if outcome.slots_mat is not None:`.

**The lineage split narrowed the gate.** `d3944da8` ("a prose turn keeps its lineage and does not get
the route") is an ancestor of `ec055c49`. Its diff replaces
`_pre_resolved = _pre_resolved_from_ask(_answering_artifact_id or "", user_id)` with the conditional
above. Before the split, naming an ask was enough to reach the direct path. After it, the turn must
**also** carry `bound_slots` or `spoken_answer`. The split takes turns away from the consumer's path
and adds none. The premise that it "should now be reachable" is backwards.

### The live log agrees and adds a population fact

`deploy/iagent-cortex-bff`, pod started `2026-09-28T14:45:23Z`, log taken whole (20,378 lines):

| pattern | count |
| --- | --- |
| `orchestrate: user=`, i.e. turns | 34 |
| HAZ-1003 turns (`context_update … ['HAZ-1003']`) | 6 |
| `pre-resolved route for run` | **0** |
| any line containing `direct` | **0** |
| `safety acceptance dispatched` / `safety acceptance NOT opened` | **0 / 0** |
| `direct path failure cause` | 0 |

All six HAZ-1003 turns are census turns (`urn:li:answerArtifact:census-safety-haz-1003-risk-assessment-…`,
log lines 787, 1190, 1478, 18865, 19151, 19430). Each one:

- routed with no ask: `verb=mesh:draftRiskAssessment disposition=route accepted=1 refused=0`;
- ran as a Dagster run (`Captured N materializations for run …`);
- ended with `AnswerArtifact dispatch scheduled … (delivery already completed at stream_end)`.

**None of the 34 turns in this pod's life took the direct path.** So the consumer has not run once
on this fleet generation, for any question. The HAZ-1003 row is only the first place anyone looked.

The only turn shape that reaches `:6111` is an **answer to an ask card that carries bound slots or a
spoken answer**. "draft a risk assessment for HAZ-1003" names its hazard, so it never asks, so
it can never be that answer. **Not fired:** a turn that reaches the consumer writes a
`human_task_projection` row through the real path, and whether to cause that write is not mine to
decide.

### A second gap, reported by the census and not re-measured here

The 09-28 morning census (three fires, fleet `ec055c4`) scores this row
`disposition 'drawn', row accepts ['task_requested']`. `walk_census._review_request` searches the
**whole** artifact for a non-empty `review_request` block (`walk_census.py:360`), so a `drawn`
result means the full path's artifact carries no such block at any depth. If that holds, moving the
consumer onto the full path would **not** be enough: the block would also have to survive from the
engine to wherever the consumer reads it. I have **not** verified this. It is the census's reading,
and this report does not re-measure it.

**CORRECTION (2026-09-29, overnight, measured).** The engine does carry the block. Read-only from
inside the bff pod, engine-safety's `/measure/draft_risk_assessment` for HAZ-1003 returns
`review_request` in full: kind `risk_acceptance_medium`, audience
`risk_acceptance_medium:SUSTAINMENT`.

The census scores `drawn` because the artifact it searches is the one read back from the SSE
stream, and Engine F's render drops the block before that. So `drawn` is true of the stream and
false of the engine. The condition above ("the block would also have to survive") was the right
one. The fix reads the block from the engine's own body, before the render: `execute_subtask`
materializes `subtask_review_request`, and the gateway opens the acceptance from the run's
materializations. That is `3ec5b3b0` on `lane/74-overnight-safety-docs`.

The census row for HAZ-1003 stays `drawn` until an SSE event carries the block, and the SSE
contract is cortex's.

### What this leaves as a decision (not mine)

`engine-safety` asks on every drafted assessment (`measures.py:411`). The only consumer sits on a
path that a fully specified question cannot take. Three options:

- (a) acceptance opens only when the draft is reached through a pick, and the walk sheet's Q1 is
  rewritten to that shape;
- (b) the full (Dagster) path gets a consumer, plus the block carried through, per the census gap above;
- (c) the typed turn is made to ask.

Each one changes a contract that someone else owns.

---

## Item 2: no page to add; the subject never binds

### The runbook already exists, and so does the canvas page

| page | `explains:` | corpus row |
| --- | --- | --- |
| `docs/runbooks/adding-an-engine.md` | `mesh:resolveInstance`, `mesh:enumerateInstances`, `mesh:InstanceResolution`, `mesh:InstanceEnumeration`, deliberately **no** `mesh:registerEngine` (header, ADR-0037) | `docs_corpus.ttl:63-70` |
| `docs/runbooks/adding-a-canvas-template.md` | `mesh:seedCanvas`, `mesh:seedPortfolioCanvas` | `docs_corpus.ttl:21-28` |

A second page would duplicate a declared subject. The instruction "check first; if it exists,
declare its subject" is already satisfied for both pages.

### Where the rows actually fail

- **Roll #5** (`2026-09-27-roll-5-…md:126-128`, `:173-175`): both rows are `slot_required` on
  `subject` for `mesh:explain`, with `accepted_slots={}` and `option_source=''`. The question
  reached the verb and could not supply its subject.
- **The 09-28 morning census**, three fires at fleet `ec055c4`: the cause rotates between a route
  miss (`verb UNKNOWN`, `subject_unknown`) and `slot_required` + `ELICITATION`. **None of the six
  readings is a corpus miss.**

The page lookup comes **after** subject binding. `mesh:explain`'s `subject` takes the universal
referent `mesh:Thing` (`docs_agent/slots.py`), and LEG 3 of `find_compatible_verbs` begins
`MATCH (start:OntologyClass {uri: $subject_uri})`. A question whose subject resolves to no
`OntologyClass` never gets to ask which page `explains` it. A corpus fix cannot move either row.

### No class exists for these subjects to bind to

I searched `rdfs:label` for `engine|canvas template|template` across all 17 files in
`setup/ontologies/*.ttl`. The only hits are the **DocPage rows themselves**
(`docs_corpus.ttl:22,32,64`) and the `idp_extension.ttl:8` header. Control: the same search for
`hazard` finds labels in `mesh_system.ttl` (1) and `safety_extension.ttl` (5), so the search does
find labels when they exist.

The nearest candidate, `mesh:CanvasSeed` (`mesh_system.ttl:560`, subClassOf `Archetype`), is the one
the canvas page **disclaims**: "This is not adding an archetype and not adding a verb."
(`adding-a-canvas-template.md:21`). Declaring it would make the page claim something false. Minting
an `Engine`/`CanvasTemplate` IRI is refused by ADR-0037's invented-IRI rule, so neither was done.

### Consequences

- **Roll #7 will not show "still fails on the corpus gap".** It will show these two rows failing on
  subject binding, as an ASK on `subject` or a route miss. A re-prime (Lane 1's) cannot change that,
  because nothing that is primed is missing.
- **The decision is ontological.** Either the mesh models "engine" and "canvas template" as classes
  a question can bind to, or DocPages become bindable subjects in their own right. That is the
  architecture seat's call. Until it is made, both rows are correctly unanswerable.

---

## Item 3 (re-registration): still waiting

Lane 1's roll #7 report has not landed. The newest roll on `origin/master` is #6 (`3aa25367`).
Nothing was done. If the engine re-registers the old `explain` spelling on restart, the registration
code is 74's, per the order.

## What I did not check

- ~~The census's `drawn` reading (above): cited, not re-measured.~~ Re-measured overnight: the
  engine carries the block, and the SSE stream does not (see the correction above).
- ~~Whether `pre_resolved_route_allowed` has other conditions~~ checked:
  `lineage_claim.py:79` is `return answers_something`, and `gateway.py:5004` is its only caller.
- Restate's `SafetyAcceptance` invocation history: not read. With zero dispatch lines and zero
  rows, it could only confirm, but it is still unread.
