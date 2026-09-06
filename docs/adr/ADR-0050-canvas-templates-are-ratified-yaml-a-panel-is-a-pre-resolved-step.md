# ADR-0050 — Canvas templates are ratified YAML: a panel is a pre-resolved step, and there is one seed verb

**Status:** Proposed (2026-09-05). **Written before the build, so the wrong build is refusable before
the right one starts.** The tempting builds — a per-canvas seed verb, and a template that carries
phrases — are refused by name in §4. **This ADR AMENDS a standing in-code ruling** (the seeder's
Ruling (a), sealed by a live test); §2 states exactly which half of it survives and why.
**Date:** 2026-09-05
**Deciders:** Architect
**Related:**
  - [ADR-0028](ADR-0028-canvas-answer-composition-workspace.md) — the canvas this ADR extends. Its
    load-bearing v1 constraint (*"the card is not a thumbnail; it is an SPO-tagged answer object"*)
    is what makes a panel expressible as a declared step at all.
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) **Decision 5** — the
    pre-resolved step. *"A step therefore does NOT invoke the NL-resolution half — it invokes stage 2
    (the structural eligibility gate) as a VERIFIER, then dispatches."* Bounded by the initiator's
    grants at every step; **a workflow cannot be used to launder access.** §2 and §5 inherit this
    verbatim and add no exception.
  - [ADR-0039](ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md) — YAML is
    authoritative, the schema is a committed artifact generated from the models with a drift test,
    invalid fails at merge. §1 inherits the mechanism. **The read shows that mechanism is decided
    and UNBUILT** — see the premise corrections.
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — seed/overlay composition, at
    the repo, with deletion expressible. Templates are ratifiable config and compose the same way.
  - [ADR-0033](ADR-0033-interrogative-disambiguation-ask-from-the-phonebook.md) — ask from the
    phone-book, menu integrity, the `slot-unfilled` disposition. §3's template-level slot is a
    consumer of it, not a second elicitation surface.
  - [ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) **§2** — the `run_any_graph`
    refusal. §4 states why one seed verb over a closed ratified set is not that shape.
  - [ADR-0049](ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md)
    **Ruling 2** — named hole vs refuse, and the existence-oracle caveat. §5 applies it to a panel.
  - [ADR-0042](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md) —
    content is state-master, **arrangement is UI-master**. §7 is that ruling defended against a YAML
    that would like to own coordinates.

---

## Context

### The question, stated so it cannot drift

**A board that several people should see the same way is currently produced by asking five questions
in English. By what artifact is such a board declared, what is a panel made of, who may seed one, and
what does a caller who cannot invoke every panel get?**

### What exists today — read 2026-09-05, cited, and it decides §2

**The seed fires PHRASES, not verbs. This is not an oversight; it is a ruling with a test behind it.**

The five asks are natural-language strings in a Python list —
[`src/iagent/gateway.py:1441-1456`](../../src/iagent/gateway.py), `PORTFOLIO_CANVAS_QUESTIONS`, each
row `{slot, measure, question}` where `question` is a sentence — and the loop posts each one as
`{"message": spec["question"]}` to the gateway's own `/interview/stream` over localhost
([`gateway.py:1497-1519`](../../src/iagent/gateway.py)). The `measure` key is a **label in a
comment's role**: nothing dispatches on it. Every panel on today's board is drawn by whatever the
classifier picked for a sentence.

The outer hop is a phrase too. `mesh:seedPortfolioCanvas` is registered with six `verb_synonyms`
([`gateway.py:184-193`](../../src/iagent/gateway.py)) — *"make me a portfolio canvas"*, *"set up my
planning board"* — so the canvas is reached by classification and then draws itself by
classification.

And it is deliberate. [`gateway.py:1414-1422`](../../src/iagent/gateway.py) carries **RULING (a): IT
ASKS QUESTIONS. IT DOES NOT INVOKE VERBS**, whose reason is governance, not convenience:

> *"a seeded card must carry a DECISION PATH or it is not an artifact. A browser-invisible measure
> call produces a picture with no provenance, no routing record and no entitlement check — governance
> bypass wearing a shortcut's clothes."*

It is sealed:
[`tests/planning/test_seed_portfolio_canvas.py:121`](../../tests/planning/test_seed_portfolio_canvas.py)
— `test_RULING_A_the_seeder_asks_questions_it_does_not_invoke_verbs`.

**§2 must therefore amend a ruling rather than fill a gap, and it must not amend it by ignoring it.**

### The rest of the path, read end to end

- **The seed returns ids, never a board.** `/canvas/seed` ([`gateway.py:1582-1683`](../../src/iagent/gateway.py))
  is a thin alias over `/seed/portfolio_canvas` and returns `{"artifact_ids": [...]}` slot-ordered.
  The reason is stated in-file: writing the canvas server-side *"would duplicate stageConstants'
  coordinates into Python, and the first divergence would be invisible."*
- **A partial seed REFUSES the whole board today** ([`gateway.py:1633-1651`](../../src/iagent/gateway.py)),
  and the refusal is reasoned across three named options (compact / holes / refuse). The receiver
  cannot place a null: cortex does `for (const id of artifactIds) addItemAuto(...)`.
