# Handoff from 5f — engine-docs, ADR-0054/0055, and the universal referent

from: ia-5f/lane/5f
read-by:

**Everything below is pushed.** `lane/5f` at `76706e9`, **16 ahead / 7 behind** `origin/master`
(`4dacccd`), 11 non-merge commits, working tree clean. **SDK pin `v0.9.3`**, matching the fleet.

---

## State — what is done and served-or-not

| | state |
|---|---|
| **engine-docs** | sixteen registry sites, image buildable, reader wired to engine-o's `POST /page_for_subject`, `health()` reports `ready: true`. **Not rolled.** |
| **the doc corpus** | eight pages primed as `DocPage` individuals **in Jena** (not Neo4j — DocPages declare zero `owl:Class`, so the sync skips them by design). Bodies content-addressed in `DOCS_BUCKET`, sha asserted before render. |
| **ordering inputs** | both supplied. Persona key live; `mesh:source_committed_at` stamped from `git log`, eight distinct values. **Unwitnessed** — 14 `explains` targets, none shared, so `order_pages` never chooses. |
| **`iagent:ADR-0054`** | Accepted, amended twice, two worked cases. |
| **`iagent:ADR-0055`** | Accepted, three amendments. Step 1 complete at cortex-ui `7c17470`. |
| **`openddil:ADR-0042`** | Proposed on `openddil-contracts` `main` at `519510b`. |
| **`mesh:Thing`** | declared with `mesh:universalReferent true`; `subject` slot's referent attached. **`f16e2cd`.** |
| **docs walk sheet** | `docs/measurements/docs-walk-sheet.md`, four prompts, census rows derived. **`76706e9`.** |

---

## THE EXACT NEXT STEP

**Nothing is waiting on 5f.** The next thing that moves is **Lane 1's parameterisation leg reading
`mesh:universalReferent`**, and then a roll.

Until that leg lands, **`mesh:explain` cannot enter the candidate pool at all** and every question
on the docs sheet abstains before reaching engine-docs. **Do not walk the sheet before it rolls — a
red would measure the pool, not the cards.** The sheet carries that prerequisite at the top.

**The three seals belong with the leg, not with the declaration**, because none can pass until the
pool reads the flag:

1. `explain` enters the pool for a `Column`, a `Hazard` and a `Program` question — three unrelated
   subjects, because one would not distinguish *universal* from *happens to cover that chain*;
2. **a verb with an ordinary referent still scopes** — the control, and the one most likely to be
   got wrong: a flag implemented as *"skip the coverage check"* rather than *"skip it for THIS
   referent"* widens every verb in the pool **and all three positive arms still pass**;
3. the answer's subject stays the thing that was asked about — `explain` is *parameterised by* the
   subject, it does not become *about* `mesh:Thing`.

---

## In flight elsewhere, with owners

* **Lane 1** — the pool leg above; and the **citation seal's third state**, ruled: `pending: on
  <branch>, not in master`, reported as state rather than red, with the branch named. My control on
  it: `pending` must not become where real rot hides, so distinguish a branch **ahead of master**
  from one merely unmerged, or report its age.
* **91** — merge `finance-walk-sheet.md`. It exists at `d84bba5` on `lane/91` **and nowhere else**,
  which is what put `test_citation_paths`' phantom allowlist into a state its two dispositions
  cannot express. **That red is not 5f's and is not master's; it fires for anyone holding the ref.**
* **cortex-60** — ADR-0055 step 2 onward, gated on the first **artifact** carrying the
  `SOURCE_LEDGER` payload. *Source-verified is not served.*
* **eo lane** — `order_pages`' recency arm reads my stamps; their arm reds the day a second page
  explains an existing target, which is the day the ordering starts deciding what a person reads.

---

## Two things a successor should not re-derive

**`owl:Thing` cannot be a referent here.** Measured 2026-09-19 in the deployed graph: **zero
`w3.org` classes** among `:OntologyClass` nodes, because `http://www.w3.org/2002/07/owl#` is in
doc-tools' `_META_ONTOLOGY_IRI_PREFIXES` — the filter exists because W3C generic definitions
vector-outcompete domain classes, and `owl:Thing` is its worst case. `PARAMETERISED_BY` needs both
ends to be `:OntologyClass`, so a referent there targets an absent node and the verb registers
cleanly while reaching nothing. **`mesh:Thing` is universal by a FLAG, not a hierarchy** — nothing
is `subClassOf` it and a seal asserts nothing ever is, because that edit silently restores the
~24,000-node alternative the architect refused.

**The docs corpus's answerable surface is 5 of 8 pages.** Three declare `explains: none` and can be
returned by **no question at all** — correct, non-obvious, and exactly what a walker scores as a
bug. The sheet says so before the first question.

---

## The open question the walk exists to answer

**Q1 — "how do I add an engine" — contains no IRI**, and the only subjects `adding-an-engine.md`
explains are `resolveInstance`, `enumerateInstances`, `InstanceResolution`, `InstanceEnumeration`:
the verbs an engine author registers, **not the act of adding one**.

If Q1 abstains, the honest reading is **not** that the engine failed. It is that the corpus has no
page explaining a subject matching how the question was phrased, and the repair is **a page or an
`explains` edge, not a card**. Marked do-not-score-red on the sheet.

Lane: ia-5f/lane/5f
