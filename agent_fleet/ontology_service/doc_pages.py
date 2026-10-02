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


def build_page_for_subject_query(subject: str, *, graph: Optional[str] = None) -> str:
    """Pages whose `mesh:explains` includes `subject`, with every field the row carries.

    THE `EXISTS` AND THE `OPTIONAL` ARE NOT A DUPLICATE. The `EXISTS` selects the page by the
    target that MATCHED; the `OPTIONAL` collects ALL of that page's targets, because
    `PageRow.explains` is the page's full claim rather than the fragment of it that answered.

    **A PAGE IS ALSO ITS OWN SUBJECT.** Since the DOCS subject pool binds `subject` to a DocPage
    IRI (`match_pages` below), the subject may name the page itself rather than something it
    explains. That arm matches the FULL IRI only, never a local name, so a subject whose local name
    happens to equal a page's cannot select it. It is also why `explains` is OPTIONAL: a page
    that declares no `explains:` (four of the nine in the 2026-09-29 corpus) is still servable by
    its IRI.
    """
    literal = sparql_lit(subject)
    local = sparql_lit(_local_name(subject))
    return _page_select(
        graph,
        f"""    FILTER (
      STR(?iri) = "{literal}"
      || EXISTS {{
        ?iri mesh:explains ?matched .
        FILTER (
          STR(?matched) = "{literal}"
          || STRENDS(STR(?matched), "#{local}")
          || STRENDS(STR(?matched), "/{local}")
        )
      }}
    )
""",
    )


def build_all_pages_query(*, graph: Optional[str] = None) -> str:
    """Every DocPage with every field. The DOCS subject POOL, which `match_pages` scores."""
    return _page_select(graph, "")


