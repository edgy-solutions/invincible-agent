---
iri: docs:runbook-adding-an-archetype
# The ONE IRI this page honestly explains. Verified present at
# setup/ontologies/mesh_system.ttl:252 (`mesh:Archetype a owl:Class`) rather than taken from the
# ADR — the invented-IRI rule (ADR-0037 section 1) refuses a target that is not in the graph, and
# reading it out of the ADR would check the wrong artifact. Deliberately one: there is no verb
# that binds an archetype, so nothing else here reaches contract depth.
explains:
  - mesh:Archetype
doc_kind: how-to
# From policy/personas.yaml, in its own casing (R-017: the corpus normalises TO the policy
# file, never the reverse). Binding a card type is a platform-builder act.
audience_hint: ARCHITECT
---

# Adding an archetype

> **Written 2026-09-11, from three consecutive rediscoveries** — `STEP_LADDER`, `NAMED_HOLE`,
> `COMPETING_MEASURES`. Cites **ADR-0042** (arrangement is UI-master); it does not amend it.
>
> *These four facts were `title`/`status`/`date`/`adr` frontmatter until 2026-09-11. They moved
> into the body when the corpus settled on one frontmatter shape —* `iri`/`explains`/`doc_kind`/
> `audience_hint`, *the shape `_TEMPLATE.md` declares and doc ingest enforces. This page had
> neither an* `iri` *nor an* `explains` *target, so the corpus could not admit the page that got
> the content right. An exemption would have taught the next author the shape was optional.*

**This is not adding an engine.** Adding a *verb* touches the engine's own tables; adding an
*archetype* touches six shared registries in four repositories' worth of layers, and
**ADR-0042 names fewer of them than exist**. Filing this inside `adding-an-engine.md` would make
that runbook the place people look for everything, which is how its §0 table came to name four
namespaces where eight sites exist.

## What this document is, and what it is not

**It is a route from a red to a green — not an inventory.**

Three archetypes were added in six days and each one was rediscovered from scratch:
`STEP_LADDER`, `NAMED_HOLE`, `COMPETING_MEASURES`. **Detection was never the problem.** The
seals caught all three within one run each, and the comment beside `INTERVAL_TIMELINE` in
`capability_admission.py` has said *"add the next archetype HERE FIRST"* since August.

What is rediscovered every time is **the fix path**, by whoever happens to be holding the red.
So every site below is paired with **the seal that names it**, and the seals are the index: if
you arrive here from a failing test, find your test and the row tells you the next step.

## The six sites

| # | site | file | the seal that names its absence |
|---|---|---|---|
| 1 | **admission vocabulary** | `agent_fleet/presentation_agent/capability_admission.py` → `KNOWN_ARCHETYPES` | `test_every_bound_archetype_is_in_the_ADMISSION_VOCABULARY` (`tests/planning/test_archetype_registries_agree.py`) |
| 2 | **projector row** | `agent_fleet/presentation_agent/main.py` → `_PROJECTED_ARCHETYPES` | `test_every_archetype_cortex_can_draw_has_SOME_projector_path` (`tests/finance/test_the_wire_carries_what_the_engine_declares.py`) |
| 3 | **the mesh class** | `setup/ontologies/mesh_system.ttl` → `mesh:<Name> a owl:Class ; rdfs:subClassOf mesh:Archetype` **with an `rdfs:comment`** | `test_every_planning_archetype_is_declared`, `test_planning_archetypes_hang_off_mesh_Archetype_not_mesh_Response`, `test_every_declared_planning_class_carries_a_comment` (`tests/planning/test_planning_classes_are_declared.py`) |
| 4 | **the binding row** | `agent_fleet/presentation_agent/capabilities.py` → `PRESENTATION_CAPABILITIES` | `test_every_binding_OBJECT_end_is_a_declared_class` (`…/test_archetype_registries_agree.py`), `test_every_binding_renders_a_response_AS_AN_ARCHETYPE` (`…/test_bindings_point_at_archetypes.py`) |
| 5 | **a producer conformance case** | beside the engine that emits it — `tests/cost/`, `tests/finance/`, … | `test_every_projected_archetype_has_a_producer_case` (`tests/planning/test_producers_speak_their_archetype.py`) |
| 6 | **the exemption, AMENDED** | `_EXEMPT` in `…/test_producers_speak_their_archetype.py` | the same seal as #5 |

