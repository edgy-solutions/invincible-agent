---
status: WALK SHEET — for a human with the UI open; nothing here is verified until the cards are seen
date: 2026-09-19
engine: engine-docs
---

# Docs card walk — the corpus answering for itself

**This sheet exists because a payload check is not a card walk**, and because this engine's
whole claim is that **the page a reader sees is the page an author wrote.** Nothing below is
evidence of that. The only evidence is the card on screen with the prose in it.

**The first question is the one the engine was built to answer**, and the page it should return
is the page that was followed to build the engine. If the runbook is wrong, the engine that
would prove it does not come up.

## ⚠ BEFORE THE WALK — three prerequisites, and NONE of them is "it is committed"

1. **`engine-docs` is ROLLED, not merely merged.** Engines re-register at startup, so a prime
   alone does not restore routing. `/version` on the served pod, not a sha in a log.
2. **The corpus is PRIMED and the bodies are UPLOADED.** Two separate acts: `docs_corpus.ttl`
   lands in Jena with the prime, and `upload_doc_pages()` puts the markdown in the page bucket.
   **A primed corpus with no bodies answers `502` naming the locator** — which is a correct
   refusal and looks like a broken engine.
3. **The parameterisation leg reads `mesh:universalReferent`.** ⛔ **NOT LANDED AT THE TIME OF
   WRITING.** Until it does, `mesh:explain` **cannot enter the candidate pool at all** and every
   question below abstains before reaching this engine. **Do not walk this sheet before that
   leg rolls; a red here would measure the pool, not the cards.**

**Fleet state this sheet assumes:** master `222fbf5`, SDK pin v0.9.3, corpus of eight pages at
`docs_corpus.ttl`. **Re-derive before walking** — the corpus is regenerated from frontmatter and
a page added since this was written changes the answerable set below.

## THE ANSWERABLE SURFACE IS 5 OF 8 PAGES, AND THAT IS BY CONSTRUCTION

Derived from the corpus, 2026-09-19 — **14 `explains` targets across five pages**:

| page | explains |
|---|---|
| `adding-a-canvas-template` | `seedCanvas`, `seedPortfolioCanvas` |
| `adding-a-graph` | `LotCostingReview`, `ProductionLot`, `Program`, `StatefulSupportResponse`, `costLotCostingReview`, `finProgramBrief` |
| `adding-a-task-kind` | `DispositionReview` |
| `adding-an-archetype` | `Archetype` |
| `adding-an-engine` | `InstanceResolution`, `InstanceEnumeration`, `resolveInstance`, `enumerateInstances` |
| `pinning-the-fleet-sdk` · `rolling-a-service` · `writing-a-walk-sheet` | **none — unreachable by this verb** |

> **THREE PAGES CANNOT BE RETURNED BY `mesh:explain` NO MATTER WHAT IS ASKED.** They declare
> `explains: none`, honestly, because they explain no graph IRI — `rolling-a-service`'s own
> frontmatter says the emptiness is the measurement. `page_for_subject` matches on `mesh:explains`,
> so a page with none is matched by nothing. **That is correct and it is not obvious**, and a
> walker who asks "how do I roll a service" and gets an abstain has found the design, not a bug.

## The questions — phrasing taken from the engine's own declared synonyms

`VERBS[0]["synonyms"]` in `agent_fleet/docs_agent/main.py`: *how do I · how to · what is · explain
· documentation for · runbook for · walk me through*. **Every question below opens with one of
them**, because the phrasing is the routing signal and a reworded question tests a different path.

**THE PROMPT FORM IS THE PARSER'S, NOT THE PROSE'S.** `iagent_pure.walk_census.PROMPT_RE` reads
`> **"…"**` and nothing else — the first draft of this sheet put the questions in a table, which
reads better and **parses to zero prompts**, leaving the census's blocked row correctly blocked
against a sheet that existed. The form is written down in one place so one parser reaches all four
sheets; this is that form.

### Q1 — the one the engine was built for

> **"how do I add an engine"**

`KNOWLEDGE_DOCUMENT` carrying **`adding-an-engine.md`, whole.**

### Q2

> **"what is an archetype"**

`KNOWLEDGE_DOCUMENT` carrying `adding-an-archetype.md`.

### Q3

> **"how do I add a canvas template"**

`KNOWLEDGE_DOCUMENT` carrying `adding-a-canvas-template.md`.

### Q4 — the designed refusal

> **"how do I roll a service"**

**ABSTAIN naming the subject. This is a PASS**, and it is the screen nobody looks at.

### Checks that distinguish

