# Overnight 2026-09-27 — items 1 and 3 landed, and the docs empty document is **not** the MESH blindness I predicted

> ⛔ **THE BEST FINDING IS A CORRECTION TO MY OWN ROLL #5 REPORT.** §4.1(c) of
> `2026-09-27-roll-5-fired-revision-153-…` named the MESH scan blindness as the cause of
> `docs-what-is-an-archetype` drawing 0 rows under `sections`. That was the outcome I *predicted in
> the arming doc*, and I read the result as confirming it without probing the payload. Probed
> tonight: the docs answer fails at **capability matching**, upstream of anything MESH scoping
> changes. Item 3's fix is still correct and still ships — but it will **not** turn that row green,
> and the arming doc's prediction must not be reported as having been borne out.
>
> The pattern is the one I have a memory entry for and walked into anyway: **verify the figure that
> agrees with you.** A prediction made before the roll is the most pre-authorised claim in the room.

Repo `6cd4c14a` + working tree. Fleet `55dc861` (revision 153) throughout — **no roll fired tonight
yet**; everything below is measured against the fleet roll #5 left running.

---

## 1. Item 1 — the seal derivation, the claim's scope, and the sheet

### 1.1 The three docs defects, with owners

| # | defect | owner | state tonight |
| --- | --- | --- | --- |
| (a) | `expect_verb: mesh_explain` in four census rows — a spelling `verb_names` cannot produce | **mine** (the instrument) | **FIXED**, sealed, 3 fires, 3/3 mutants |
| (b) | the disposition changes: two rows ask where the sheet says draw, one draws where it says abstain | **re-diagnosed — see §3**; not three defects and not a content leak | named, not fixed |
| (c) | `docs-what-is-an-archetype` draws 0 rows under `sections` | **re-diagnosed — see §3**; owner is the docs answer's capability match, not the MESH scan | named, not fixed |

### 1.2 (a) is fixed, and the fix is confirmed against the live fleet

`verb_names` (`src/iagent_pure/walk_census.py:339`) offers three spellings of the verb an answer
used: the IRI's local segment, the `_camel_to_snake` of it, and the last path segment of
`handled_by.endpoint_url`. Every one of them is taken **after** splitting on `#`, `/` or `:` — so
the prefix is gone from all three by construction, and `mesh_explain` is producible by nothing.

The sheet agreed with itself everywhere else: all 16 non-docs rows carry a bare name. I checked the
obvious objection rather than assuming it — `cost_rate_comparison` and `fin_burn_rate` *look*
prefixed, and `cost`, `fin`, `docs` and `safety` **are** all registered CURIE prefixes
(`setup/ontologies/*_extension.ttl`). They are not prefixed here: the wire carries
`mesh:costSupplierConcentration`, so `cost` is inside the local segment and the snake form is the
bare name. Had I sealed on "no expectation starts with a registered prefix", the arm would have
false-redded 16 correct rows.

**Fixed** — four rows, `mesh_explain` → `explain`. Confirmed live: the `verb [...] lacks ...` line
is **gone from all four rows** where before it was on every one.

### 1.3 What the seal for (a) could and could not be

Two things I tried and discarded, both recorded because the reasoning is the reusable part:

- **A prefix-derived predicate** — killed by the measurement above.
- **Cross-checking `expect_verb` against the TTL's declared verbs** — killed by a standing ruling
  in `mesh:explains`' own `rdfs:comment` (`setup/ontologies/mesh_system.ttl:747`): *"The check is a
  SPARQL ASK against the deployed graph and never a grep of a TTL — those two came apart three
  times in eight days."*

And the general limit, which is the honest part: **no offline check can rule a sheet expectation
unproducible**, because every string is the local segment of *some* IRI (`mesh:mesh_explain`
produces `mesh_explain`). So the seal splits in two, and neither half pretends to be the other:

| arm | subject | what it holds |
| --- | --- | --- |
| `test_verb_names_NEVER_RE_ATTACHES_THE_PREFIX_IT_STRIPPED` | the **helper** | no spelling it offers is `<prefix>_<local>`, quantified over the **complete** delimiter set `{#, /, :}` read off its body — plus the positive half, that the bare local IS offered, so it is not a bare absence assertion |
| `test_EVERY_DOCS_ROW_EXPECTS_A_SPELLING_THE_EXPLAIN_VERB_ACTUALLY_PRODUCES` | the **sheet** | every DOCS row's expectation is in `verb_names({"action": {"iri": "mesh:explain"}})`, **derived from the row set** so a fifth mis-spelled row reds on the commit that adds it |

