---
iri: docs:runbook-adding-a-canvas-template
# Every target must exist in the graph — the invented-IRI rule (ADR-0037 §1). This list is
# therefore SHORT and both entries were checked against `CALL db.relationshipTypes()` before
# being written, not assumed from the ADR. There is no verb for "add a template": a template is
# ratified CONFIG, and minting an IRI to make the edge look tidy is what the gate refuses.
explains:
  - mesh:seedCanvas
  - mesh:seedPortfolioCanvas
doc_kind: how-to
audience_hint: data-engineer
---

# Adding a canvas template

**Written from the commits that got it wrong.** Three of the five sites below were discovered by a
seal going red or by a refusal arriving in a shape nobody predicted, and one of them was
**dispatched twice as a one-line change and refused three times** because the obvious version
regresses the only board that draws today.

**This is not adding an archetype and not adding a verb.** An archetype is *how a card renders*; a
verb is *what a panel computes*. A template is **which panels, in which order, with which declared
slots** — ratified config, reviewed like a grant, and invisible to the mesh without a row
(ADR-0050 §1).

## The route: one RED to one GREEN

You are done when **all five seals below are green AND the board actually draws**. Those are
different conditions, and §"What this page cannot distinguish" is about the gap between them.

    1  write policy/canvases/<id>.yaml            RED: --validate refuses it
    2  the models are the schema's source          RED: --check says the committed schema drifted
    3  verbs must be REGISTERED                    RED: the mesh seal names the verb
    4  verbs must be REACHABLE from the subject    RED: no_verb_in_scope at resolve time
    5  cortex's TEMPLATES row — FRONTEND FIRST     RED: nothing; and that is the problem

## The five sites, each with the seal that names its absence

| # | site | the seal that fails if you skip it |
|---|---|---|
| 1 | `policy/canvases/<template_id>.yaml` — one file, one template, `template_id` == filename stem | `scripts/generate_canvas_schema.py --validate`, and the CI job on `pull_request`. **It also fails on ZERO files** — a validator that finds nothing and exits 0 is indistinguishable from one that passed |
| 2 | `src/iagent/canvas_template.py` — the Pydantic models ARE the schema's source; the JSON Schema is generated | `tests/test_canvas_schema_drift.py` — `--check`, plus a **positive control** (the generator exists and `--help` does not write) and a **break-on-purpose** |
| 3 | every panel's verb registered in **BOTH** Neo4j and Weaviate | `tests/planning/test_template_verbs_are_registered.py`. **Conjunctive on purpose:** a verb in Neo4j alone is the row that registers, reports accepted, and never matches |
| 4 | every verb **reachable from its registered subject**, not merely existing | `unreachable_from_subject()` in `tests/_mesh_verbs.py` |
| 5 | cortex-ui's `TEMPLATES` builder + the `CanvasUse` closed union | **none. There is no seal.** See below |

## Site 3 and site 4 are different checks, and site 4 exists because site 3 passed by luck

Site 3 asks `CALL db.relationshipTypes()` — **a global existence question.** On 2026-09-10 it passed
for all eleven template verbs **while `/resolve` excluded every one of their subjects with
`reason: "no_verb_in_scope"`.** The edges turned out to be intact, so the green was correct — **by
luck rather than by measurement.**

A verb whose relationship type exists somewhere, but hangs off nothing its subject can walk to,
produces **the same empty panel as a verb that was never registered**. Site 4 asks the question the
router actually asks: `subClassOf*0..5` from the panel's subject, then the typed edge.

**Both have per-store negative controls, and the split is not symmetry.** One combined control gated
on Neo4j **and** Weaviate skipped when Weaviate went down, while the Neo4j assertion passed — a
green with no control behind it, in exactly the degraded state a control exists for. **A control
must share its subject's gate.**

## Site 5 has no seal, and the ordering is the whole of it