- **The recognizer places nothing.** `canvasSeedFromArtifact` in cortex-ui
  (`src/lib/canvasSeedFromAnswer.ts:40-42`) returns `{ ids: string[]; name?: string } | null` and
  says so in its own header: *"It computes no placement — the template applies inside `addItemAuto`,
  so a seeded canvas stays the same object a user builds by hand."*
- **The client's template is a FUNCTION, and its geometry is proportional.**
  `portfolioPlanningTemplate(vp, rowContentH?, anchorContentH?): CardSlot[]`
  (cortex-ui `src/lib/stageConstants.ts:95`), realized from measured content heights, with the
  registry `TEMPLATES: Record<string, builder>` at `stageConstants.ts:170-175` holding exactly one
  row. The file states the reason coordinates cannot be authored elsewhere:
  *"THE TEMPLATE IS PROPORTIONAL, NOT ABSOLUTE … World units still exist — the canvas is one
  coordinate space and a seeded card must stay byte-identical to a dragged one — but their absolute
  size cancels out."*
- **`arranged` is the re-fit invariant, and it is sealed.** `CustomCanvas.arranged`
  (cortex-ui `src/store/useStageStore.ts:62-74`) is *"TRUE once a HUMAN has placed, moved or resized
  a card here … Never by seeding or auto-placement, which are the template speaking rather than a
  person."* The rule is one line — `setViewport`, `useStageStore.ts:219`:
  `if (c.arranged || !c.use) return c;` — so a board is re-fitted **iff** it is unarranged and has a
  type. Sealed by `src/lib/canvasTemplate.test.ts:425-489`, including a `JSON.stringify` byte-compare
  for the arranged case and an explicit *"SEEDING does not count as arranging"*.
- **A seeded board is already indistinguishable from a hand-built one**
  (`useStageStore.ts:345-355`, sealed at `canvasTemplate.test.ts:217-235`), except for
  `seededFrom`, which exists purely for idempotency.

### Six premise corrections from the read — each changes what gets built

**1. ADR-0039's mechanism is DECIDED AND UNBUILT.** There is no `*.schema.json` anywhere in the repo
and no `model_json_schema()` call outside prose. `policy/sync/validate_policy.py:121` validates six
data files plus two optional ones and **does not touch `policy/workflows/*.yaml` at all**. So §1
cannot "inherit a running mechanism"; it is the mechanism's **first instance**, and it must be built
as the generator workflow definitions will later share — not as a second one. The `--check`
regeneration pattern to copy already exists and is proven: `scripts/generate_board.py --check` read by
`tests/test_board_drift.py`, **including a positive control asserting the generator exists so the
seal cannot pass vacuously.**

**2. "Fails at merge" is not true of this repo yet.** `validate_policy.py` runs in the private policy
repo's PR gate and again fail-closed in
[`helm/invincible-agent/templates/topaz-seed-cronjob.yaml:249`](../../helm/invincible-agent/templates/topaz-seed-cronjob.yaml).
This repo's `.github/workflows/` holds `build-containers.yml`, `release-helm-charts.yml` and
`suite-order-independence.yml` — **no job runs `validate_policy`.** Since `policy/canvases/` lives
here, §1's merge gate is a **new CI job in this repo**, and calling it "alongside `validate_policy`"
describes a rail that does not exist on this side yet. Say it, or the first builder discovers it.

**3. There is no single `ruleset_ref` pattern — there are three, and they disagree.**
`policy_rules_loader.py:79-86` mints `<label>@<sha256[:12]>` over canonicalized JSON **without a
separators pin**; `agent_fleet/utils/trust_table.py:260-262` mints `trust@<sha1[:12]>` over **raw file
bytes**; `agent_fleet/cost_agent/export.py:58-70` mints `sha256:<full>` over canonical JSON **with**
`separators=(",",":")` pinned. §1 must pick one deliberately rather than say "follow the pattern".

**4. The load-bearing property of `ruleset_ref` is CONTENT-ONLY hashing, and it was hard-won.**
`policy_rules_loader.py:39-50`: the hash covers the rule subgraph, not the file and not the graph, so
co-tenant vocabulary cannot perturb it — *"a `ruleset_ref` provenance claim means 'THESE RULES,' not
'this graph state'."* `template_ref` inherits that property, and inherits its cost with it.

**5. `derived_from` is SINGULAR today.** `src/iagent/answer_artifact_writer.py:135` declares
`derived_from_artifact_id: Optional[str]`, one `MERGE (a)-[:DERIVED_FROM]->(parent)` at `:657`, and
the projector collapses with `[(a)-[:DERIVED_FROM]->(d) | d.id][0]`
(`src/iagent/projector/apply_loop.py:452`). §6 wants a canvas artifact with **N** parents. That edge
must become multi-valued and the projector's `[0]` must go; it is a prerequisite, not a detail.

**6. The verb that exists today is already a per-template verb.** It is named
`mesh:seedPortfolioCanvas`, and the string is load-bearing in at least one place beyond registration:
`_CALLER_IDENTITY_VERBS = frozenset({"seedPortfolioCanvas"})`
([`src/iagent/defs/dynamic_supervisor.py:1373`](../../src/iagent/defs/dynamic_supervisor.py)) — the
allow-list deciding which verbs dispatch under the caller's own identity rather than the service's.
**§4's refusal is retroactive.** It names a thing in the tree, and the conversion has a cost that §4
states rather than discovers.

