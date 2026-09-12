---
id:         s3000l-is-primed-and-invisible
status:     open
owner:      doc-tools-7f
blocked-on:
closed-by:
repo:       invincible-agent
summary:    S3000L is in the prime manifest, loads, and contributes 761 owl:Class to the SUSTAINMENT graph — and ZERO of them reach any consumer of `/classes`, because that query requires `rdfs:label` and S3000L declares none. The SPO interview menu, operable-subjects and the router's candidate pool are all reading a SUSTAINMENT vocabulary that silently omits the domain's largest standard. Fix is not loosening the query — a menu needs names — but deriving a label from the URI fragment at the ontology-seed step, written as a triple with `label_source: derived` vs `authored` so a reader can tell a name the spec gave from one the seeder made up.
---

# S3000L is primed, reproducible, and invisible to every menu

**Found 2026-09-11 during ADR-0051's ADR-0007 survey**, by the survey nearly recording a false
negative.

**ROUTED TO `doc-tools-7f`, corrected 2026-09-12.** It was first routed to Lane 1 as "a prime-step
change", which was half right: the *symptom* is visible here, but `ingest_ontology_to_jena` lives in
**doc-tools**, and this repo names it only in docs and `values-sandbox.yaml`. The build is
doc-tools'. **Lane 1 files it, and does not build it.**

**The two controls stay in THIS repo**, because they assert what a consumer sees rather than what
the ingest wrote: the SUSTAINMENT class count as a floor reporting its own delta, and an authored
label surviving and being marked `authored`. A seal that runs only where the fix lands cannot see
the thing the fix was for.

## The measurement

| probe | result |
|---|---|
| `POST /classes {"domain":"SUSTAINMENT"}` | **100** classes: 90 IOF `construct/*`, 9 `internal/sustainment/*`, 1 BFO. **Zero S3000L.** |
| control — same call, other domains | MAINTENANCE **128**, DATA_ENGINEERING **6**, PORTFOLIO_PLANNING **5**, MIL **0**. Not a cap; 100 is the real population. |
| S3000L source (`semanticstep.org`, the manifest's own URL) | HTTP 200, 279 KB, **761 distinct `owl:Class`** |
| `rdfs:label` in that file | **0** |
| `skos:prefLabel` / `dc:title` / any annotation naming a class | **0** |
| `/classes` SPARQL | `?cls a owl:Class ; rdfs:label ?label` — **both required** |

A class in S3000L looks like this. The only human-readable name is the URI fragment, and the spec
section is a `#` comment, which is not a triple:

```turtle
# S3000L v1.1 4.11.3.4 LSAFailureMode
s3kl:LSAFailureMode
      rdf:type owl:Class , s3kl:ClassS3000L ;
      rdfs:subClassOf s3kl:FailureMode .
```

**The triples are present.** `product_structure_extension.ttl`'s header records its citations as
"verified present in the live S3000L graph" — so this is not a load failure. It is a read failure,
and only for consumers that go through the labelled-class query.

## Who is reading an incomplete vocabulary right now

Everything downstream of `/classes` and the same `_SPARQL_MAINTENANCE_CLASSES` shape: the SPO
interview's authorized-subject menu (ADR-0029 Slice 2), `/operable_subjects`, and the
OntologyClass candidate pool a router selects from. Each of them currently presents SUSTAINMENT as
100 classes. The domain's largest standard — the one the product-structure vocabulary cites as its
authority — contributes nothing to any of them.

**The failure mode is a confident, uniform silence.** Nothing errors. A caller asking about a
failure mode gets a clean "no such subject", which is indistinguishable from the term genuinely not
existing. ADR-0051's survey was one step from recording "S3000L: not found" and minting a parallel
cause vocabulary over 41 failure-mode classes that were there the whole time.

## The fix, and what it must not be

**NOT loosening the query to accept unlabelled classes.** A menu needs names; admitting a class
with no label puts a bare IRI in front of a user and degrades every consumer to make one
consumer's count go up.

**Derive the label at the ontology-seed step** — for any class with no authored annotation, write
an `rdfs:label` derived from the URI fragment (`LSAFailureMode` → "LSA Failure Mode"), **as a
triple**, carrying its own provenance:

    label_source: authored   the vocabulary supplied this name
    label_source: derived    the seeder made it up from the IRI

**The provenance is the whole point, and it is the three-state rule again.** A derived name is a
guess presented in the same position as a fact; without the marker, a reader cannot tell which
kind they are looking at, and the menu becomes the same optimistic-default dishonesty the
`favourable` ruling refused. With it, the 761 appear, honestly marked, and a consumer that wants
only authored names can filter.

## Definition of done

1. Seed step derives labels for unlabelled classes, with `label_source` on every label it writes.
2. `/classes` for SUSTAINMENT returns **~861**, not 100 — the count itself is the seal, asserted as
   a floor with its delta rather than a containment check.
3. A class with an authored label keeps it, and is marked `authored` — the positive control,
   without which the seal cannot tell "derivation worked" from "derivation overwrote everything".
4. One consumer verified end to end: a failure-mode term reachable through `/operable_subjects`.
5. The derivation shown RED against a class whose fragment cannot yield a sane name, or the
   heuristic ships unmeasured.