**And two that are not archetype-specific but bite here**: the namespace must expand on **both**
the write and read prefix tables (`test_EVERY_BINDING_ROW_SURVIVES_THE_WRITE_PATH`,
`test_EVERY_capability_endpoint_expands_to_a_full_iri`) — an unknown prefix passes through
**verbatim by design**, so the row registers, reports *accepted*, and never matches.

## Site 3 is the one that needs a prime, and the seals cannot tell you that

**Sites 1–6 are all green the moment you commit.** Every one of those seals reads a **file** or a
Python registry.

`mesh:<Name>` reaching the **graph** is a different claim, closed only by a prime off a pushed
**master** sha — the prime reads the TTLs baked into the image. **No seal in this repo checks
it.** Ask the graph:

```sparql
ASK { <http://invincible-agent/mesh#CompetingMeasures> a <http://www.w3.org/2002/07/owl#Class> }
```

> **Declared and resolves are different claims with different checks.** A green seal after
> step 3 means the class is declared. It is not evidence the class landed, and reading it that
> way is the specific error this section exists to prevent.

## Order matters, and only for one reason

**Site 1 before the frontend registers.** A frontend advertising a render the backend has no
name for is **refused at the door** — correctly. The refusal is right; the vocabulary was short.

Everything else can land in any order **as long as #4 comes after #3 resolves.** Contract D
refuses a binding whose object end is undeclared, and a row added early joins the existing
failures and stops the seals pointing at one lane's gap. **Unbound beats mis-bound**: a
mis-binding renders something plausible and wrong, where an absent one refuses visibly.

## Site 6 exists because of a real mistake — read this before deleting anything

An exemption in `_EXEMPT` said *"delete this entry when your conformance case lands"*. The case
landed **in `tests/cost/`** — where that same exemption's text said it belonged — and deleting
the entry turned `test_every_projected_archetype_has_a_producer_case` red, because that seal
enumerates *projected* archetypes and looks for a case **in its own file**.

The entry needed **amending to state where conformance lives**, not deleting.

> **An instruction written for one outcome should not be followed into a different one.**
> Meeting an instruction past the point its premise holds is a failure mode of compliance, not
> of inference — the counterweight to *"I would rather meet an instruction than infer one"*.
> Both halves belong together, or the rule teaches obedience to stale text.

## What the class comment must carry

`rdfs:comment` on the mesh class **is the definition the router reads**. It is not
documentation, so it belongs to the lane that owns the archetype rather than to whoever notices
the red first.

**Carry the elimination, including the nearest candidate that fails.** *"Nothing fits"* reads as
unexamined even when it is right. `COMPETING_MEASURES` names MATRIX_GRID — methods × {EAC, VAC,
ETC} is literally a grid and draws all nine figures correctly — and says why it fails:
**a spread spans rows and a grid renders cells.**

> **The nearest thing fits and fails, and here is why** is a stronger claim than *nothing fits*.

## The shortest correct sequence

1. `KNOWN_ARCHETYPES` — **before** the frontend registers.
2. `mesh:<Name>` in `mesh_system.ttl`, under `mesh:Archetype` (**not** `mesh:Response`; there is
   a test for exactly that confusion), with a real `rdfs:comment`.
3. Commit to a lane branch. Merge is gated; a lane commit is free.
4. Merge → CI builds a master sha → roll → **prime**.
5. **ASK the graph.** Only now is the class resolvable.
6. `_PROJECTED_ARCHETYPES` row — rows key plus the passthrough the card actually **reads**.
   A field advertised that nothing reads is the same defect as one a renderer needs and never
   gets, pointing the other way.
7. Binding row, conformance case, and the exemption amendment — **together**. A refusal kept
   after the thing is bound is a stale claim.