---

## §1 — A canvas template is a git-asserted YAML in `policy/canvases/`

A template is **ratifiable config**, in the same sense and the same directory family as grants, the
trust table and workflow definitions: diffable, greppable, reviewed like a grant, entering only by PR.

1. **Location and form.** `policy/canvases/<template_id>.yaml`. One file, one template.
2. **The schema is a committed artifact generated from the models.** `model_json_schema()` from the
   Pydantic models that the seed verb itself loads, committed to the repo, with a **drift test** built
   on the `--check` shape already proven by `scripts/generate_board.py` + `tests/test_board_drift.py`
   — **including its positive control**, so the seal cannot pass because the generator vanished. The
   models and the schema cannot disagree because one is generated from the other.
3. **Validation runs in the rails, and the rail is new.** A CI job in **this** repo validates every
   `policy/canvases/*.yaml` against the committed schema, so an invalid template fails **at merge**
   rather than at seed time in a pod. Per premise correction 2, this job does not exist yet and §1 is
   what creates it. When ADR-0039's workflow-definition schema lands, it uses **this** generator and
   **this** job — two generators for one law is ADR-0036 §2's two-escapers problem at config scale,
   and it will produce two schemas that disagree once, in production.
4. **Composition is ADR-0036's, unchanged.** Seed templates ship here; work overlays deltas in the
   work-side repo; composition happens **at the repo**, emits a readable composed artifact, and the
   composed result passes the **same** validation. Deletion of a seeded panel must be expressible as
   an overlay statement, per §3c, or the first unwanted panel forces a fork.
5. **`template_ref` is the content hash, minted deliberately.** Format follows `ruleset_ref` so refs
   read alike in a record: **`<template_id>@<first 12 hex of sha256>`**. Canonicalization follows
   `cost_agent/export.py`'s `_canonical` — `sort_keys=True, separators=(",",":")` — because the
   separators pin is the one thing `policy_rules_loader`'s version lacks, and an unpinned separator is
   a ref that moves when a serializer's defaults do. The hash covers the **composed template's
   semantic content** — its panels, their verbs, their declared slots, their slot roles — and **not**
   the file bytes: a reordered key, a reflowed comment or a changed description does not mint a new
   ref, and a changed panel does. That is `ruleset_ref`'s content-only property inherited
   deliberately, including its stated cost: **`template_ref` says "THIS panel set", and nothing about
   the state of anything else.**

---

## §2 — A panel is a pre-resolved step, not a phrase

**A panel is `{verb, slots, layout}`.** The verb is dispatched through the ADR-0029 Decision 5 seam —
**stage 2, the structural eligibility gate, invoked as a verifier, then dispatch** — and never
through the classifier. Decision 5's sentence applies without amendment: a step *declares* subject and
verb, so it is already resolved and does not invoke the NL-resolution half.

### The reason is a measurement, not a preference

**The router's winner is a sample of a distribution, and the distribution moves under the substrate.**
The evidence is in the seeder's own comments, put there by the people who paid for it:

- **The winner moved with no change to the phrase.** [`gateway.py:1436-1440`](../../src/iagent/gateway.py):
  *"subject resolution SHIFTS when the ontology or verb set changes — 'where are we over budget' moved
  Portfolio 0.86 → Site 0.75 across a single prime. Re-verify after any prime before trusting this
  list."* A template that routes phrases is pinned to a substrate state, and nothing announces when
  that state changes. The list is defended by a test that exists only because it rots:
  `test_every_phrasing_is_from_the_resolver_verified_set`
  ([`tests/planning/test_seed_portfolio_canvas.py:86-91`](../../tests/planning/test_seed_portfolio_canvas.py)).
- **A phrase was rewritten to match a default, and the card it drew was correct and off-question.**
  [`gateway.py:1447-1456`](../../src/iagent/gateway.py), measured 2026-08-28: the by-initiative
  phrasing returned **eleven organisations**, because the slot was never carried to dispatch and the
  verb ran on its default. The card rendered cleanly, with clean provenance, and **no disclosure
  surface** — the strip renders routing, not verb params. The fix was to change the *question* so the
  *default* would be true. A declared slot makes that fix a declaration instead of a workaround.

**Declared verbs draw the same board every time; routed phrases redraw differently on every load.**
That is the whole of §2's argument, and it rests on two measurements in this repo rather than on a
preference for determinism.

*The dispatch for this ADR also cites `/resolve` contention under fan-out as a third measurement. **It
is not asserted here**: it was not verified in this read, and the two facts above carry the argument
without it. Recorded so its absence reads as a decision rather than an omission.*

### What survives of RULING (a), and what does not

Ruling (a) conflated two things that ADR-0029 Decision 5 separates: **the governed path** (the
entitlement gate, the artifact, the decision record) and **the NL path** (stages 1 and 3 — resolve a
sentence to a subject and a verb). Its stated harms were *"no provenance, no routing record and no
entitlement check."*

- **Provenance survives, unchanged.** A declared panel still mints a real answer artifact with its own
  decision path. Nothing becomes browser-invisible.
