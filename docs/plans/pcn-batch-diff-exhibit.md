# PCN batch-diff exhibit — IPCN25300X, prediction-from-source THEN run THEN diff

The seam-seal's predictions (`9628a8c`) are FIXTURE-shaped (`4=1+0+3`). The live notice is real and
different. Per the D4 discipline ("name the expected answer from the source before running"), this
prediction is derived from the LIVE graph/Neo4j, not the fixture. Run + diff follow; both halves banked.

## Seam decision (named on paper first — the last unsealed seam)

**Authoritative source for the request = the extraction (Neo4j doc-tools projection), NOT the mesh Jena
graph.** Reading the producer (`doc-tools/doc_tools/plugins/sustainment.py` `to_graph_queries`):
- Per-part `needs_review` is written to NEITHER graph — Neo4j carries only the DOC-LEVEL `n.needs_review`
  (`aug.needs_review`, True iff any part needs review or there are reasons); the Jena INSERT drops it.
  Per-part detail lives only in the `review.json` payload.
- **Therefore building the request from the Jena graph would silently default every part to
  `needs_review=False` — the exact unverified-extraction laundering §3 exists to prevent.** The graph is
  a RESOLUTION projection (subject IRIs); the extraction is authoritative for the parts + review flags.
- **Disagreement handling:** if doc-level `needs_review` is TRUE, the request MUST source per-part flags
  from `review.json` (not the graph). For IPCN25300X the doc-level flag is FALSE → no part needs review
  → the graph-derived part list is safe HERE (verified, not assumed).

**doc-tools replacement-IRI bug: NOT landed.** The live graph has 2 parts whose `hasReplacement` is a
MANGLED multi-MPN string (`SNSR01F30NXT5G,_NSR20F40NXT5G`). Harmless for THIS notice's disposition (a
PCN form/fit/function change proposes via `RuleFormFitFunctionChange`, which does not test replacement),
but flagged: do not trust `hasReplacement`-derived VALUES until the doc-tools fix lands.

## Live-derived facts (from Neo4j + Jena, 2026-07-24)

- Notice type: **PCN** (`ProcessChangeNotification`). Neo4j `doc_needs_review = FALSE`.
- **19 affected parts** (not the fixture's 4).
- Change categories: **Material, Process, Location, Testing** → change-classes `{form_fit_function
  (Material/Process/Testing), administrative (Location)}` — a MIX.
- Live ruleset `rules@2915ddb229e4`, evaluated for PCN + `{form_fit_function, administrative}`:
  - `RuleFormFitFunctionChange` (PCN, anyChangeClass form_fit_function) → MATCHES → `dispatchQualification`.
  - `RuleAdministrativeOnlyChange` (PCN, allChangeClass administrative) → change-classes ≠ {administrative}
    → NO match.
  - Single matching disposition → **all parts propose `dispatchQualification`** (MATCHED, no abstain).

## Prediction (write-down BEFORE running)

Scope decision (a BUSINESS input — BOM/AVL — not in the notice): **all 19 affected parts in scope** for
this exhibit (no arbitrary filtering; note that a real BOM would filter to a subset).
Residue decision: **TEST run** — `can_act` is dark (`ENABLE_DISPOSITION_AUTHZ` off → no-op True → tasks
mint with recipients:[], invisible), so this is not yet the demo artifact; clean up after. The real
demo-artifact run happens once `can_act` + grants are live on the git-rails.

Predicted `start_review` result:
- `counts`: **input 19, residue 19, filtered 0, auto_disposed 0, review_forced 0**.
- all residue `proposed_disposition = dispatchQualification`, `proposed_by_ruleset = rules@2915ddb229e4`.
- resolved subjects **19**, unresolved **0** (all 19 are components in the graph).
- batch **19** (can_act dark → all pass), status **STARTED**.

## Actual (live run 2026-07-24, `PcnReviewStarter/start_review` over real IPCN25300X)

A THIRD live-only bug first (the batch's whole point): `load_policy_rules` 500'd with `No module named
'rdflib'` — restate-analyst's image lacked rdflib (offline tests overlay `--with rdflib`, masking it).
Fixed (`d3b3c2e`, rdflib added to deps+lock), engine-a rolled, retried. Then:

```json
{"status":"STARTED","workflow_id":"pcn-review-IPCN25300X-alice","count":19,
 "ruleset_ref":"rules@2915ddb229e4",
 "counts":{"input":19,"residue":19,"filtered":0,"auto_disposed":0,"review_forced":0},
 "resolved":19,"unresolved":0}
```
Dispositions confirmed (deterministic proposer + the live ruleset): **all 19 → `dispatchQualification`**.

## Diff verdict — EXACT MATCH (composition proven on real data)

| field | predicted (from source) | actual (live) |
|---|---|---|
| input / residue / filtered / auto / review_forced | 19 / 19 / 0 / 0 / 0 | **19 / 19 / 0 / 0 / 0** ✓ |
| resolved / unresolved | 19 / 0 | **19 / 0** ✓ |
| ruleset_ref | rules@2915ddb229e4 | **rules@2915ddb229e4** ✓ |
| all proposals | dispatchQualification | **dispatchQualification (×19)** ✓ |
| count / status | 19 / STARTED | **19 / STARTED** ✓ |

The live batch matches the LIVE-DERIVED prediction on every field — not the fixture's `4=1+0+3`, which
it correctly does not resemble. Prediction-from-source, then execution, then diff: the D4 discipline,
and the chain is proven on the real notice. This run found the third live-only bug of the session
(`ruleset_ref` / `requested_by` / `rdflib` — none findable offline).

**Residue (TEST run, cleaned):** the run started workflow `pcn-review-IPCN25300X-alice` (suspended on
its ONE grouped HumanTask, recipients:[] — can_act dark). No disposition-state writes (those happen on
approve/fan-out, which did not run). Workflow invocation cancelled after; the real demo-artifact run
(kept tasks, real recipients) awaits `can_act` + grants on the git-rails.
