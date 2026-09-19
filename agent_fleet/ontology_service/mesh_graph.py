"""Engine-o's `MeshGraph` implementation — named reads over Neo4j.

**THIS MODULE IMPORTS NO DRIVER.** The Neo4j driver is INJECTED, the same shape `mesh_vectors.py`
and `state_sparql.py` already use here — which is why this file can be exercised by a test where
`main.py` needs a stub harness. The driver stays in `main.py`, the one place engine-o is entitled
to hold one.

**READ-ONLY, AND THAT IS RULED RATHER THAN OMITTED.** The SDK's Protocol says it outright: the
substrate-read inventory found *zero* Neo4j writes in engine-o — the registrar writes, and state
writes go through the mesh writer with `DERIVED_FROM`. A write half added "for symmetry" would mint
a surface whose only caller does not exist. The fleet write census agrees from the other side: of
88 write sites, none in this engine.

WHAT THE CONTRACT ASKS FOR, and where each part lives:

    identity is an argument         every operation takes `Initiator` and REFUSES `kind="service"`
    the return says WHETHER         MeshResult: answered | empty | failed | unreachable
    a refusal is not a zero         a substrate that could not be asked NEVER renders as `empty`
    the caller owns its disposition an operation reports `failed`; degrading open is the CALLER's
                                    decision, written at the call site

**THE CYPHER LIVES HERE AND ALSO IN `main.py`, WHICH IS A DUPLICATE UNTIL THE ROUTES MIGRATE.**
Duplicate only where a wrong copy FAILS LOUDLY: `tests/test_mesh_graph_conforms.py` reads
`main.py`'s constants by AST and asserts they still match these, so drift reds instead of producing
two engines that answer the same question differently.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from iagent_mesh.interfaces import Initiator, ServiceIdentityRefused
from iagent_mesh.results import MeshResult

#: The hop bound for `path`, which the Protocol signature does not carry — so the implementation
#: must choose one, and **a default invented locally becomes a contract**. Not invented: read from
#: `main.py`'s `FindPathRequest.max_hops = Field(4, ge=1, le=8)`, the fleet's existing declaration.
#: Cypher cannot parameterise a hop range, so it is templated after bounding.
PATH_MAX_HOPS = 4
PATH_HOP_BOUNDS = (1, 8)

#: Read from `main.py`'s `_VALID_COST_CLASSES`; the conformance test asserts the two agree.
VALID_COST_CLASSES = ("fast", "medium", "slow")

#: The ancestor-walk bound, from `_get_subject_ancestor_chain(subject_uri, max_hops: int = 5)`.
ANCESTOR_MAX_HOPS = 5

# ── the queries ─────────────────────────────────────────────────────────────────────────────

ANCESTORS_CYPHER = """
MATCH (start:OntologyClass {uri: $subject_uri})
MATCH path = (start)-[:subClassOf*0..$MAXHOPS$]->(scope:OntologyClass)
WITH scope, length(path) AS hops
ORDER BY hops ASC
RETURN scope.uri AS uri, scope.label AS label, hops
"""

OPERABLE_SUBJECTS_CYPHER = """
MATCH (s:OntologyClass)-[r]->()
WHERE r.iri IS NOT NULL
  AND ($domain IS NULL OR s.domain = $domain)
RETURN DISTINCT s.uri AS uri, s.label AS label
ORDER BY label
"""

#: ONE CYPHER FOR BOTH QUESTIONS, with the referent UNION switched off by a NULL root — so the two
#: reaches cannot drift the way two copies would. `main.py` states the reasoning and it is the
#: reason this constant carries a UNION that looks unconditional: passing `referent_root=None`
#: makes `m.uri = $referent_root` match nothing, which is the whole switch.
CLASSES_WITH_A_VERB_CYPHER = """
MATCH (c:OntologyClass)-[:subClassOf*0..5]->(anc:OntologyClass)
MATCH (anc)-[r]->(:OntologyClass)
WHERE r.iri IS NOT NULL
  AND (
    size($domains) = 0
    OR coalesce(r.domains, []) = []
    OR any(d IN r.domains WHERE d IN $domains)
  )