- **The entitlement check survives, and gets stronger.** Stage 2 runs as a verifier against the
  **caller's** identity at every panel, which is exactly Decision 5's *"you cannot declare a step with
  a verb you are not eligible for and have it execute."* Today's check is real but incidental — it
  happens because the phrase went through the interview path; tomorrow's is structural.
- **The routing record is what changes, and losing it is the point.** A declared panel has no
  classifier decision to record, because there was no classification. The `selection_basis` of a
  declared step is *"the template declared it"*, and a template is a reviewable artifact in a way a
  0.86-vs-0.75 margin is not.

**So Ruling (a) is amended, not overturned: its governance requirement holds in full, and its chosen
mechanism — reuse the NL path literally — is replaced by the pre-resolved step, which satisfies the
same requirement without inheriting the classifier's variance.** The seal
`test_RULING_A_the_seeder_asks_questions_it_does_not_invoke_verbs` is **superseded** by slice 1 and
must be replaced in the same commit by a seal asserting the opposite property with the same intent:
*every panel dispatches through the stage-2 verifier under the caller's identity, and every panel
mints an artifact carrying its own decision path.* **A superseded seal that is deleted without a
replacement is how the governance half of Ruling (a) gets lost while everyone believes §2 preserved
it.**

---

## §3 — Template-level slots: one ask, N panels

A template may declare **slots its panels share** — `program` is the worked case. The rules:

1. **Declaration.** A template declares its shared slots at the top level; a panel declares which of
   them it consumes. A panel may also declare panel-local slots, which are never asked at load.
2. **One ask at load, through ADR-0033's disposition.** A shared slot that is unfilled fires
   **exactly one** ask, using the `slot-unfilled` → **ask** disposition ADR-0033's amendment declared,
   from the phone-book, with menu integrity: every offered option must produce a board. The answer
   **binds into every panel declaring that slot.** This is a *consumer* of the elicitation surface,
   not a second one — ADR-0033's *"one elicitation surface, not two"* applies to templates the same
   way it applies to goal-shaped abstains.
3. **A slot no provider can enumerate falls to RESPEAK.** There is no menu, so the answer is words
   (`src/iagent_pure/slot_disposition.py:583`), carried as a spoken value and resolved rather than
   bound — the existing separation between `bound_slots` and a respeak answer
   ([`gateway.py:2224-2231`](../../src/iagent/gateway.py)) is what keeps an unvalidated string out of
   the bound set, and it is inherited unchanged. **A template is not a licence to bind an unoffered
   value.**
4. **A slot the initiator has no entitlement to see refuses the TEMPLATE, not the panel.** This is the
   one place §5's named hole does *not* apply, and the asymmetry is deliberate: a shared slot is the
   board's subject. A board seeded on a subject the caller may not see is not a board with a hole in
   it — it is a board about something they were not permitted to ask about, and every panel would be
   a hole. Refuse at load, naming the slot, subject to §5's existence-oracle flag.

**§3 is BLOCKED, and the blocker is measured.** `[[slots-are-extracted-then-dropped-at-dispatch]]`
(corrected 2026-08-28) records that **nothing is extracted at all**: BAML's `RouteIntent` has zero
callers, `/route_intent` calls `ExtractIntent`, which returns mode and entity refs only, and *"every
verb runs on DEFAULTS."* The pipeline is one-third built and the built third is the middle. A declared
slot on a panel is worth nothing until the **dispatch boundary carries slots**. That fix is §3's
prerequisite and §2's completion, and it is the same blocker ADR-0045 already waits on
(`[[slot-resolution-entities-in-the-resolver-substrate]]`).

**What this costs the rollout, honestly:** slice 1's five panels take their verbs' defaults today, so
a slice-1 template declaring those defaults explicitly is **true** and produces the same board whether
or not the carry has landed — the declaration documents reality instead of hoping for it. Slice 2
cannot work without the carry.

---

## §4 — One seed verb: `seedCanvas(template_id)` — and two refusals by name

**There is one seed verb.** `seedCanvas(template_id)`, where:

- **`template_id` is a spoken-mandatory slot.** A bare *"build me a board"* is refused with the
  question, exactly as `fin_eac_calculation` refuses a bare *"what's the EAC"* with *"which method?"*
  (ADR-0045). The seed verb has no default template; a default template is a per-template verb wearing
  a parameter's clothes.
- **It is enumerable from the ratified set**, so the ask is a menu and every option seeds — ADR-0033's
  menu-integrity rule verbatim. The phone-book here is the directory listing: the templates that
  merged.

### REFUSED BY NAME — 4.1: the per-template verb (`seedFinanceCanvas`, `seedCostCanvas`)

**Refused.** One registration per canvas is *the template smuggled into code*, and every property this
ADR buys is lost with it:

- **The panel set stops being reviewable.** A template in a Python list is not diffable as policy; it
  is diffable as a deploy. `template_ref` has nothing to hash.
- **The registry count multiplies.** Adding a board costs a mesh registration, `verb_synonyms` a
  classifier must discriminate between, an entitlement grant, an admission row, and — measured — an
  entry in `_CALLER_IDENTITY_VERBS` ([`dynamic_supervisor.py:1373`](../../src/iagent/defs/dynamic_supervisor.py)),
  a frozenset keyed on a literal verb string. That is the four-name-registries hazard, once per board.