Measured red **before** the fix: `1 failed, 17 passed`, failing exactly at the sheet arm with
`4 DOCS row(s) expect ['mesh_explain'], and mesh:explain produces ['explain']`. The helper arm was
green before *and* after — **that split is the proof the defect was in the sheet and not in
`verb_names`**, and it is also why the helper arm needed a mutant before I could call it a seal at
all. Three fires after: `18 passed` ×3.

Mutants, each killed **by its named arm** with the expected assertion fragment present:

| mutant | killed by | fragment |
| --- | --- | --- |
| M1 one row reverts to the mis-spelling | the sheet arm | `DOCS row(s) expect` |
| M2 `verb_names` re-attaches the prefix it stripped | the **helper** arm | `re-attached the prefix it stripped` |
| M3 the row filter selects nothing | the sheet arm's population floor | `this seal is asserting nothing` |

M2 is the one that mattered: until it ran, the helper arm was green before the fix and green after,
which is a no-op defence with nothing showing it was wired to anything.

### 1.4 The "not on the wire" claim, narrowed in all four homes

Roll #5 established the claim's true scope: `accepted_slots` is absent from the supervisor
**wrapper** and present in the **envelope** (`slot_disposition.py:634`, `dict(accepted or {})`, on
every ask). The correction has as many homes as the claim had, and grepping the claim's *subject*
rather than its struck wording found four:

| home | what changed |
| --- | --- |
| `tests/routing/test_a_menu_on_the_wire_can_be_answered.py` (docstring) | done in the previous window |
| `agent_fleet/presentation_agent/main.py:1251-1266` (`_reroute_fields`) | the ⛔ paragraph now says the scope is the **wrapper**, with the wrapper/envelope table and the knowledge-vs-value distinction |
| `agent_fleet/presentation_agent/main.py:271` (`_wrapper_field`) | "not on the wire" → "not on the **wrapper**", naming the envelope as a place the field may still be |
| `docs/measurements/2026-09-26-…-the-docs-fallback-is-the-only-path-by-construction.md` §3.2 | heading corrected in place with a dated note |

And the **sibling written in the same act** — §3.1 of that same doc, which claimed the AST-derived
arm meant "a third producer reds on the count". That was false when written: the third producer
already existed and the arm was green over it. It is the hardest home to find precisely because
fixing §3.2 reads as having handled the class.

---

## 2. Item 3 — MESH in the class scan's scope

`class_scan_scope_domains` (`agent_fleet/ontology_service/main.py:1150`) is a **new module-level
function**, and it is one for the reason `cold_start_fallback_domains`' own docstring records: with
the rule inlined in the handler, the seal had to mirror it, and a mirror is not a seal — disabling
the MESH append left the fallback's arm green (mutant B, 2026-09-26). It **calls**
`cold_start_fallback_domains` rather than restating the rule, so the two paths cannot drift.

**The dispatch said `near_vector`; there is no `near_vector` in this engine.** The path is
`collection.query.hybrid()` with a `bm25()` fallback (`:1209`/`:1222` after the edit). Reconciled,
not adopted.

⚠ **The naive reuse would have been a regression wearing the fix's clothes.**
`cold_start_fallback_domains(None, None)` returns `["MESH"]`, correct where a graph scope is
mandatory. Here an empty scope means `filters = None` — read the **whole index** — so passing that
through would narrow a whole-index read to MESH alone. Empty in, empty out.

**The class has one member, and the exemption is checkable.** The engine's other hybrid/bm25 site,
`_predicate_hybrid_search_sync`, searches the **Predicate** collection and already carries an
escape arm for platform rows (`Filter.by_property("domains", length=True).equal(0)`). An arm asserts
that escape arm is still there, because the exemption is only true while it is.

Seal: `tests/routing/test_the_class_scan_spans_mesh_for_a_scoped_caller.py`, 6 arms, green ×1.
The wire arms assert the **request** — the `filters` object handed to `.hybrid()` — because a
recording double asserts the writer and never the store, and a row-count arm would be scripted by
the double and pass under any filter at all.

One instrument defect worth recording: my first version built the expected filter from an
independently imported `weaviate.classes`, while the `ontology_main` fixture **stubs** that module.
The production call recorded the stub's `('contains_any', 'domain', ['DOCS','MESH'])` tuple and the
arm redded against a real `_FilterValue` — with the **right values in both halves of the diff**. A
red that accuses production of a defect the test invented. Fixed by building the expectation through
the module under test's own `wvc`: derive the object from the subject's imports.

Mutants, 4/4 killed by their named arms:

