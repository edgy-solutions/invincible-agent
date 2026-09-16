"""`page_for_subject` — engine-docs' first-consumer read, over JENA.

**THIS IS A `MeshOntology` OPERATION, NOT `MeshGraph`, and the store is the finding.**
`docs_agent/reads.py` declared it as MeshGraph's. The corpus is `setup/ontologies/docs_corpus.ttl`,
primed into `internal/DOCS` — and `DocPage` individuals declare zero `owl:Class`, so doc-tools'
`sync_jena_ontologies_to_neo4j` takes its class-less third case and **skips the Neo4j write**.
`prime_databases.py:456` says it outright: *"the Jena named-graph load — which is where the doc
route reads — still succeeds."* There are no DocPage rows in Neo4j, by design.

**f3's BOTH-SHAPES TRAP DOES NOT APPLY HERE, and saying so is the point.** Four `mesh:explains`
targets are `:OntologyClass` nodes and four are relationship types, so a NEO4J probe asking only
the class question reports four real targets absent with total confidence. That is ingest-time
target validation, and doc-tools already solved it (`runbook_ingest.py:238`, which also records
the half that bites twice: relationship types cannot contain colons, so the linker stores the full
IRI as `r.iri` and uses the LOCAL NAME as the type). **A triple match does not care what shape the
target is**, so a both-shapes branch here would guard nothing — an arm that cannot fire, added out
of diligence.

PURE BUILDERS, INJECTED EXECUTOR — the shape `state_sparql` and `sustainment_instance_provider`
already use here, so the SPARQL is parse-tested before it meets Fuseki and this module imports no
client.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

try:  # flatten-aware import, same shape as registry_views in main.py
    from state_sparql import sparql_lit  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.state_sparql import sparql_lit

DOCS_GRAPH = "http://internal/DOCS"

#: THE SEVEN FIELDS, and they are the corpus's own triples rather than a restatement:
#: `rdfs:label` · `mesh:doc_kind` · `mesh:audience_hint` · `mesh:source` · `mesh:body_sha` ·
#: `mesh:explains` (repeating) · and the page IRI itself, which is the subject of them all.
_PREFIXES = """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX mesh: <http://invincible-agent/mesh#>"""


def _local_name(subject: str) -> str:
    """The last segment of a CURIE, an IRI, or a bare name.

    **NO PREFIX TABLE ON PURPOSE.** `subject` arrives as the RAW SLOT VALUE — the verb is
    polymorphic over every class, so the slot declares no referent and the value is a CURIE in the
    happy case and sometimes a NAME. Expanding a CURIE would need a prefix registry, and an
    unknown prefix in this fleet passes through VERBATIM and matches nothing, silently, which is a
    defect this repo has paid for three times. Matching on the local name asks a question the data
    can answer without a registry to be wrong about.
    """
    for sep in ("#", "/", ":"):
        if sep in subject:
            subject = subject.rsplit(sep, 1)[-1]
    return subject.strip()


def build_page_for_subject_query(subject: str) -> str:
    """Pages whose `mesh:explains` includes `subject`, with every field the row carries.

    THE SECOND `mesh:explains` PATTERN IS NOT A DUPLICATE. The first selects the page by the
    target that MATCHED; the second collects ALL of that page's targets, because `PageRow.explains`
    is the page's full claim rather than the fragment of it that answered this question.
    """
    literal = sparql_lit(subject)
    local = sparql_lit(_local_name(subject))
    return f"""{_PREFIXES}
SELECT ?iri ?title ?doc_kind ?audience_hint ?source ?body_sha ?ex
WHERE {{
  GRAPH <{DOCS_GRAPH}> {{
    ?iri a mesh:DocPage ;
         mesh:explains ?matched ;
         mesh:explains ?ex .
    OPTIONAL {{ ?iri rdfs:label ?title }}
    OPTIONAL {{ ?iri mesh:doc_kind ?doc_kind }}
    OPTIONAL {{ ?iri mesh:audience_hint ?audience_hint }}
    OPTIONAL {{ ?iri mesh:source ?source }}
    OPTIONAL {{ ?iri mesh:body_sha ?body_sha }}
    FILTER (
      STR(?matched) = "{literal}"
      || STRENDS(STR(?matched), "#{local}")
      || STRENDS(STR(?matched), "/{local}")
    )
  }}
}}"""


def rows_to_pages(rows: Sequence[dict]) -> list[dict]:
    """Collapse the executor's flat rows into one dict per page, explains gathered.

    The query returns a row per (page, target) pair, so a page explaining six things arrives six
    times. Grouping here rather than in SPARQL keeps the query parse-testable and the grouping
    unit-testable, which is the trade `state_sparql` already makes.
    """
    pages: dict[str, dict] = {}
    for row in rows:
        iri = row.get("iri")
        if not iri:
            continue
        page = pages.setdefault(
            iri,
            {
                "iri": iri,
                "title": row.get("title") or "",
                "doc_kind": row.get("doc_kind") or "",
                "audience_hint": row.get("audience_hint") or "",
                "source": row.get("source") or "",
                "body_sha": row.get("body_sha") or "",
                "explains": [],
            },
        )
        ex = row.get("ex")
        if ex and ex not in page["explains"]:
            page["explains"].append(ex)
    for page in pages.values():
        page["explains"] = tuple(page["explains"])
    return list(pages.values())


def order_pages(pages: Sequence[dict], audience: Optional[str] = None) -> list[dict]:
    """The ruled order — audience match first, then most recent body, ties as a list.

    **BOTH INPUTS ARE MISSING TODAY AND THIS FUNCTION SAYS SO RATHER THAN SUBSTITUTING.**

        audience   no audience reaches the operation. `acting_persona` is in scope at the dispatch
                   site and is not put in the request body — one key in one dict. Until it lands,
                   callers pass `None` and this is a stable identity.
        recency    THE CORPUS CARRIES NO TIMESTAMP. `body_sha` is a content hash, not a time.
                   `mesh:source_committed_at` is 5f's to stamp from each page's source commit —
                   a rebuildable fact derived from the act — and it is what will give this rule
                   its second key.

    **A STABLE IDENTITY IS THE HONEST BEHAVIOUR, not a defect.** With neither key available every
    page ties, and a tie is exactly what the consumer renders: engine-docs' `8a424d6` replaced
    `rows[0]` with rendering every surviving row, because *picking the first of several is a winner
    chosen on no evidence and indistinguishable from a confident answer*. Ordering by something
    arbitrary here — insertion order, IRI, sha — would manufacture that winner.
    """
    if not audience:
        return list(pages)
    wanted = audience.strip().upper()
    return sorted(pages, key=lambda p: (p.get("audience_hint", "").strip().upper() != wanted,))


def page_for_subject(
    subject: str,
    *,
    run: Callable[[str], Sequence[dict]],
    audience: Optional[str] = None,
) -> list[dict]:
    """Pages explaining `subject`, ordered. **Empty is an answer and never raises.**

    A young corpus has gaps by design, and engine-docs turns an empty list into an abstain naming
    what it received. A raise here would become a 500 on a question whose honest answer is
    "nothing covers that yet" — so a substrate failure is the caller's to surface, and an
    unresolvable subject is simply empty.
    """
    if not (subject or "").strip():
        return []
    return order_pages(rows_to_pages(run(build_page_for_subject_query(subject))), audience)
