# Lane 1, 2026-09-26 — the docs walk's `NO_COMPATIBLE_VERBS`: registration is **correct**

**Answer to the dispatch's question: engine-docs registers `mesh:explain` against
`mesh:DocPage`, not against `DocExplanation`, and that registration is right. The fix is NOT a
registration fix, so per the order's conditional I am reporting rather than editing.**

The figure is reproduced exactly: **`DocExplanation` at 0.99, 3/3 fires**, on all three
"how do I" questions (0.96 on the abstain row).

## 1. The chain, every link measured

| # | link | how measured |
|---|---|---|
| 0 | The Weaviate `OntologyClass` index holds **26,240 rows across 8 domains and ZERO for DOCS** | censused live by `groupBy:["domain"]` — see §1a |
| 1 | So class recall returns nothing for a docs question and every such `/resolve` cold-starts | **9/9** `COLD START DETECTED` in engine-o's own stdout, all naming `MAINTENANCE` |
| 2 | The cold-start fallback reads the **singular** `request.domain`, never `domains` | `ontology_service/main.py:2445` — `execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)` |
| 3 | A domain read is scoped to **one domain's two graphs** | `main.py:565` — `VALUES ?__mesh_g { <http://internal/{DOM}> <http://internal/{DOM}_INSTANCES> }` |
| 4 | The DOCS graph declares **exactly one** `owl:Class` | `docs_extension.ttl:31` — `docs:DocExplanation a owl:Class`, and nothing else |
| 5 | `mesh:DocPage` is in the **MESH** graph, so a DOCS-scoped caller cannot see it | `mesh_system.ttl` is its only declaration |
| 6 | So the candidate pool is `['DocExplanation']` — **one option, and it is the verb's OUTPUT** | measured: `ncand=1`, `DocPage in pool: False` |
| 7 | The productive-option gate **refuses to filter** a pool it would empty | **9/9** `would have emptied the pool ... NOT filtering` in stdout |
| 8 | BAML picks the only enum member | `confidence_score=0.99`, deterministic across 3 fires |
| 9 | `DocExplanation` carries no verb: it is `rdfs:subClassOf mesh:Response`, and LEG 1 keys on `input_uri` | live pool: `DocPage` -> 2 verbs (both explain), `DocExplanation` -> **0**, `mesh:Response` -> **0** |

**A 0.99 here is not confidence. It is a single-candidate enum.** The score measures nothing
about fit, which is why it reads as a strong signal and is the opposite of one.

## 1a. The index census, and the loop it closes

| domain | rows in `OntologyClass` |
|---|---|
| SUSTAINMENT | 13,147 |
| MAINTENANCE | 13,051 |
| MESH | 14 |
| PROGRAM_FINANCE | 8 |
| DATA_ENGINEERING | 8 |
| PRODUCTION_COST | 6 |
| PORTFOLIO_PLANNING | 5 |
| MANUFACTURING | 1 |
| **DOCS** | **0** |

`mesh#DocPage` **is** indexed — under `domain: "MESH"`. Vectors are present and 768-dimensional
(checked via REST `include=vector`; see §5.4 for the detector that said otherwise and was wrong).

**So the vector path is consulted, runs correctly, and correctly returns nothing.** The DOCS
domain's only class is `DocExplanation`, a response shape, and doc-tools **deliberately excludes
response shapes** from the index it builds (`doc_tools/assets/ontology_assets.py:373`,
`_RESPONSE_SHAPE_ROOTS`, transitive `rdfs:subClassOf+`). The index is empty for DOCS *on purpose*.

**The defect is that the fallback applies a different rule than the index.** It offers the one
class the index refused. The two halves of the fix are therefore not two independent good ideas:
excluding response shapes makes the fallback *agree* with the index, at which point the DOCS pool
is empty — and spanning MESH is what then makes it non-empty with the right class.

**The root set has TWO roots, not one:** `mesh#Response` **and** `mesh#Archetype`. Derived from
doc-tools' predicate, not typed.

## 2. Why this is not a registration defect

`agent_fleet/docs_agent/main.py:104-106` registers `input_uri = mesh#DocPage`,
`output_uri = docs#DocExplanation`. That is the correct direction: a verb's input is what a
caller must already have, its output is what the verb returns. `docs_extension.ttl`'s own
header says the input end is deliberately `mesh:DocPage` from `mesh_system.ttl` and is not
restated locally.

**`docs:DocExplanation rdfs:subClassOf mesh:Response`** (`docs_extension.ttl:31-32`). A
`mesh:Response` subclass can never be a resolved subject *by construction*, because no verb
takes one as input. Re-pointing the registration at `DocExplanation` would invert the verb and
break the half that currently works.

## 3. The gate that was built for this and could not fire

Step 1.56's `elif not _productive:` branch degrades open and says why: an empty served-set is
"the signature of a served-set computed against the wrong domains", and emptying the pool would
"take routing down for every caller".

**That premise is false in this case, and the case is not exotic.** Here the served-set is
right, the single candidate is genuinely unserved, and the gate hands the caller the one dead
end it exists to remove. The branch cannot distinguish *"my scope is wrong"* from *"this domain
genuinely offers nothing answerable"* — and the second is what a thin domain graph produces.
The comment at `restate_analyst/main.py:601-604` cites the same log line from the portfolio
defect at **10 candidates, 0 served**; at **1 candidate, 0 served** it fires for the opposite
reason and reads identically.

Its degradation is also invisible to the artifact on this path: `_gate_excluded` is populated
only inside the `if _productive and _unproductive:` arm, so when the gate degrades open it
records **nothing** structured. The reader of the card cannot see that a gate declined to act.