| mutant | killed by | note |
| --- | --- | --- |
| M1 no MESH append — **the pre-fix state** | the scope arm **and** the wire arm | this is the unfixed-code measurement; the fix was written before the seal, so it was owed |
| M2 the naive pass-through | both unscoped-caller arms | the regression above |
| M3 **the mirror hazard** — rule back inline, helper left correct | the wire arm only | proves the wire arm reads the request, not the helper |
| M4 the predicate search loses its escape arm | the exemption arm | the exemption cannot outlive its premise |

---

## 3. ⛔ The re-diagnosis: (b) and (c) are one defect, and it is not MESH scoping

### 3.1 What the live probe measured (fleet `55dc861`, revision 153)

| row | disposition | reason | archetype | options |
| --- | --- | --- | --- | --- |
| `docs-how-do-i-add-an-engine` | `abstain` | `['empty', 'no_verb_in_scope']`, slot `subject` | `ELICITATION` | **0**, `option_source: ''` |
| `docs-what-is-an-archetype` | `abstain` | *"no registered capability's contract is satisfied by this payload"*, then per archetype *"no typed contract for KNOWLEDGE_DOCUMENT; and output_uri matched no capability"* — same for `PERIOD_SERIES`, `GROUPED_REVIEW`, `CONTRIBUTION_RANKING` — then `'no rows'` | every one tried, each failed | — |
| `docs-how-do-i-roll-a-service-abstains` | `abstain` | identical reason list | identical | — |

All three resolve `mesh:explain`, and all three are offered the **same six-class pool**
(`mesh#DocPage`, `AgentTask`, `Archetype`, `CatalogAssetQuery`, `CatalogScopeQuery`,
`DatasetAnalysisRequest`) — identical across rows, which is the cold-start fallback serving, as
roll #5 diagnosed correctly.

**So nothing returned the `explains: none` page.** (b) was described as a disposition change and a
possible content leak; it is neither. Every docs row abstains, and the two that get past slot
filling abstain at the **same** step, with the **same** reason, for the **same** cause. (b) and (c)
are one defect.

### 3.2 The defect, censused rather than sampled

`agent_fleet/presentation_agent/capabilities.py` holds **30 registry entries**, each with a unique
`subject_uri`. **None of them is `mesh:DocPage`, and none carries a `docs:`-domain subject at all.**
That is a census of the table, not a sample of it: 30 entries, 30 distinct subjects, zero matches.

`mesh:DocPage` is what `mesh:explain` declares on both sides of its contract, and it is the first
member of the pool the three rows are offered. The reason string reads as an accusation against a
value — *"output_uri matched no capability"* sounds like the uri was wrong — but the comparison it
names finds nothing because **the table has no row to find**. The failure is a registry gap and it
is class-level: every docs answer that reaches capability matching fails, under all four
archetypes, for the same missing declaration.

There is a prior instance of exactly this class **in this same file**, at `capabilities.py:62-64`:
*"THE WRITE TABLE HAS HAD THIS AND THIS TABLE HAS NOT."* The `docs:` prefix was added to the prefix
map after that; the subject table was not extended to match.

### 3.3 The three defects, with owners

| # | defect | owner | state |
| --- | --- | --- | --- |
| (a) | census rows expect `mesh_explain`, a spelling `verb_names` cannot produce | **mine** (the instrument) | **FIXED**, sealed, 3 fires, 3/3 mutants (§1) |
| (b+c) | no capability entry declares an archetype for `mesh:DocPage` — no DOCS subject is registered at all, so every docs answer abstains at capability matching | **presentation_agent's registry** — *or* docs_agent, if the intended fix is for its payload to satisfy an existing contract such as `mesh:KnowledgeRetrievalResponse`. **Which of the two is a design call and I am not making it.** | named, censused, **not fixed** — not mine |
| (d) | an `ELICITATION` card on the docs path with **zero options** and `option_source: ''` | the empty-menu guard's reachability on the docs path — the carried item, which **fired for real tonight** | newly measured, not fixed |

(d) is the one worth flagging loudest: it was on the carried list as a *question* about whether the
guard could be reached, and the answer arrived as a live card with an empty menu. An elicitation
that asks for a slot while offering nothing to pick is a dead end the caller cannot leave.

---

## 4. A seal had pinned the defect

`tests/routing/test_the_pool_reaches_the_universal_referent.py` carried an arm named
`test_the_docs_census_still_has_exactly_four_rows_all_expecting_mesh_explain`, whose body was:

```python
assert len(_DOCS_ROWS) == 4, sorted(r.id for r in _DOCS_ROWS)
for row in _DOCS_ROWS:
    assert row.expect_verb == "mesh_explain", row.id
```

