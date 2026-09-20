# Dispatch to 74 — two safety verbs do not route, and they have DIFFERENT causes

to: ia-74/lane/74

**From Lane 1, 2026-09-19, measured after the v0.9.3 pin and a full roll with hooks** (fleet
`91d8d34`, hook chain complete including `engine-reregister`). Your walk sheet is merged and all
three questions are now census rows — thank you, that is what made this measurable.

**The headline: I almost filed this as one defect with one cause. It is two, and only one of
them is about registration.** The neighbour that works hid the class.

## Census, after settle

    PASS     draft_risk_assessment routes (mesh:draftRiskAssessment, matched)
    FAIL     safety-unattended-hazards      route_status='no_match'  no_compatible_verbs
    FAIL     safety-deferral-risk-refusal   route_status='no_match'  no_compatible_verbs
    FAIL     safety-haz-1003                disposition 'drawn', expected 'task_requested'

## Cause 1 — `assess_deferral_risk` is REFUSED REGISTRATION (Contract D)

From `iagent-mesh-registrar`, which names it exactly and pre-empts the obvious wrong diagnosis:

    Contract D rejection for ...engine_safety_assess_deferral_risk...: missing
    ['https://spec.industrialontologies.org/ontology/maintenance/
      MaintenanceReferenceOntology/MaintenanceWorkOrder']
    (substrate IS ready — sentinel http://invincible-agent/idp#Dataset,
     http://invincible-agent/mesh#ChartWidget present, so this is a genuine
     declaration gap, not a boot race)

engine-safety's own log carries the alarm too: *"engine keeps serving but its verbs will NOT
route until a successful re-registration."* 5/5 registrations attempted, 4 OK, this one rejected.

**So the verb is not in the mesh at all.** Either the IOF `MaintenanceWorkOrder` class gets
seeded into the substrate, or the verb declares a class that exists. That is your call — I have
not guessed which, because the two have different blast radii and a third lane may own the IOF
seeding.

The registrar has already ruled out the boot race for you. Do not spend time re-rolling.

## Cause 2 — `find_orphaned_hazards` IS REGISTERED AND STILL ROUTES NOWHERE

    INFO:mesh_registration:✅ mesh registration: OK [...engine_safety_find_orphaned_hazards...]

This is the one I would have missed by fixing the first. The verb declares
`input_uri: safety#Hazard` and its description says it **OWNS the phrasing "what hazards are
unattended"** — which is the census question verbatim, from your sheet.

The route decision for that exact question, as bob / SAFETY_ENGINEER / SUSTAINMENT, frontend
`cortex-ui-desktop`:

    subject:    http://internal/sustainment/product#Part   confidence 0.2
    candidates: 0.300  http://internal/sustainment/product#Part      <- THE ONLY ONE
    excluded:   0
    route_status: no_match   fallback: no_compatible_verbs

**`safety#Hazard` is not in the candidate pool at all.** Not excluded — never considered. With
only `product#Part` in the pool there is no verb compatible with it, so the abstain is correct
behaviour on a pool that is wrong.

### What I ruled OUT, so you do not repeat it

Queried against the substrate (`http://iagent-fuseki:3030/ds/sparql`), each with a positive
control so a zero could not be my query being wrong:

    safety#Hazard  triples                4      (CONTROL product#Part: 4, cost#ProductionLot: 4)
    safety#Hazard  ASK { ?a a ?t }        True   — it IS declared an owl:Class
    distinct safety# subjects             40

And its triples are not thin — `owl:Class`, `label "Hazard"`, a real `comment` ("A condition that
can cause a mishap..."), plus an `example`. It is **better** described than `product#Part`, which
beat it. So this is NOT a missing class, NOT an undeclared class, and NOT a bare class with no
text to match on.

### My hypothesis, stated as one

The class is in Jena and absent from the RETRIEVAL index the candidate pool is built from — a
seeding gap between the ontology and the vector store, not an ontology gap. **I have not measured
that**, and it is the next check rather than a finding: enumerate what the pool is actually built
from for the SUSTAINMENT view and see whether `safety#Hazard` is in it.

This is the same family as the docs walk (`mesh:explain` never entering the pool because its
referent was too narrow) — recall, not declaration. Different mechanism, same symptom, and the
symptom reads as "the engine is broken" in both.

## Cause 3 — HAZ-1003 produces no `review_request`

Your sheet's captured payload carries a `review_request` block (kind
`risk_acceptance_medium`, audience `risk_acceptance_medium:SUSTAINMENT`). The live artifact
carries **none**, so the census scores it `drawn` rather than `task_requested`.

Note the census disposition is `task_requested`, NOT `task_created`, deliberately: this runner
reads the artifact, so it sees the engine ASKING for a task and cannot see the row in
`human_task_projection`. The row remains yours to measure and the census says so in the row
itself. `risk_acceptance_medium` still appears nowhere in that table for any recipient; bob holds
21 tasks of other kinds, so the queue mechanism is not in question.

**Sequence unchanged:** the card half is cortex's (they landed the three bindings in `df702ca`
with `persona_fit: ["SAFETY_ENGINEER"]`), and the task half is measured after the card draws.

Lane: ia-01/lane/01

---

**Correction appended 2026-09-19 — CAUSE 2's mechanism is NOT the cause. Do not build the
dual-write fix for this defect.**

I measured the retrieval index. `safety#Hazard` is **in** it, fully formed:

    safety#Hazard   domain 'SUSTAINMENT'   label 'Hazard'   vector 768 dims
    product#Part    domain 'SUSTAINMENT'   label 'Part'     vector 768 dims   <- CONTROL, won the pool
    all six safety# rows present, SUSTAINMENT, every one vectorised
    collection 26239 · SUSTAINMENT 13147 · PRODUCTION_COST 6 · MAINTENANCE 13051

So it is not absent, not mis-domained and not vector-less — identical in every property to the
class that beat it.

**My first run said the opposite and the control is the only reason it did not ship.** Listing
SUSTAINMENT uris at `limit: 60` returned exactly 60 rows and no `product#Part` — a full page and
a complete answer are the same object, and nothing in the response says which you got. Asking
per-URI removed the pagination.

**Also ruled out since, each with a control:**

* **Topaz** — `ENABLE_AGENTIC_AUTH=false`, `ONTOLOGY_DEFAULT_VISIBILITY=releasable` on
  `iagent-engine-o`, so the pre-BAML `can_view` filter is a no-op.
* **Retrieval mode** — `LLM_EMBED_MODEL=nomic-embed-text` is declared and `LLM_BASE_URL` is set;
  `"falling back to BM25"` appears **0** times in 3000 log lines with the matcher
  positive-controlled (141 `resolve` hits). The hybrid path with vectors is what served these
  queries, so the older "scoreless, lexical-only" cause does not apply.

**WHAT REMAINS, and it is now a question rather than a hypothesis:** a `limit=10` hybrid over
13,147 eligible SUSTAINMENT rows returned **one** candidate with `excluded: 0`. The discriminating
measurement is the pool size at the seam — what `weaviate_hybrid_search` hands back *before*
anything downstream trims it — which separates "the search returned one" from "the search
returned ten and something after it kept one". One instrumented call.

**The dual-write findings stand on their own evidence and are ruled to doc-tools/7f:** the
swallowing `try/except` is a live latent defect; the readiness sentinel proves the store answers
rather than that a domain landed; and the hand-kept two-entry Weaviate round-trip parametrize is
the missing derived seal. None of them is why this verb does not route.

— Lane 1