- **The classifier is asked to discriminate between boards.** Six synonyms for one canvas already
  exist; N canvases means N synonym sets competing in the same space, and §2's own measurement says
  that winner moves.
- **It already exists and is the thing being retired.** `mesh:seedPortfolioCanvas` is the first
  instance of exactly this shape. **The conversion is part of slice 1**, and its cost is named above so
  nobody discovers `_CALLER_IDENTITY_VERBS` at deploy time.

### REFUSED BY NAME — 4.2: the phrase-carrying template

**A template may not contain a natural-language question, not even as a fallback for a verb it could
not name.** A template with one phrase in it is a template whose board is reproducible except where it
isn't, and the exception is invisible in the rendered result — which is §2's measured failure mode
(*eleven organisations, clean provenance, no disclosure surface*) preserved in a ratified artifact.
**A panel whose verb cannot be named is a panel that is not ready to be in a template.**

### Why this is NOT `run_any_graph` (ADR-0046 §2)

ADR-0046 refuses `run_any_graph(graph_id, payload)` on five counts. `seedCanvas(template_id)` answers
each, and the reason is structural rather than a promise:

| ADR-0046 §2's objection | why it does not apply here |
|---|---|
| **no slots to declare** | every inner step is a **real registered verb with declared slots**; the filler has exactly the same surface it has for a typed question |
| **no arity** | each panel's verb carries its own arity; the seed verb's own arity is one `template_id` |
| **no subject** | each panel's verb declares its own `input_uri`; grounding discriminates per panel |
| **one output type for all** | each panel produces its verb's fixed output class (ADR-0030); the seed verb's own output is the existing `mesh:CanvasSeedResult` ([`setup/ontologies/mesh_system.ttl:329`](../../setup/ontologies/mesh_system.ttl)) |
| **one grant covers everything anyone ever plugs in** | **this is the sharp one, and it is the one §5 answers.** Entitlement is evaluated **per inner verb, under the initiator's grants** — never once, per runner. A grant on `seedCanvas` grants the ability to *ask for a board*; it grants **nothing** about what lands on it |

Two further differences of kind: **the template set is closed and reviewed** — a template enters by PR
into `policy/canvases/`, unlike a graph id which is a string the caller supplies; and **there is
nothing opaque in the payload** — `template_id` is an enum over merged files, not a passthrough.

`run_any_graph`'s defining property is *entitlement to the runner is entitlement to everything anyone
ever plugs in, including graphs authored after the grant.* Under §5 that sentence is **false** here:
entitlement to `seedCanvas` plus a template authored tomorrow containing a verb you cannot invoke
yields a hole, not a disclosure.

---

## §5 — Entitlement by construction: the named hole

**Each panel passes the stage-2 gate under the initiator's grants, at dispatch, every time.** No
pre-computed board, no cached eligibility, no service identity. This is ADR-0029 Decision 5's
*bounded by its initiator's grants, by construction, at every step*, and ADR-0049 Ruling 1's *inner
calls run as the INITIATOR* — the same property arriving through a third door.

**A panel whose verb the initiator cannot invoke renders as a NAMED HOLE: the card exists and says why
it is empty.** The template declared the panel, so the panel's absence is a fact the reader is
entitled to, and per ADR-0049 Ruling 2 a narrowed result must **say** it was narrowed. This is the
declared-optional case, satisfied structurally: **the template's declaration at authoring time IS the
registration-time declaration Ruling 2 requires**, which is why a hole is permitted here and a
runtime-decided hole is not.

**Two users, one template, different-sized boards is CORRECT.** It is the eligibility intersection
made spatial — ADR-0028's own thesis — and anyone who files it as a bug should be sent here.

### The existence-oracle caveat — FLAGGED, NOT RULED

**Whether the hole names the verb it could not invoke is a per-classification policy decision, not a
per-template one.** *"You are not entitled to the program-cost panel"* discloses that the panel exists
and that this caller lacks it; in a compartmented context that emission may be the thing being
protected, and the refusal must then be indistinguishable from the template simply not having that
panel. ADR-0049 Ruling 2 flags this and assigns it to the enforcement overlay; **this ADR flags it
identically and does not decide it.** What §5 *does* fix is that the hole exists at all — a silently
shorter board is refused in every classification.

### Where this collides with today's behaviour, and how it is reconciled

Today a partial seed **refuses the whole board** ([`gateway.py:1633-1651`](../../src/iagent/gateway.py)),
reasoned across compact / holes / refuse, and the refusal is right for the case it was written for. It
is not the same case. ADR-0049 Ruling 4's three states settle it:

| state | disposition |
|---|---|
| **unentitled** — the caller may not invoke this panel's verb | **named hole.** The board seeds; the card says why it is empty |
| **unavailable** — the verb failed, timed out, or the run queue refused | **today's refusal stands.** A shifted board is the confidently-wrong answer in layout form |
| **empty** — the verb answered and legitimately has nothing | the panel's own rowless/degraded card, as any typed question would get |

**The named hole has a cost that must be paid before it can be claimed:** cortex places ids, and a
null becomes a broken item. **A hole card is a component cortex-ui does not have.** Until it exists,
§5's hole is a decision without a surface, and slice 1 must not pretend otherwise — see the rollout.