and whose docstring opened *"Read from the source, not restated as a count"*. Both halves of that
sentence are true of the **count**. The **spelling** was a restated literal standing next to it,
borrowing the same sentence's authority — and it was the mis-spelling. The arm had been green over
defect (a) for as long as (a) existed, for the plain reason that it **agreed with it**, and it is
the 39th red in tonight's regression run: it fired on the *repair*.

Repaired by derivation rather than by correcting the literal: the arm now computes
`verb_names({"action": {"iri": "mesh:explain"}})` and asserts membership, with a population floor
so an empty offer cannot pass as agreement. Renamed, because the name carried the claim too, and
the neighbouring parametrized arm's docstring assertion *"All four rows declare
`expect_verb: mesh_explain`"* was corrected in the same pass — it is the same claim in a second
home. **Mutant:** row `353` reverted to `mesh_explain` → red at the renamed arm with the expected
fragment (`does not produce`), restored, `grep -c 'mesh_'` back to 0, 40 passed.

The reusable part: **a seal on a value must call the producer of that value.** A hard-coded copy of
the thing you are guarding is not a guard, it is a second instance — and the day the original is
fixed, the copy reds and reads like a regression.

---

## 5. What I did not verify

**Item 3's fix will not turn `docs-what-is-an-archetype` green, and the arming doc's prediction was
not borne out.** The MESH scan fix is correct, sealed and shipping, and the empty document it was
written for has a different cause. The arming doc's claim must be reported as *refuted by
measurement*, not as confirmed.

**The `output_uri` probe measured nothing, and its own control is what said so.** It dumped every
key path of the live answer for `docs-what-is-an-archetype` and for `finance-burn-rate` — a card
known to project — and `output_uri` is **absent from both**, with no `*uri*` leaf anywhere in either
envelope. So the key is not a response field at all, the absence in the docs answer says nothing
about the docs path, and the question *"absent, or present and unmatched"* was the wrong question.
The control was the whole value of that probe: without it I would have read "ABSENT" as a finding.
The right instrument was the **registry**, read statically — §3.2 — and that is where the answer was.

**I have not verified what the correct fix for (b+c) is.** Adding a `mesh:DocPage` entry and
changing the docs payload to satisfy an existing contract are different designs with different
blast radii, and the registry's own comments record that its archetype assignments are sometimes
*"KNOWLEDGE_DOCUMENT by ruling, not by fit"* (`capabilities.py:524`). That is the owner's call.

**The six-class pool is a sample of one read.** It was identical across three rows in one pass; I
have not fired it three times, so "the fallback serves every docs caller" is supported for those
three questions at that revision and is not a census of the docs path.

**Item 3's recall delta across MAINTENANCE (three fires before/after) is not run** — the dispatch
asks for it and this report does not contain it.

### 5.1 The regression comparison, by identity

`docs/plans/suite-signal-session.md` records the failure census as **per-file counts at `42a4afa`
over the full suite**. My run was a four-target subset of a different tree. Reading "39 failed"
against that table's routing rows would have compared two different populations by count, so the
before-state was measured **here**: mutant M1 (no MESH append) applied to this tree, same targets,
identities saved, replacement restored in a `finally`.

| set | identities |
| --- | --- |
| common to both | **38** — `test_classify_route.py` 29, `test_phrasing_independence.py` 7, `test_adr0019_engine_o_contract_a.py` 2 |
| BEFORE only | 2 — both arms of the new MESH seal. This is M1's kill, seen from the other side: the fix is what makes them green |
| AFTER only | 1 — the stale pool seal of §4, since repaired |

**The MESH change introduced zero new failures, by identity.** The 38 are byte-identical across the
two runs.

⚠ Two things this comparison says that a count would have hidden. First, `test_classify_route.py`
contributes **29** reds here where the recorded census says 23 — a different commit and a different
target set, and I have **not** chased which. The figure in that plan should not be cited for this
tree. Second, my own comparison instrument nearly reported the opposite of the truth: the before
file was written by Python (`write_text`, so CRLF on this box) and the after file by `sort` (LF), and
`comm` duly reported **0 identities in common** — a result that reads as *"the change replaced the
entire failure set"*. Normalizing gave 38. A diff is a claim about an encoding before it is a claim
about a population.

---

## 6. State at the end of the window

Nothing is committed. Working tree carries items 1 and 3 plus the seal repair in §4. Items 2, 4
and 5 of the dispatch are not started; roll #6 is **not armed**, because arming it is gated on
items 1–3 landing and item 3's recall measurement is outstanding.
