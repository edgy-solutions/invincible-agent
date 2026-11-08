# Audit of lane/saf work against the architect's standing rule (2026-10-30)

from: invincible-agent/lane/saf. Read-only: no code, commit or PR touched. Tree read: ia-saf
(`lane/saf-adr-0063-safety-and-slice`) for Engine S; `origin/master` for #158; `origin/lane/saf-safety-finding-review-workflow` (f1c5b0d8) for #160.

## Counts

| bucket | items |
| --- | --- |
| (i) violation in shipped code | 4 |
| (ii) test fixture or seal that legitimately names a case | 5 |
| (iii) read from config and only echoed | 4 |
| (iv) undecided | 11 |
| form-only matches naming none of the rule's nouns (mechanism, not bucketed) | 4 sites |

## Census: forms used, with the positive control

Vocabulary is DERIVED, not typed: `scratchpad/vocab.py` reads domains.yaml, every task_kinds row
(kind, accepts), every workflow id, groups.yaml, the decision-table names and the audience keys in
task_grants.yaml (106 words, plus rejected, returned_for_rework, concurrence, risk_acceptance, risk_redraft, safety-engineers).

Scope files: `agent_fleet/safety_agent/{main,safety_critical,entities,measures,graph_shape,instances,slots,matrix,failure_source}.py`, `setup/safety_critical_seed.py`; tests of #125, #128, #158 and #160's seal.

- F1 quoted vocabulary word: `grep -nE "[\"'](<ALT>)[\"']" <scope>` : 6 lines, 5 sites.
- F2 comparison to a string literal: `grep -nE "(==|!=)\s*[\"'][A-Za-z_:-]+[\"']|[\"'][A-Za-z_:-]+[\"']\s*(==|!=)"` : 9 lines.
- F3 membership against a literal collection: `grep -nE "\bin\s*[\(\[\{]\s*[\"']"` : 1 line (an env flag).
- F4 module constants bound to str or a collection of str: `grep -nE "^[A-Z][A-Z0-9_]*\s*(:[^=]+)?=\s*[\(\[\{\"']"` : 30 lines.
- Beyond the forms: read `review_request` construction (measures.py:498-531) and the data sources by hand, because F1 over the vocabulary misses a kind built by f-string.

POSITIVE CONTROL. A copy of slots.py in the scratchpad had `if kind == "hazard_link_review":` appended; F1 caught it
(line 146 of the copy). The first run of the control caught NOTHING: the vocabulary file had CRLF endings from the Windows
python, so every alternative ended in a carriage return. Stripped with `tr -d '\r'` and re-run; the real census was run
only after the control passed. The copy was deleted. Nothing in the repo was planted.

LIMITS. F1 sees only vocabulary that already exists in policy; a literal naming a case no policy file knows yet is seen only by F2 to F4, which are shape-based and noisier. Docstring and comment mentions (e.g. "SUSTAINMENT plane") are excluded: prose, not code.

## (i) Violations in shipped code

| # | file:line | what | fails | config home | days |
| --- | --- | --- | --- | --- | --- |
| I1 | measures.py:530 | `"reason_required": ["accepted", "rejected"]` restates the task kind's own declaration in the card payload | 4 (a copy of the served declaration), 2 | the composed task-kind row (`reason_required`) served to the card; the engine returns facts, the gateway fills it from the kind | 0.5 |
| I2 | measures.py:509 | `kind: f"risk_acceptance_{level.lower()}"`: the engine restates the kind template that `safety_acceptance_direct.yaml` and the selection tables declare (`risk_acceptance_{level_slug}`) | 4, partly 2 (a new level needs a kind row and this prefix agreeing) | a column on the matrix row beside `acceptanceAudience` (ttl), or the selection table served; engine passes the level only | 0.5 |
| I3 | measures.py:320, 508, 510 | `risk-acceptance-{hazard}-{slug}` case key and `risk-acceptance-{hazard}` task id mirrored from `iagent_pure.acceptance_request` (sealed equal, but a copy) | 4 | the minter owns it; the wire carries the subject facts and the gateway mints. Touches Lane 1's gateway and iagent_pure | 1.0 |
| I4 | entities.py:163, 323, 338, 371, 405, 433, 438; read at measures.py:129, 232 and instances.py:111-120 | Hazards, safety-critical items, work orders, write-ups and failure records are in-code tuples and are the production data source. A deployment cannot add a hazard or a critical part without a code change | 3, 4 | the graph, read through the mesh (an SDK read) with the demo fixtures moved to an overlay | 5.0 (the same read-back as the Hazard-node follow-on in ADR-0063 s5; shared, not additive) |