**Not "a document appeared".** For Q1–Q3:

* the card's body is the page **byte-for-byte**, `#`-headings and all — **not a summary.** A
  summary is a second artifact nothing reviewed, and the contract refuses it;
* `audience_hint` renders and is the **canonical persona** — `ARCHITECT`, `DATA_ENGINEER`;
* the **cited seals** are the test paths the page names, **in the page's order**;
* Q1's card contains the string `§0 — Before you write a line: claim the name`. A card that draws
  the right archetype with the wrong page passes every check above and fails this one.

## READ THIS BEFORE THE FIRST QUESTION — four correct results that look broken

**Written before the walk, and each is a way an honest answer reads as a defect.**

1. **A very long card is correct.** `adding-an-engine.md` is over 1,200 lines and the contract
   says the page is carried **whole**. A card that scrolls for a minute is the design; a card that
   ends neatly is the thing to investigate.
2. **A single page for a question with several plausible pages is correct TODAY, and it proves
   nothing about ordering.** The 14 targets are distinct — **no subject resolves to two pages** —
   so `order_pages` never chooses. A one-page answer is not evidence the ordering rule works; it
   is evidence the tie never arose.
3. **An abstain naming the subject is a PASS** (Q4), and it is the screen nobody looks at. It must
   say *which* subject it could not cover. An abstain that renders as generalist prose, or as
   `No content available`, is the same defect as a card that will not draw — **and "nothing drew"
   is what both look like.**
4. **`audience_hint` is DISPLAY ROUTING, NOT AUTHZ.** A card addressed to `ARCHITECT` appearing
   for a `DATA_ENGINEER` caller is **correct**. It is a hint about who the page was written for,
   never a gate — and mistaking it for one is the reading the vocabulary warns about.

## Which component owns each failure

| symptom | owner |
|---|---|
| the question abstains before reaching engine-docs | **routing / the pool leg.** Check `mesh:explain` is in the candidate set before blaming this engine |
| `503` naming `ONTOLOGY_SERVICE_URL` | **engine-docs' reader binding**, or engine-o is not serving |
| `502` naming a bucket key | **the prime.** The corpus landed and `upload_doc_pages()` did not, or ran against a stale tree |
| `409` naming a sha mismatch | **the prime again**, and it is the good failure: the bytes are not the bytes the graph indexed, and the engine refused rather than rendering them |
| the right page, the wrong rendering | **cortex.** The payload carried the body; the card dropped it |
| the wrong page, rendered perfectly | **the classifier's subject**, not this engine. `page_for_subject` returns what `mesh:explains` says |

## Residuals — named here, DO NOT SCORE RED

* ⚠ **Ordering is unwitnessed.** Both keys now have inputs — the persona key is live and
  `mesh:source_committed_at` is stamped — but **no subject resolves to two pages**, so nothing
  exercises them. The eo lane's arm reds the day one does. **A walk cannot test this today.**
* ⚠ **`audience` is sent as `null`.** No persona crosses the direct-dispatch route, so the
  ordering's first key is undeliverable and the reader passes nothing. Lane 1 owns the one-line
  gateway change.
* ⚠ **Q1's subject is the open question of this walk, and it is why Q1 is first.** *"How do I add
  an engine"* contains **no IRI**. The filler must produce one, and the only subjects
  `adding-an-engine.md` explains are `resolveInstance`, `enumerateInstances`, `InstanceResolution`
  and `InstanceEnumeration` — **the verbs an engine author registers, not the act of adding one.**
  If Q1 abstains, the honest reading is **not** that the engine failed: it is that **the corpus
  has no page explaining a subject that matches how the question was phrased**, and the fix is a
  page or an `explains` edge, not a card. **Score that as a finding, not a red.**

## What this sheet cannot distinguish

**Every check above passes on a corpus that is stale.** The card renders the bytes the prime
uploaded, and the sha assertion proves those bytes match the row — **it does not prove the row
matches the page in git.** A corpus generated two commits ago is internally consistent, renders
perfectly, and shows a reader the wrong version of the page. **`test_docs_corpus_drift.py` is what
covers that, and it runs in CI rather than on this sheet** — so a green walk plus a red drift seal
means the reader saw a page that no longer exists, and the walk cannot tell.

## Census rows

This sheet's questions are the source; `docs/measurements/walk-census.yaml` follows it, not the
other way round. `expect_verb: mesh_explain` matches either spelling; `expect_archetype:
KNOWLEDGE_DOCUMENT` for Q1–Q3, and Q4's disposition is the abstain rather than `drawn`.