`CanvasUse` is a **closed union** in cortex-ui and `TEMPLATES` has one row. A second `template_id`
must be admitted **on both sides, and the frontend row lands FIRST** (ADR-0050 §7). Ship the
backend first and the board is advertised before anything can draw it.

Nothing in this repo can catch that, because the registry is in another one. **Treat site 5 as a
precondition you assert by hand, not as a step you will be reminded of.**

## Order matters, and only for one reason

Sites 1–4 are checkable in any order. **Site 5 is not reorderable**, per above. Everything else is
convenience — except that site 2 before site 1 saves you a cycle, because the schema the validator
uses does not exist until the generator has run.

## What this page cannot distinguish

**EVERY SEAL ABOVE GOES GREEN ON A TEMPLATE THAT CANNOT SEED.** This is the gap, and it is not a
gap in the seals — each one is true.

`program_finance` is ratified, schema-valid, all six verbs registered **and** reachable, CI green —
and it **cannot draw a board**. Two refusals, and they are different:

* **`501`** — the seeder still runs a phrase list, so only `portfolio` seeds. Every other template
  is honest config with no execution path yet.
* **`409`** — the template declares shared slots that panels *consume* and nothing binds them yet
  (ADR-0050 §3's carry).

So: **green seals plus a ratified file is not a board.** Ask for the refusal, not the colour.

### The moment the obvious repair was the harmful one

**"Declare `program` in `shared_slots`" was dispatched twice and refused three times.** It is what
ADR-0050 §3 names as the worked case, it is one line, and doing it would have:

* taken **`portfolio` from SEEDS to 409** — a regression on the only path that draws a board;
* declared on `portfolio` a slot **none of its verbs accept**: `program_id` occurs **zero** times
  in the planning engine against dozens in finance.

**A shared slot is a parameter the panels' verbs actually take — not a statement that the panels
are about the same thing.** The second reading is what "shared" sounds like in English, which is
exactly why it gets reached for. The zero is the whole argument and it survives every way of
counting.

The correct order is **(1) the seeder dispatches each panel's declared verb, (2) something binds a
shared slot into panels, (3) then declare it.** Declaring first satisfies the ADR's letter and
breaks the working path.

### And a seal whose purpose expired without the seal becoming useless

A test recorded that the `409` branch was **unreachable** — no ratified template declared shared
slots. When `R-005` made it reachable, the honest move looked like deleting it. **Do not.** The
defect had *swapped*, not gone: with `portfolio` seeding and `program_finance` stopping at the 409,
**no ratified template reaches the 501 any more.** Same shape, branches exchanged. It was renamed
to watch the other branch and goes red when increment (1) lands.

**A guard that has "passed its purpose" is often the only thing watching the branch that just went
dark.**

## The shortest correct sequence

    1  frontend: add the TEMPLATES row + CanvasUse member in cortex-ui       (site 5, FIRST)
    2  edit src/iagent/canvas_template.py only if the SHAPE changes          (site 2)
    3  python scripts/generate_canvas_schema.py                              regenerate, do not hand-edit
    4  write policy/canvases/<id>.yaml — verbs, role, ordinal, slots
    5  python scripts/generate_canvas_schema.py --check --validate            (sites 1–2)
    6  pytest tests/planning/test_template_verbs_are_registered.py            (sites 3–4, needs the mesh)
    7  pytest tests/test_canvas_schema_drift.py                               (site 2's controls)

**Declare each verb's REAL signature defaults** (`group_by: org`, not omitted) so the panel states
what it computes. Read them from the measure's signature, not from the ADR — and note the
`accepted_slots` the engine records have been checked against the declarations and agree five for
five, so the declarations are measured rather than argued.

## Two things this page deliberately does not cover

* **Which panels belong on a board.** That is a domain decision; this page is the mechanism.
* **`lens`** — R-002, and it is an **ADR-0050 amendment**, not a field you add quietly. Still
  blocked at the time of writing.