Cross-lane: I1 and I3 need Lane 1 (gateway fills the card, minter). I4 needs an SDK read verb (ca) and the Topaz gate.
The comment at safety_critical.py:25-27 says the records are interim ("until the graph read ... replaces it"); that is an earlier ruling, see below.

## (ii) Seals and fixtures that legitimately name a case

- T125-seed: tests/safety/test_the_safety_critical_seed_is_match_only_and_idempotent.py:76,127-141 names SUSTAINMENT and PRODUCTION_COST as fixture domains (the cross-domain control needs a second domain).
- T125-rule: test_the_safety_critical_rule_is_the_only_decision.py:39 uses PRODUCTION_COST as the other-domain control.
- T158-door: test_seal_the_can_drop_door_fails_closed_at_every_site.py names `pcn`/`pdn` kinds and a registry built in the test (a fixture, as the seal needs a kind that is gated and one that is not).
- T158-export: test_seal_review_export_cells_catalogue_and_corrections.py names `finance`, `pcn`, the CATALOGUE sets and the RUNGS list. The catalogue sets are a deliberate copy ("written here, not read from the subject"). Tension with test 4 noted for the architect, not decided here.
- T160-seal: test_the_safety_finding_review_is_declared.py:34-35 pins `_KIND` and `_OUTCOMES` on purpose (the expectation must not be read from the subject).
- #128 (test_no_automated_path_clears_safety_critical.py): zero hits.

## (iii) Read from config and only echoed

- E1 measures.py:429-461, matrix.py:120-126: the acceptance audience is read from the ratified matrix ttl and echoed into the card.
- E2 setup/safety_critical_seed.py:46 `DOMAIN = rule.DOMAIN`: echo of the rule's constant (the constant itself is U1).
- E3 main.py:467: `id_namespaces` echoes `ID_NAMESPACES` onto the registration (the constant itself is U3).
- E4 #160's rows: `safety_finding_review.yaml` (workflow), the overlay task-kind row and the `task_grants.yaml` row are the configuration. They name the case in a row, which is what the rule asks.

## (iv) Undecided