### The seal is the three-caller shape

Per ADR-0046 §5 and ADR-0048's seal 2: the same `template_id`, three identities — one entitled to
every panel, one entitled to some (a board with a named hole), one entitled to none (a refusal, not an
empty board). **All three run; the discrimination is the assertion.**

---

## §6 — Provenance

1. **The canvas artifact carries `template_id` and `template_ref`.** *Which board, and under which
   version of it.* `template_ref` is the answer to *"what exactly was this board declared by?"* the way
   `ruleset_ref` answers it for a disposition — and, per §1.5, it answers **only** that.
2. **The canvas artifact carries `derived_from` for every panel artifact.** N edges, not one.
3. **Panels keep their own provenance unchanged.** A panel artifact is the artifact that verb always
   produces; nothing about being on a board alters it. This preserves ADR-0028's *a seeded card is the
   same object as a typed one* and cortex's matching claim that a seeded board is byte-identical to a
   hand-built one.
4. **A template change mints a new `template_ref`. Boards seeded under the old one are NEVER
   rewritten.** A board is a record of an act — the `CANVAS_SEED` contract already says so
   (`recomputes: false`, cortex-ui `src/components/registry/CanvasSeed.contract.ts:55`) — and
   retro-fitting a board to a template edited afterwards would make *"which template drew this?"*
   unanswerable, which is the entire reason the ref exists.

**Prerequisite, from premise correction 5:** `derived_from_artifact_id` is singular
(`answer_artifact_writer.py:135`) and the projector takes `[0]`
(`projector/apply_loop.py:452`). §6.2 requires a multi-valued edge and a projector that does not
collapse it. **A canvas artifact written against today's edge would silently record one panel and
lose the rest** — and it would look fine, because one parent is a valid answer to a query for one
parent.

---

## §7 — Layout is a hint; `arranged` is the truth

**Cortex's invariant holds unchanged, and this ADR exists partly to say so:** a board a human has
arranged is byte-identical across round trips; a board still wearing its template's arrangement
re-fits to the pane. One line, `useStageStore.ts:219` — `if (c.arranged || !c.use) return c;` — sealed
at `canvasTemplate.test.ts:425-489`, including *"SEEDING does not count as arranging"*. **The fold and
full-screen work is not reopened by this ADR.**

### The read narrows what "the template declares positions" can mean

The dispatch for this ADR says the template declares positions. **The read overrides it**, on two
independent grounds:

- **The existing division is explicitly ruled.** [`gateway.py:1421-1428`](../../src/iagent/gateway.py):
  *"A template that chose which measure went where would be reaching into the seeder's job; a seeder
  that computed coordinates would be reaching into the template's."* Order lives server-side;
  coordinates live client-side. Putting coordinates in the YAML re-imports the duplication that ruling
  removed, and the in-file reason — *"the first divergence would be invisible"* — is unchanged.
- **The client's coordinates are not authorable.** They are derived at render time from the viewport
  aspect and from **measured content heights** (`stageConstants.ts:21-34`, 95, 137-143). There is no
  set of numbers a YAML could carry that would survive a different pane.

**Ruling: a panel's `layout` declares its SLOT ROLE and ordinal — `anchor`, and the pairs beneath it —
never pixels.** The geometry that realizes a role stays in cortex's `TEMPLATES` builder, keyed by
`template_id`. `ORDER IS THE DECLARATION` (`gateway.py:1421-1428`, and the projector comment at
`agent_fleet/presentation_agent/main.py:552-571`) is preserved verbatim: position 0 is the anchor, the
client never sorts, the projection never reorders or dedupes. ADR-0042's *arrangement is UI-master*
survives intact, and so does the hand-built/seeded identity.

**The registry consequence, named because it is the recurring defect:** cortex's `CanvasUse` is a
closed union (`useStageStore.ts:35-39`) and `TEMPLATES` has one row. A second `template_id` must be
admitted **on both sides** — the ratified YAML here and the builder there — and the frontend row must
land **before** the backend advertises it, which is the ordering trap already written into the
archetype registries by name (`agent_fleet/presentation_agent/capability_admission.py:108-115`).
Whether that second registry should exist at all is §9.2.

---

## §8 — Non-goals, with reasons

- **No runtime-authored templates.** A board a user builds in the UI stays a **user board** — a
  `CustomCanvas`, exactly as today. A template enters by PR. The reason is §1's whole premise: a
  template is a policy artifact whose value is that it was reviewed, and a runtime-authored one is a
  mutable table wearing a policy artifact's name — ADR-0039's two-planes hazard, reproduced.
- **No template inheritance in v1.** Composition is by **overlay only** (ADR-0036). Inheritance is a
  second merge algebra beside the one ADR-0036 already fixed, and ADR-0036's own non-goal — *"a merge
  algebra … anything richer waits for a case"* — applies unchanged. Nothing here is a case.
- **No per-panel phrases, not even as fallback** (§4.2).
- **This ADR does not build the slot carry.** It names it as the blocker (§3) and stops.

---

## §9 — Open questions, with trades

