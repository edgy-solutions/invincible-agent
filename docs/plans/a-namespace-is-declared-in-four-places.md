---
id:         a-namespace-is-declared-in-four-places
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0019 (Contract D — both triple ends must resolve to :OntologyClass nodes); ADR-0045 (Engine F, the first non-platform namespace)
code-site:  agent_fleet/utils/mesh_registration.py:492 (_IRI_PREFIXES, FIXED for fin:), agent_fleet/presentation_agent/capabilities.py:32 (_IRI_PREFIXES_FOR_LOOKUP, FIXED for fin:), agent_fleet/mesh_registrar/v2_substrate.py:558 (_IRI_PREFIXES, NOT fixed — see "why not"), tests/routing/test_substrate_invariants.py:295, tests/routing/test_predicate_collection_dedup.py:92
summary:    Adding a namespace prefix requires editing FOUR independent compact-to-full IRI maps (three in prod code, two more in tests) and NOTHING asserts they agree. They already disagree today — the test map carries `data:` and no prod map does. Every one of them fails the same way: an unknown prefix is passed through VERBATIM by deliberate design, so the miss is SILENT at every site. Engine F is the first namespace after `mesh:`/`idp:` and it hit two of the four; the third is a DELETING path it does not reach today only by accident of calling convention.
---

# A namespace is declared in four places and nothing makes them agree

## The maps

| # | site | purpose | had `fin:`? |
|---|---|---|---|
| 1 | `agent_fleet/utils/mesh_registration.py:492` `_IRI_PREFIXES` | expands the wire form at the emit boundary so the linker's MATCH lands | **no → fixed** |
| 2 | `agent_fleet/presentation_agent/capabilities.py:32` `_IRI_PREFIXES_FOR_LOOKUP` | folds compact/full at archetype lookup | **no → fixed** |
| 3 | `agent_fleet/mesh_registrar/v2_substrate.py:558` `_IRI_PREFIXES` | canonicalises `input_uri` for the stale-row **DELETE** sweep | **no → left alone, see below** |
| 4 | `tests/routing/test_substrate_invariants.py:295` | test-local expansion | no — **and it carries `data:`, which no prod map has** |
| 5 | `tests/routing/test_predicate_collection_dedup.py:92` | test-local expansion | no |

Site 4 is the proof that this drifts rather than might drift: **a prefix exists in a test map and in
no production map.** Either `data:` is real and two prod paths mishandle it, or it is not and a test
asserts over a namespace that does not exist. Nobody had to choose, because nothing compares them.

## Why the miss is silent at every site

Each map's lookup ends `return s` — unknown prefix passed through unchanged. That is **correct and
deliberate**, and `mesh_registration.py`'s docstring gives the good reason: *"An unknown prefix is
left alone rather than guessed at — inventing a namespace would fabricate the same phantom class
Contract D exists to refuse."*

The cost is that the failure has no tell. At site 1 the registration is emitted, accepted, and the
linker's MATCH misses on both ends; the row is simply never created. Measured 2026-09-01: the
observable was a finance card rendering as `Knowledge Document · No content available` on an answer
that had routed perfectly — **indistinguishable from having no binding at all.**

## Why site 3 was NOT fixed

It is shared code outside this lane's fences, and Engine F does not reach it today: the sweep keys
on `verb_iri` and canonicalises `input_uri`, and every engine registration passes **full** IRIs
already, so canonicalisation is the identity function on both sides and they match. Presentations
never enter it at all — the sweep is verb-keyed and a presentation's predicate is `rendersAs`.

**That is an accident of calling convention, not a property.** Site 3 is the one map whose miss
DELETES: rows survive by canonical-equality with `current_input_uri`, so two spellings of one class
make a live row look like a rename-stale orphan. The module's own comment already instructs the fix
— *"Adding a new namespace prefix: add an entry here and the sweep handles compact-vs-full
equivalence"* — and that instruction was not followed for `fin:`, by me, deliberately, on the
fences. It is one line and it is recorded here so the next namespace does not discover it the
expensive way.

## What would actually close this

Not "remember to edit four files." One exported map, imported by all three prod sites, with the test
maps asserting against it rather than restating it. The seal is cheap and is the real deliverable:

> **every prefix appearing in any map appears in all of them** — which fails today on `data:`, and
> would have failed on `fin:` before this change, which is the definition of a useful seal.

Until then the derivation to prefer is the one `tests/test_presentation_wire_form.py` already uses:
assert the **property** (*nothing a presentation puts on the wire is still in compact form*) over the
real table, not the map's contents. That seal would have caught `fin:` at site 1 the moment the rows
were added, and it is why site 1's gap was found before deploy rather than after.

## Related

* `[[an-adr-does-not-allocate-a-component-name]]` — the same shape one level up: four name registries
  per engine, none of which knows about the others. A namespace has four too.
* `[[read-the-consumer-of-what-you-fixed]]` — sites 1 and 2 are both *consumers* of a table that
  looked complete on its own.