RETURN DISTINCT c.uri AS uri
UNION
MATCH (c:OntologyClass)-[:subClassOf*1..5]->(m:OntologyClass)
WHERE m.uri = $referent_root
RETURN DISTINCT c.uri AS uri
"""

#: The declared referent marker, from `main.py`'s `_RESOLVABLE_REFERENT_ROOT`.
RESOLVABLE_REFERENT_ROOT = "http://invincible-agent/mesh#ResolvableReferent"

DATA_ASSETS_CYPHER = (
    "MATCH (o:OntologyClass {uri: $uri})-[:HAS_DATA]->(d:DataAsset) RETURN d.urn as urn"
)

PROVIDERS_FOR_CYPHER = """
MATCH (:OntologyClass)-[r]->(:OntologyClass)
WHERE r.iri = $verb
RETURN DISTINCT r.endpoint_url AS endpoint_url,
                r.provider     AS provider,
                r.timeout_s    AS timeout_s,
                coalesce(r.domains, []) AS domains
"""


def build_path_cypher(max_hops: int) -> str:
    """The hop range is TEMPLATED, not parameterised — Cypher does not allow it as a parameter.

    Bounded first, because a templated value is string-interpolated into a query and a bound is the
    only thing standing between that and an injected clause. `main.py` bounds it with Pydantic
    (`ge=1, le=8`); this module has no Pydantic, so it bounds it here — **the same bound, asserted
    equal in the conformance test**, rather than a second opinion about what is safe.
    """
    lo, hi = PATH_HOP_BOUNDS
    if not isinstance(max_hops, int) or isinstance(max_hops, bool) or not lo <= max_hops <= hi:
        raise ValueError(
            f"max_hops must be an int in [{lo}, {hi}] — a hop range is templated into the Cypher, "
            f"so it is bounded before it is interpolated, never after"
        )
    return f"""
    MATCH path = (start:OntologyClass {{uri: $start_uri}})
                 -[rs*1..{max_hops}]->
                 (end:OntologyClass {{uri: $end_uri}})
    WHERE all(r IN relationships(path)
              WHERE coalesce(r.cost_class, 'slow') IN $allowed_cost_classes)
    WITH path, relationships(path) AS rels, length(path) AS hops
    RETURN [r IN rels | {{verb_type: type(r), verb_iri: r.iri}}] AS edges, hops
    ORDER BY hops ASC
    LIMIT 1
    """


class Neo4jGraph:
    """`MeshGraph` over an injected Neo4j driver."""

    #: **EMPTY ON PURPOSE, AND DECLARED RATHER THAN OMITTED.** `MeshVectors` carries
    #: `("hybrid", "bm25")` because retrieval has a degraded path worth marking — the fleet ran
    #: sixty-seven days BM25-only with nothing in any result saying so. A graph read has no such
    #: second path: the query either ran against Neo4j or it did not, and *that* distinction is
    #: already carried by `outcome`. An invented mode here would be a vocabulary with no second
    #: member, which reads as a choice the implementation never makes.
    MODES: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        driver: Any,
        report: Optional[Callable[[str], None]] = None,
        persona_registry_cypher: Optional[str] = None,
        domain_registry_cypher: Optional[str] = None,
    ) -> None:
        self._driver = driver
        self._report = report or (lambda _m: None)
        # `registry` reads two views that live in `registry_views.py`. INJECTED rather than
        # imported so this module keeps one dependency rule ("nothing but the SDK"), and so a test
        # can drive `registry` without the flatten-aware import dance.
        self._persona_cypher = persona_registry_cypher
        self._domain_cypher = domain_registry_cypher

    # ── identity ────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _require_person(initiator: Initiator, operation: str) -> None:
        """A service identity is refused at the boundary.

        Not sniffed from the subject's spelling — `kind` is declared at the edge that minted the
        token, and parsing a subject is the rule this one exists beside, not a cheaper version.
        """
        if initiator.kind == "service":
            raise ServiceIdentityRefused(
                f"{operation}: a read attributed to a service records provenance no person can "
                f"be asked about (subject={initiator.subject!r})"
            )

    # ── the one place a query meets the driver ──────────────────────────────────────────────

    def _read(self, what: str, cypher: str, **params: Any) -> MeshResult:
        """Run one read and say WHICH of the four things happened.

        **`unreachable` AND `failed` ARE DIFFERENT AND NEITHER IS `empty`.** No driver is a
        deployment that never configured one; an exception mid-query is an outage. `[]` was the
        answer to both for years, and a caller holding it read a dead substrate as a confident zero.
        """
        if self._driver is None:
            return MeshResult.unreachable(f"{what}: no Neo4j driver is configured")
        try:
            with self._driver.session() as session:
                rows = [dict(r) for r in session.run(cypher, **params)]
        except Exception as exc:  # noqa: BLE001 — the substrate's failure, whatever shape it takes
            return MeshResult.failed(f"{what}: {type(exc).__name__}: {exc}")
        return MeshResult.answered(rows) if rows else MeshResult.empty()

    # ── operations, in the order the read inventory shows them called ───────────────────────

    def ancestors(self, initiator: Initiator, iri: str, *, max_hops: int) -> MeshResult:
        """The `subClassOf` chain.

        **REFUSES RATHER THAN DEGRADING**, and this operation is why the whole result type exists:
        a failed ancestor walk silently narrows verb compatibility and returns classification to
        pre-ADR-0018 behaviour — validating a verb against the raw `input_uri` string. A degraded
        answer there is indistinguishable from a considered one, and the ADR still reads as
        satisfied because all the code is present.
        """
        self._require_person(initiator, "ancestors")
        lo, hi = PATH_HOP_BOUNDS
        if not isinstance(max_hops, int) or isinstance(max_hops, bool) or not lo <= max_hops <= hi:
            return MeshResult.failed(f"ancestors: max_hops must be an int in [{lo}, {hi}]")
        cypher = ANCESTORS_CYPHER.replace("$MAXHOPS$", str(max_hops))
        return self._read("ancestors", cypher, subject_uri=iri)

    def verbs_for(self, initiator: Initiator, subject: str, *, max_hops: int) -> MeshResult:
        """Predicates that can operate on `subject`, walking the ancestor chain.

        Built on `ancestors` rather than repeating its walk: the compatibility rule is *a verb
        registered against any class in the chain applies to the subject*, so the chain is the
        input and a second copy of the traversal would be a second thing to keep correct.
        """
        self._require_person(initiator, "verbs_for")
        chain = self.ancestors(initiator, subject, max_hops=max_hops)
        if chain.outcome in ("failed", "unreachable"):
            # THE CHAIN'S FAILURE IS THIS OPERATION'S FAILURE. Continuing with an empty chain is
            # exactly the silent narrowing the `ancestors` docstring refuses.
            return MeshResult.failed(f"verbs_for: ancestor chain unavailable — {chain.detail}")
        scopes = [r.get("uri") for r in chain.rows if r.get("uri")]
        if not scopes:
            return MeshResult.empty()
        return self._read(
            "verbs_for",
            """
            UNWIND $scopes AS scope_uri
            MATCH (scope:OntologyClass {uri: scope_uri})-[r]->(o:OntologyClass)
            WHERE r.iri IS NOT NULL
            RETURN DISTINCT r.iri AS verb_iri, type(r) AS verb_type,
                            scope.uri AS input_uri, o.uri AS output_uri
            """,
            scopes=scopes,
        )

    def classes_with_a_verb(
        self, initiator: Initiator, domains: Sequence[str], *, include_referents: bool = False
    ) -> MeshResult:
        """Classes carrying a verb in these domains — the productive-option gate.

        **ITS CALLER DEGRADES OPEN AND THIS OPERATION DOES NOT.** An empty means *do not filter*,
        because failing closed empties the candidate pool and takes routing down globally. That
        disposition belongs to the caller and is written at the call site; reporting `failed`
        honestly here is what lets the caller make it. An exemption from the result type would hide
        the one decision worth showing.

        **`include_referents` SELECTS BETWEEN TWO DIFFERENT QUESTIONS AND THE DEFAULTS DISAGREE.**

            True   *may the resolver OFFER this class?* — a declared `mesh:ResolvableReferent` is
                   groundable on purpose ("lot 4" is a real thing a caller names), so it belongs in
                   the candidate pool. This is the productive-option gate's question.
            False  *can this class be ANSWERED?* — a referent is precisely a class that grounds and
                   cannot be answered, so it must not count as served. The post-preemption check.

        The Protocol declares `include_referents: bool = False`; `main.py`'s `_served_class_uris`
        declares `= True`. **This implementation takes the Protocol's**, because the Protocol is the
        contract — but the two disagree, and the operation's own one-line summary calls it *"the
        productive-option gate"*, which is the `True` question. One of the three is wrong and it is
        not this lane's to rule.

        **THE TRAP IS DELAYED, WHICH IS WHY IT IS FLAGGED RATHER THAN LEFT.** Measured 2026-09-04:
        the referent set is EMPTY in the live graph, so today both questions return the same answer
        and a caller taking the wrong default looks correct. The day someone declares a referent —
        which the ruling says is the RIGHT thing to do — the wrong default silently stops abstaining,
        and nothing goes red. Doing the correct thing would disable the protection.
        """
        self._require_person(initiator, "classes_with_a_verb")
        scoped = [d.upper() for d in (domains or []) if d]
        return self._read(
            "classes_with_a_verb",
            CLASSES_WITH_A_VERB_CYPHER,
            domains=scoped,
            # THE NULL ROOT IS THE SWITCH. `False` must not merely omit referents from a
            # post-filter; it must ask a different question of the graph.
            referent_root=RESOLVABLE_REFERENT_ROOT if include_referents else None,
        )

    def operable_subjects(self, initiator: Initiator, domain: str) -> MeshResult:
        """Classes carrying at least one registered verb, domain-scoped.

        Filtered for THIS initiator — which is why identity is an argument rather than ambient.
        """
        self._require_person(initiator, "operable_subjects")
        return self._read("operable_subjects", OPERABLE_SUBJECTS_CYPHER, domain=domain or None)

    def edge(self, initiator: Initiator, subject: str, verb: str) -> MeshResult:
        """Resolve one predicate edge, cheapest by cost class."""
        self._require_person(initiator, "edge")
        return self._read(
            "edge",
            """
            MATCH (s:OntologyClass {uri: $subject})-[r]->(o:OntologyClass)
            WHERE r.iri = $verb
            RETURN r.iri AS verb_iri, type(r) AS verb_type, o.uri AS output_uri,
                   coalesce(r.cost_class, 'slow') AS cost_class,
                   r.endpoint_url AS endpoint_url
            ORDER BY CASE coalesce(r.cost_class, 'slow')
                       WHEN 'fast' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END ASC
            LIMIT 1
            """,
            subject=subject,
            verb=verb,
        )

    def path(
        self, initiator: Initiator, start: str, end: str, *, cost_classes: Sequence[str]
    ) -> MeshResult:
        """Shortest composition from `start` to `end` within the allowed cost classes."""
        self._require_person(initiator, "path")
        allowed = [c for c in (cost_classes or ()) if c in VALID_COST_CLASSES]
        if not allowed:
            # AN UNKNOWN COST CLASS IS NOT A SILENT WIDENING. Falling back to "all of them" would
            # answer a question nobody asked, using a permission the caller did not give.
            return MeshResult.failed(
                f"path: no recognised cost class in {list(cost_classes or ())!r}; "
                f"valid are {list(VALID_COST_CLASSES)!r}"
            )
        return self._read(
            "path",
            build_path_cypher(PATH_MAX_HOPS),
            start_uri=start,
            end_uri=end,
            allowed_cost_classes=allowed,
        )

    def providers_for(self, initiator: Initiator, verb: str) -> MeshResult:
        """Engines registered as providers of `verb`.

        **THREE STATES, OF WHICH ONLY TWO ARE CACHEABLE** — and this implementation holds no cache
        at all, which is the cheapest way to obey that. `registered` and `none-registered` are
        checked answers; `unreachable` is not an answer. Caching it would silence enumeration for a
        whole TTL, which is exactly how a failed lookup came to render as *"no provider is
        registered"*. Any cache layered above this MUST read `outcome` before storing.
        """
        self._require_person(initiator, "providers_for")
        return self._read("providers_for", PROVIDERS_FOR_CYPHER, verb=verb)

    def data_assets_for(self, initiator: Initiator, iri: str) -> MeshResult:
        """Physical dataset URNs behind an ontology IRI."""
        self._require_person(initiator, "data_assets_for")
        return self._read("data_assets_for", DATA_ASSETS_CYPHER, uri=iri)

    def registry(self, initiator: Initiator) -> MeshResult:
        """Which personas and domains are active.

        TWO VIEWS, ONE RESULT, and a partial answer is a FAILURE rather than half a registry: a
        caller told which personas exist but not which domains would filter against a set it
        cannot see.
        """
        self._require_person(initiator, "registry")
        if not (self._persona_cypher and self._domain_cypher):
            return MeshResult.unreachable(
                "registry: the persona/domain views were not supplied to this implementation"
            )
        personas = self._read("registry(personas)", self._persona_cypher)
        if personas.outcome in ("failed", "unreachable"):
            return personas
        domains = self._read("registry(domains)", self._domain_cypher)
        if domains.outcome in ("failed", "unreachable"):
            return domains
        rows = [{"kind": "persona", **r} for r in personas.rows]
        rows += [{"kind": "domain", **r} for r in domains.rows]
        return MeshResult.answered(rows) if rows else MeshResult.empty()