**1. Does the named hole name the verb?** Flagged in §5, deliberately not decided. It is a
per-classification policy on the enforcement overlay, and deciding it per template would be the
implementation choosing an emission policy — the exact inversion ADR-0049 Ruling 2 warns against.
*What is decided:* the hole exists. *What is open:* what it may say.

**2. Where does template geometry live when the second template lands?** Two shapes, both real:
  - **Extend cortex's builder registry per template** (today's shape). Geometry stays where the
    measurements are, and the `CanvasUse` union stays a closed type the compiler checks. **Cost:** a
    second registry to keep in step with the YAML, with a landing order that must not be got wrong —
    the hazard §7 just named.
  - **The YAML declares a proportional slot grid the client realizes generically.** One registry;
    adding a board is a PR with no frontend change. **Cost:** it moves arrangement into config, which
    is a nick in ADR-0042's *arrangement is UI-master*, and a grid expressive enough for a real board
    is a layout language nobody asked to maintain.
  *Lean:* the first, until a third template makes the sync cost real — but it is a genuine trade and
  slice 2 is where it gets decided on evidence rather than here.

**3. May an overlay DELETE a seeded panel, and what does that do to the seal?** ADR-0036 §3c says
deletion must be expressible or the overlay forks, and that reasoning holds. But a deleted panel
changes the board's shape, and the *"two seeds produce identical panel sets"* seal must then be scoped
per **composed** `template_ref`, not per `template_id` — otherwise the seal compares a work board to a
seed board and fails correctly for the wrong reason. *Lean:* deletion is expressible, and the seal is
scoped to the composed ref. Recorded as open because the seal's scope is the load-bearing half and it
has no consumer yet.

**4. Is the shared-slot ask fired BEFORE any panel dispatches, or lazily at the first panel that needs
it?** Pre-flight is the lean, on ADR-0029 Decision 5's own reasoning: a board that is predestined to
refuse should refuse **at start**, before consuming a run queue for seventeen minutes, and at
classification *creating* the work is itself an emission. **Cost:** a caller who abandons the board
was asked a question for nothing. *Not decided here*, because the pre-check's own ruling is
advisory-only and this would be its first real consumer.

**5. Does `seedCanvas` stay sequential?** Today's seed is sequential by construction and measured at
**17.7 minutes for five panels** ([`gateway.py:1424-1428`](../../src/iagent/gateway.py)); the reason
was `max_concurrent_runs: 2` plus a reaper gap that deadlocked the queue twice in one day. Declared
panels make a dependency graph *expressible* for the first time, which is the argument for
parallelism — but **nothing about the run queue has changed**, and the constraint that ruled
sequential is a substrate fact, not a code one. Open, and the honest form of the question is *"has the
queue changed?"*, not *"can the template say so?"*

---

## Acceptance — the seals this ADR commits to

1. **A template referencing an undeclared verb FAILS AT MERGE.** The CI job of §1.3, against the
   generated schema plus a verb-existence check. Broken-on-purpose once, since a schema check that
   never rejects is indistinguishable from no check.
2. **A panel whose verb the initiator lacks renders a NAMED HOLE, not a seed failure.** The
   three-caller shape of §5: entitled / partially entitled / unentitled, all three run.
3. **Two seeds of the same template under the same identity produce identical PANEL SETS.**
   *Scope, stated precisely because the loose version is unpassable:* identical **(verb, declared
   slots, slot role, ordinal)** per panel. **Not** identical artifact ids — those are minted per run
   (`uuid4`, [`gateway.py:1500-1507`](../../src/iagent/gateway.py)) — and not identical rendered
   content, which is state-dependent by design (ADR-0042).
   **This seal must be run against TODAY's seed once, first, and it must FAIL.** A seal that has never
   been shown to bite on the thing it was written to catch is decorative, and this is the one seal
   phrase-based seeding cannot pass. Recording the failure is what makes §2 a measurement rather than
   a claim.
4. **A template-level slot fires exactly ONE ask for N panels.** Assert on the count of elicitations
   emitted, not on the board that came back — a board that rendered proves the binding worked and says
   nothing about how many times the user was asked.
5. **The schema-matches-model drift test passes, and its positive control passes too** — the generator
   exists, per `tests/test_board_drift.py`'s shape. Without the control, deleting the generator makes
   the drift seal green.
6. **The replacement for the superseded RULING (a) seal lands in the same commit** (§2), asserting that
   every panel dispatches through the stage-2 verifier under the caller's identity and mints an
   artifact carrying its own decision path.

---

## Rollout

**Slice 1 — re-express the existing portfolio canvas as the first template. Nothing new until it
passes.**

The success condition, stated in the terms the seals can actually check: **the same panel set, in the
same slot order, with the same slot roles, producing a board structurally identical to today's** —
`CustomCanvas` equal modulo `id`, `name`, `seededFrom` and the artifact ids, which is precisely the
comparison cortex already makes at `canvasTemplate.test.ts:217-235`. Any panel that differs is
**documented with its reason** rather than quietly accepted; the expected differences are known in
advance and are the interesting output of the slice:

- slot 3's phrasing was chosen to match a **default** (§2's second measurement), so its declared slots
  state what the verb actually does. If declaring them changes the card, that is the slot carry
  landing, and it is a *correction*, not a regression — record it as such.