- U1 safety_critical.py:36 `DOMAIN = "SUSTAINMENT"`, :45 `if domain != DOMAIN: return []`, and the part list coming from `SAFETY_ITEMS`. Ruled 2026-10-28 (equality seal against main.py). New rule vs ruling: see conflicts.
- U2 main.py:136-137 `OWNER_PERSONA`, `DOMAINS`: the engine's own registration scope, sealed to exist in policy (test_engine_scope_exists_in_policy). Is an engine's registered scope config or identity?
- U3 main.py:335 `ID_NAMESPACES = ("HAZ-", "CSI-", "MIT-")`. Ruled 2026-10-12 as "declared in its registration"; it is declared, but in code.
- U4 Engine-internal enums: measures.py:78, 80 (`verified_in_field`), :132, :352, :411 (`not_assessed`, `closed`, outcome `not_assessed`). Status words are not among the rule's nouns, but `closed` refusing a draft is a behaviour keyed on a status literal (ruled 2026-10-09).
- U5 measures.py:92, 94, 120 `scope` compares `fleet`/`platform`/`tail`, a second copy of the enum declared in main.py's VERBS and slots.py `_SCOPE_REFERENT`.
- U6 graph_shape.py:29-36 `LABEL`, `ONTOLOGY_PROPS`, `UNDECLARED_PROPS`: derived and pinned to the ttl by a test, inert, and not read at runtime.
- U7 safety_critical_seed.py:49-53 Cypher `Component`, `mpn`, `safety_critical`: platform graph-schema names shared with promotion_stores.
- U8 measures.py:513 `"requested_by": "engine-safety"` duplicates `COMPONENT` in main.py:51.
- U9 #160's seal loads the workflow by file path and composes task kinds from a hard-coded `overlays/sample/task_kinds` path. Test 4 result below.
- U10 #158 door seal: `SITES` is a hand-written list of four routes, a census by name; a fifth site would not be found.
- U11 ADR-0063 s5 text: "the slice carries `service_due_unreleased`" names the predicate as slice behaviour. Per the rule it is the first row of a rule table, not a constant; the s5 days (1.0 landing) assume code.

## Form-only matches (not bucketed)

instances.py:231 (`exact`/`normalised` match tiers), slots.py:113 and :143 (`spoken` slot kinds), main.py:360 (env flag). They name none of the rule's nouns.

## Test 4 for #160

- Workflow: the seal uses `workflow_definition.load_workflow_definition`, the same function the server's `load_all_workflows` uses, so the loader is not a copy. But it reads the repo file by path; the server resolves through `candidate_definition_dirs` (repo or `/app/policy/workflows`). Same loader, different resolution.
- Task kind: the seal calls `iagent_mesh.task_kinds.compose(policy/task_kinds, [overlays/sample/task_kinds])`, the same function `human_tasks.py:853` calls with `_DECL_DIR` (human_tasks.py:767) and overlay dirs from `TASK_KIND_OVERLAY_DIRS`. Same composer; the overlay dir is hard-coded in the seal instead of coming from the env var the server reads.
- Grant row: `task_grant_sync.load_audiences`, the sync's own loader.
- Verdict: no copy of a registry, but the seal does not go through the server's accessor (`human_tasks`), so it does not prove the server serves these rows. A one-hour fix: drive `human_tasks`' accessor with the env set. Left as U9, not fixed.
- Rows are config, not branches: adding a second finding workflow is a new workflow yaml, task-kind row and grant row, no code. The one code step ADR-0063 still needs is U11 and the Hazard-node follow-on (I4).

## Conflicts with earlier rulings (decision left to the architect)

1. 2026-10-28, `DOMAIN = "SUSTAINMENT"` in safety_critical.py accepted with an equality seal. The new rule does not obviously supersede it: the ruling picked a duplicated literal over a shared read for image-shape reasons, which is not what the rule's tests address. Fails test 3 if "a deployment adds a domain's critical parts without code" is meant.
2. 2026-10-28/29 (Q5 "agreed"): "the rule stays a static list". That is a list of parts in code; the new rule would make it a registry row or graph property. Same item as U1.
3. The interim ruling that Engine S answers from in-code records "until the graph read replaces it" (safety_critical.py docstring; s5 estimates exclude the read). I4 is that interim, now a violation of tests 3 and 4 if the rule is retroactive.
4. 2026-10-12 (Q3): id namespaces "declared in its registration" (U3): satisfied in form, in code.
5. 2026-10-29 (Q6): "service_due_unreleased" as the slice predicate (U11): a ruling that names a specific case; the rule says it is the first row.
6. 2026-10-09: a closed hazard refuses a draft (U4): keyed on a status literal.

## Sizing summary

(i) total 7.0 days if done separately, 2.0 without I4 (I1 0.5, I2 0.5, I3 1.0). I4 is 5.0 and is the same work as ADR-0063's Hazard-node follow-on.