def _page_select(graph: Optional[str], filter_block: str) -> str:
    """The one SELECT both builders share, so the pool and the lookup return the same row shape."""
    # WHO SCOPES THE GRAPH IS THE CALLER'S TO SAY, AND GETTING IT WRONG IS SILENT.
    # engine-o's `execute_sparql` WRAPS every query in
    # `VALUES ?__mesh_g { <internal/{DOM}> <internal/{DOM}_INSTANCES> } GRAPH ?__mesh_g { ... }`
    # by brace surgery on the text. A builder that emits its own GRAPH clause hands that wrapper
    # a nested scope it did not expect — so the route passes `graph=None` and lets the executor
    # scope, while a direct executor (a test over the corpus file, or any caller holding its own
    # store) passes the graph explicitly. **The default is None because the fleet path is the
    # executor path**, and a default that suits the test would be wrong where it matters.
    opening = f"  GRAPH <{graph}> {{" if graph else "  {"
    closing = "  }" if graph else "  }"
    return f"""{_PREFIXES}
SELECT ?iri ?title ?doc_kind ?audience_hint ?source ?body_sha ?committed ?ex
WHERE {{
{opening}
    ?iri a mesh:DocPage .
    OPTIONAL {{ ?iri mesh:explains ?ex }}
    OPTIONAL {{ ?iri rdfs:label ?title }}
    OPTIONAL {{ ?iri mesh:doc_kind ?doc_kind }}
    OPTIONAL {{ ?iri mesh:audience_hint ?audience_hint }}
    OPTIONAL {{ ?iri mesh:source ?source }}
    OPTIONAL {{ ?iri mesh:body_sha ?body_sha }}
    OPTIONAL {{ ?iri mesh:source_committed_at ?committed }}
{filter_block}{closing}
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
                "source_committed_at": row.get("committed") or "",
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
    """The ruled order — audience match first, then most recent body, ties rendered as a list.

    **THE SECOND KEY IS LIVE AS OF 5f's `98aef67`:** the generator stamps
    `mesh:source_committed_at` from each page's source commit (`git log -1 --format=%cI`), eight
    pages with eight distinct stamps, so it DISCRIMINATES rather than tying everything.

    **A COMMIT TIME, NOT AN INGEST TIME, and the reason decides the semantics.** One prime lands
    the whole corpus, so every page shares an ingest timestamp to the second and "most recently
    ingested" separates nothing. The source commit does. **It ORDERS; it does not ASSESS** — a page
    whose last commit was a typo fix outranks one untouched for a year, which is right for choosing
    between two candidates and wrong as a claim about maintenance. Anything reading this as
    freshness is reading a claim the field does not make.

    **A MISSING STAMP SORTS LAST AND IS NOT INVENTED.** 5f's generator refuses an uncommitted page
    rather than substituting mtime or `now`, because a fabricated timestamp would then order the
    corpus. A page arriving here without one is a page from a corpus generated before the stamp
    existed, and it ties with its peers rather than being dated by this function.

        audience   still unwitnessed on the direct-dispatch route — engine-docs sends
                   `audience: null` DELIBERATELY rather than omitting the field, because no persona
                   reaches it and a guess would order by an audience nobody asserted.
        recency    LIVE. Descending, so most-recent first.

    **STABLE, so a tie stays a tie.** Anything still level after both keys is rendered as a list by
    the consumer — `8a424d6` replaced `rows[0]` for that reason, and ordering by insertion, IRI or
    sha here would manufacture the winner that fix removed.
    """
    ordered = sorted(
        pages,
        key=lambda p: (p.get("source_committed_at") or "") == "",   # stamped before unstamped
    )
    ordered = sorted(
        ordered, key=lambda p: (p.get("source_committed_at") or ""), reverse=True
    )
    # re-apply the unstamped-last rule, which the descending sort above would otherwise invert
    ordered = [p for p in ordered if p.get("source_committed_at")] + [
        p for p in ordered if not p.get("source_committed_at")
    ]
    if not audience:
        return ordered
    wanted = audience.strip().upper()
    return sorted(ordered, key=lambda p: (p.get("audience_hint", "").strip().upper() != wanted,))


def page_for_subject(
    subject: str,
    *,
    run: Callable[[str], Sequence[dict]],
    audience: Optional[str] = None,
    graph: Optional[str] = None,
) -> list[dict]:
    """Pages explaining `subject`, ordered. **Empty is an answer and never raises.**

    A young corpus has gaps by design, and engine-docs turns an empty list into an abstain naming
    what it received. A raise here would become a 500 on a question whose honest answer is
    "nothing covers that yet" — so a substrate failure is the caller's to surface, and an
    unresolvable subject is simply empty.
    """
    if not (subject or "").strip():
        return []
    return order_pages(
        rows_to_pages(run(build_page_for_subject_query(subject, graph=graph))), audience
    )


# ── THE DOCS SUBJECT POOL ─────────────────────────────────────────────────────────────────────
#
# "how do I add an engine" names no class. No OntologyClass is labelled engine or canvas
# template, ADR-0037 refuses minting one, and `mesh:explain`'s `subject` slot declares the
# universal referent `mesh:Thing`, so the class contest has nothing to bind and the instance
# fan-out has no provider that knows a page. The subject a DOCS question names IS a page, so
# the DOCS pool is the DocPage individuals themselves, scored here and bound by engine-o's
# `/resolve` and `/fill_slots`.
#
# PURE AND OFFLINE, like the builders above: the pool arrives as `rows_to_pages` output, so the
# scorer is sealed over `docs_corpus.ttl` with no store.

DOCS_NS = "http://invincible-agent/docs#"
DOCPAGE_CLASS = "http://invincible-agent/mesh#DocPage"

#: THE TWO GATES, and each refuses a different wrong bind.
#:   COVERAGE — the share of the question's IDF mass the winner's tokens cover, with a token no
#:              page carries weighted as the rarest. "what is the status of HAZ-1003" covers
#:              nothing and binds nothing, so a non-docs question falls through unchanged.
#:   MARGIN   — the runner-up must score at most this fraction of the winner. "how do I add
#:              something" matches six `adding-*` pages alike and binds none of them, and a
#:              near-tie is an ASK the caller owns, never a coin toss this function makes.
#: Measured over the 9-page corpus on 2026-09-29: the engine question wins 0.94 over the graph
#: page's 0.57 (ratio 0.61); the canvas question wins 0.97 over 0.20; "runbook" ties at 0.90.
MATCH_COVERAGE_FLOOR = 0.5
MATCH_MARGIN = 0.75

_STOPWORDS = frozenset(
    "how do does did i a an the to of for in on at by what which is are was my me we you our "
    "your and or with can could should would please show tell about this that it its into from "
    "be".split()
)


def _stem(tok: str) -> str:
    """A deliberately small stemmer: -ing, plural -s/-es, then a final doubled consonant.

    **THE UNDOUBLING RUNS ON EVERY TOKEN, NOT ONLY AFTER -ing**, because it must map both
    spellings to one form: "adding" -> "add" -> "ad" and "add" -> "ad". Undoubling only the -ing
    form left "adding" as "ad" and the question's "add" as "add", and every page lost its verb.
    """
    if len(tok) > 5 and tok.endswith("ing"):
        tok = tok[:-3]
    elif len(tok) > 4 and tok.endswith(("ses", "xes", "zes", "ches", "shes")):
        tok = tok[:-2]
    elif len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is", "as")):
        tok = tok[:-1]
    if len(tok) > 2 and tok[-1] == tok[-2] and tok[-1] not in "aeiou":
        tok = tok[:-1]
    return tok


def _tokens(text: str) -> frozenset:
    words = "".join(c if c.isalnum() else " " for c in (text or "").lower()).split()
    return frozenset(_stem(w) for w in words if w not in _STOPWORDS)


def _page_tokens(page: dict) -> frozenset:
    """Title, source file stem and IRI local name: the three places a page states its topic."""
    source = str(page.get("source") or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return (
        _tokens(str(page.get("title") or ""))
        | _tokens(source)
        | _tokens(_local_name(str(page.get("iri") or "")))
    )


def match_pages(identifier: str, pages: Sequence[dict]) -> dict:
    """Score `identifier` against the DocPage pool; bind ONE page or none.

    Returns `{"page", "score", "coverage", "runner_up", "candidates"}`. `page` is None unless
    the winner clears BOTH gates above. `candidates` is every page with a nonzero score, ranked
    and in the `instance_top_candidates` shape (`instance_id`, `class_uri`, `label`, `score`),
    so a refused near-tie still carries the menu a disambiguation ask needs.

    IDF-weighted cosine over binary token sets. The IDF is what separates the engine page from
    the graph page ("Runbook — adding a graph to engine-lg"), whose label also says engine: both
    cover the question, and the shorter claim wins on its norm. The graph page is the control
    that makes this a discrimination and not a keyword hit.
    """
    import math

    empty = {"page": None, "score": 0.0, "coverage": 0.0, "runner_up": 0.0, "candidates": []}
    query = _tokens(identifier)
    pool = [(p, _page_tokens(p)) for p in pages if p.get("iri")]
    if not query or not pool:
        return empty
    n = len(pool)
    df: dict[str, int] = {}
    for _, toks in pool:
        for t in toks:
            df[t] = df.get(t, 0) + 1

    def idf(t: str) -> float:
        return math.log((n + 1) / (df.get(t, 0) + 1)) + 1.0

    q_norm = math.sqrt(sum(idf(t) ** 2 for t in query))
    q_mass = sum(idf(t) for t in query)
    scored = []
    for page, toks in pool:
        shared = query & toks
        if not shared:
            continue
        d_norm = math.sqrt(sum(idf(t) ** 2 for t in toks))
        score = sum(idf(t) ** 2 for t in shared) / (q_norm * d_norm)
        coverage = sum(idf(t) for t in shared) / q_mass
        scored.append((score, coverage, page))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored:
        return empty
    candidates = [
        {
            "instance_id": p["iri"],
            "class_uri": DOCPAGE_CLASS,
            "label": p.get("title") or _local_name(p["iri"]),
            "score": round(s, 4),
        }
        for s, _, p in scored
    ]
    best, coverage, page = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    won = coverage >= MATCH_COVERAGE_FLOOR and runner_up <= MATCH_MARGIN * best
    return {
        "page": page if won else None,
        "score": round(best, 4),
        "coverage": round(coverage, 4),
        "runner_up": round(runner_up, 4),
        "candidates": candidates,
    }