- `mesh:seedPortfolioCanvas` → `seedCanvas`, including
  `_CALLER_IDENTITY_VERBS` ([`dynamic_supervisor.py:1373`](../../src/iagent/defs/dynamic_supervisor.py)),
  the registration and its `verb_synonyms` ([`gateway.py:180-197`](../../src/iagent/gateway.py)).
- **The named hole may be declared and not yet rendered.** cortex has no hole component (§5). Slice 1
  may land the backend disposition with the client falling back to today's refusal, **provided the gap
  is a named board item and not a silent narrowing** — a board that quietly comes back shorter is the
  exact defect §5 exists to prevent, and shipping it as an interim would be this ADR failing on its
  first slice.

**Slice 2 — the finance template, with `program` as the shared slot: six cards from one ask.** This is
the demo, and it is **gated on the dispatch-boundary slot carry** (§3). Slice 2 is also where §9.2
gets decided, because it is the second row in both registries.

---

## Consequences

- **Someone can start slice 1 without asking a question**: the template is YAML in `policy/canvases/`,
  the panel is `{verb, slots, layout-role}`, the verb goes through the stage-2 verifier, the seed verb
  is `seedCanvas(template_id)`, entitlement is per panel under the initiator, and the layout role is a
  hint that cortex's builder realizes.
- **Someone proposing `seedFinanceCanvas` is refused by section number** (§4.1), and so is a template
  carrying a question (§4.2).
- **This ADR creates a CI job that does not exist**, and it is the first schema-generation instance in
  the repo. That is a real new build dependency and the honest cost of §1.
- **Two prerequisites move onto the critical path, neither of them cosmetic**: the multi-valued
  `derived_from` edge (§6) and the dispatch-boundary slot carry (§3). The second is shared with
  ADR-0045, which strengthens the case for it rather than duplicating it.
- **Boards will differ between people, visibly**, and it will be reported as a bug at least once. §5 is
  the answer, and the fact that it is written down is most of its value.
- **A template's board is only as reproducible as its verbs are stable.** `template_ref` pins the panel
  set, never the answers — same discipline, and same limit, as `ruleset_ref` pinning rules and not
  graph state.

## Indicators we got this wrong

- **A template acquires an `if`.** Panels selected at runtime by anything other than the caller's
  entitlement is ADR-0034's no-mode-branch ruling arriving in a new file type, and the point at which
  templates stop being reviewable as policy.
- **Every panel in every template is declared optional**, so nothing ever refuses and §5's hole is the
  default. ADR-0049 records this failure for composed verbs; it is the same one.
- **The second template ships as a second verb** "just for the demo". §4.1 exists because that is the
  one-afternoon build.
- **`template_ref` is written and nothing reads it.** Write-only provenance; the project has one of
  those already.
- **Seal 3 was never run against today's seed.** Then §2's central claim is an assertion, and this
  document is a preference with citations.

## The one-sentence model

**A canvas template is a reviewed, content-hashed YAML declaring an ordered set of panels, each a
pre-resolved `(verb, slots)` step dispatched through the eligibility gate under the initiator's own
grants — so the same template draws the same board every time for the same person, a different-sized
board for someone entitled to less, and no board at all for someone entitled to none of it.**

## Verification note

Every claim about current behaviour was read on 2026-09-05 and is cited above. In this repo:
`src/iagent/gateway.py` (registration 180-197; questions 1441-1456; seed route 1471-1571; alias and
partial-seed refusal 1582-1683; RESPEAK carriage 2224-2231), `src/iagent/defs/dynamic_supervisor.py:1373`,
`src/iagent/answer_artifact_writer.py:135,651-660`, `src/iagent/projector/apply_loop.py:452`,
`agent_fleet/presentation_agent/main.py:552-571`, `agent_fleet/presentation_agent/capability_admission.py:108-115`,
`agent_fleet/restate_analyst/policy_rules_loader.py:32-88`, `agent_fleet/utils/trust_table.py:260-262`,
`agent_fleet/cost_agent/export.py:58-70`, `policy/sync/validate_policy.py:62-121`,
`helm/invincible-agent/templates/topaz-seed-cronjob.yaml:249`, `setup/ontologies/mesh_system.ttl:329`,
`tests/planning/test_seed_portfolio_canvas.py`, `tests/test_board_drift.py`,
`docs/plans/slots-are-extracted-then-dropped-at-dispatch.md`. In the sibling repo `cortex-ui`:
`src/lib/canvasSeedFromAnswer.ts:11-12,40-55`, `src/lib/stageConstants.ts:21-34,95,137-158,170-193`,
`src/store/useStageStore.ts:35-39,57-90,196-239,266-384`, `src/lib/canvasTemplate.test.ts:217-235,425-489`,
`src/components/registry/CanvasSeed.contract.ts:39-75`, `src/api/client.ts:430-435`.

**Unverified, and named so it is not inherited as fact:** the `/resolve`-contends-under-fan-out claim
in this ADR's dispatch (§2 declines to rest on it); whether `bpmn_catalog`-style parallelism limits
have changed since the sequential ruling (§9.5 asks it as a question); and whether any deployment
outside this repo already runs a `policy/canvases/` validation rail (premise correction 2 assumes not,
and §1.3 is written to hold either way).
