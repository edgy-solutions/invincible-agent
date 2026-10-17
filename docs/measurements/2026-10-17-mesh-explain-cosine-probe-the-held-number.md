# The `mesh:explain` cosine probe — the number the pool-leg hold waited on

Date: 2026-10-17. Taken by Lane 1 (`ia193/lane/01-193`), on the architect's Day 2 addendum,
item 2. Taken once, as ordered.

## What was run

- Probe: `scripts/explain_cosine_probe.py`, committed `60b512e2` (2026-09-19) before any number
  existed. Blob `230e86c236ad0951d6003e5d1ac5009df5d74a6f`, unchanged since.
- Where: piped into the sandbox engine-o pod (`ontology-service:b89d4c951a3f13667341e120e1cab23dfbc98ccd`),
  `python - <questions> < scripts/explain_cosine_probe.py`. Every call is a read: Weaviate GETs
  plus the fleet embedder (`utils.embed`). Exit 0.
- Questions: the four distinct `question:` values of the `docs/measurements/docs-walk-sheet.md`
  rows in `docs/measurements/walk-census.yaml`. "how do I add an engine" appears on two rows and
  was asked once.

## What the store holds

| field | value |
|---|---|
| explain rows | `mesh:explain` → `http://invincible-agent/mesh#DocPage` (read from the Predicate row; it matches the probe's cross-check constant) |
| OntologyClass vector slots | legacy=23956, named=977, none=1315 |
| rows with a readable vector | 24933 |
| subject present with a vector | True |
| query dimension | 768 |

## The number

| question | DocPage rank of 24933 | DocPage cosine | top-1 (cosine) | DOCS-domain subset |
|---|---|---|---|---|
| how do I add an engine | 86 | 0.4750 | `…elecricalPowerFromEngineEstablished` (0.6051) | empty |
| what is an archetype | 16 | 0.5575 | `mesh#Archetype` (0.7701) | empty |
| how do I add a canvas template | 22 | 0.4734 | `mesh#Archetype` (0.6153) | empty |
| how do I roll a service | 146 | 0.4487 | `mesh#Archetype` (0.5414) | empty |

**DocPage is in the top 5 for none of the four questions.** Its best rank is 16. Its cosine
trails the top hit by 0.09 to 0.21. The DOCS subset is empty: no vector-bearing OntologyClass row
has `domain` exactly `DOCS` (the probe's predicate, `r["domain"] == "DOCS"`), and that includes
DocPage itself. A search filtered to the DOCS domain would have nothing to rank.

## What it answers, and what it does not

The scope is 74's caveat, unchanged: a hand-scored ranking over STORED vectors, not the pool a
fixed search would build. It has no BM25 half, no domain filter, no top-k cut and no
tie-breaking. A bad number means vector similarity cannot put the subject in the pool; a good one
would not have meant routing works.

What it does answer: the query vector does not prefer `mesh:DocPage` over the ontology's other
classes for any docs-walk question. Vector retrieval alone will not bring DocPage into the
candidate pool, even with a working search. That is the case for admitting it by referent
(`universalReferent`, addendum item 1) rather than waiting on the vectors.

## Not measured here

- The pool the shipped search builds (BM25 plus vector, domain filter, top-k).
- Any question outside the docs walk sheet.
- Whether a re-embed with a DOCS domain tag would change the ranking. No re-embed path exists.