## 4. The two callers disagree, and they get different subjects

- The **UI** path sends both: `payload["domains"]` and `payload["domain"] = _domains[0]`
  (`restate_analyst/main.py:612-614`). The singular arrives, the fallback is DOCS-scoped, and
  the subject is `DocExplanation`.
- **My first probe** sent the plural alone. The fallback ignored it, scoped to the defaulted
  `MAINTENANCE`, and returned `mil#DitaNode` / `MaintenanceReferenceOntology/*` with no docs
  class anywhere. **Nothing about docs was measured, and the result looked like a finding.**

Same endpoint, same question, two subjects, decided by which of two fields the caller filled.

## 5. Corrections to my own earlier claims

1. **This morning's census owed-item #1 — "a caller identity on `/find_compatible_verbs`, now
   measured as the blocker for the whole docs feature" — is WRONG for these four rows.** LEG 3
   was never the blocker; the subject never reaches a verb lookup that could succeed. §7 of that
   report flagged the uncertainty, and it is now resolved against my own framing.
2. **"Every candidate scores 0" was my reader, not the engine.** The SPARQL-fallback candidate
   shape carries no `score` key at all; my probe did `c.get("score", 0)` and printed the default.
   A Weaviate-path candidate does carry one (positive control: `WorkInstruction`, `score=0.7`).
3. **"The resolver invents a URI outside its candidate set" was also my reader.** I truncated the
   printed candidate list to the first few; the resolved `Procedure` was candidate #9 of 15+. The
   select-from-authorized-set invariant held. I was one print-width from filing a fabricated
   integrity defect against the resolver.
4. **"No class in the index carries a vector" was a fourth reader defect, caught before it
   shipped.** GraphQL `_additional{vector}` returned nothing for every domain I asked, which read
   as a total absence and would have pointed the fix at the embedding pipeline. A second detector
   on a different surface — REST `include=vector` — shows 768-dim vectors present. The first
   detector was never positive-controlled; the second one is what a positive control looks like.

**Four instrument defects in one session, three of them caught only by re-asking on a different
surface.** Each one individually produced a plausible, specific, wrong finding. That is the rate
to assume, not the exception to note.

## 6. The fix, stated as a choice and not taken

Not registration. Candidates, in the order I would rank them:

1. **The cold-start fallback must honour `domains`, and should span the MESH system graph.** It
   is the only path that runs while Weaviate is cold — which is always, today — and it silently
   narrows to one defaulted domain. The archetype classes that every domain's verbs take as
   inputs live in MESH, so a domain-scoped pool structurally cannot contain them. This alone puts
   `DocPage` in the pool and the walk answers.
2. **A `mesh:Response` subclass must never be offered as a resolved subject.** Derivable from the
   TTL, general, and sealable — not a docs fact. The Response-subclass population spans
   `cost_extension.ttl` (~10), `finance_extension.ttl` (~7+) and `docs_extension.ttl` (1), so this
   is a class of latent dead ends rather than one row.
3. **The degrade-open branch owes a distinction and a structured record.** At minimum emit
   `_gate_excluded` with `disposal: "retained"` so the dead end reaches the artifact.

**(1) and (2) are independent and both worth having:** (1) makes the right subject reachable,
(2) stops the wrong one being offered when it is not.

## 7. The census, and the seal the defect walked past

**Three fires of the four docs rows: `0 pass, 4 fail`, rc=1 each, every row
`route_status='no_match'` / `fell back: no_compatible_verbs`** — the walk reproduces through the
census, because the supervisor sends both `domain` and `domains` so the singular arrives either
way.

**The three fires are byte-identical** (same md5 over the FAIL / `route_status` / `fell back`
lines). That matters for what comes next: this is a deterministic before-column, so a single
green fire after the fix is evidence rather than a coin toss — and equally, a *partial* pass
after the fix cannot be waved off as flake.

**`tests/routing/test_response_shapes_are_not_groundable.py` already exists and already carries
both roots.** Its arms cover the registration direction
(`test_no_declared_response_shape_is_used_as_an_INPUT`,
`test_every_registered_OUTPUT_is_a_declared_response_shape`). **Not one of them asserts that a
response shape never reaches a CANDIDATE POOL.** The seal is complete about registration — the
half that was already correct — and silent about recall, which is the half that failed. That is
why a seal named for exactly this defect was green while exactly this defect shipped.

## 8. What I did not verify

- **That the fix makes the walk draw.** The build is in flight as this is written; the census
  re-fire is what decides it, and it is not yet run.
- **Why the MESH graph holds 14 rows where the prime is described as writing 12.** Noted, not
  chased; it does not change any conclusion here.
- **The other domains' graphs.** I measured DOCS. PROGRAM_FINANCE (8), DATA_ENGINEERING (8),
  PRODUCTION_COST (6), PORTFOLIO_PLANNING (5) and MANUFACTURING (**1**) are all thin enough that
  the same single-candidate-enum failure is plausible for them, and I did not fire any of them.
  **MANUFACTURING at one indexed class is the same shape as DOCS at zero** — my own positive
  control returned exactly that one class, which I read as "the path works" rather than as the
  warning it also was.
- **`_served_class_uris`' own correctness.** I observed 0 served for `DocExplanation` and accepted
  it because the graph shape independently explains it; I did not audit the function.
- **The stale comment at `main.py:~2560`** claiming "every class candidate comes back with
  `score: None` because hybrid search is running lexical-only". Measured false — my MANUFACTURING
  control carried `score=0.7`. That comment is load-bearing for
  `_preempted_subject_is_unanswerable`'s design rationale. Flagged, not fixed.
