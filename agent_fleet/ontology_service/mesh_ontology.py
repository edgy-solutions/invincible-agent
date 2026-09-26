"""`MeshOntology` over Jena — the two named reads, and no write half.

WHAT THIS IS. The SDK declares `MeshOntology` as a Protocol with exactly two operations, `ask`
and `construct`, and `MODES = ()`. This is engine-o's implementation of it. **It is deliberately
not wired to a route**: the order that asked for it said not to, and there is a reason worth
recording — a route would fix the transport shape before the conformance test from lane/ca has
said whether this implementation is right, and an interface with a live caller is much harder to
correct than one without.

THREE THINGS THE PROTOCOL DECIDES FOR US, each of which I would otherwise have got wrong.

1. **The operations are SYNC.** `inspect.iscoroutinefunction` on both Protocol methods is False,
   measured, not assumed. engine-o already owns `_run_ask` and `_run_construct_turtle` in
   `main.py` and both are `async` — so the obvious "reuse what is there" is the one thing that
   cannot be done. Reusing them would have meant either an event loop inside a sync method or
   changing the Protocol's shape, and the Protocol is not ours to change. What IS reused is the
   endpoint and the POST form; the async helpers stay where they are for their own callers.

2. **`empty` and `unreachable` are different answers and collapsing them is the defect the
   result type exists to end.** The Protocol's own docstring for `ask` says so: "`empty` means
   *asked, and it does not exist*, which is not the same as *could not ask*. Collapsing those is
   how a decision-record write came to be guarded by a check that could not fail." So an
   unreachable store returns `unreachable` WITH a detail, never `empty`, and never a bare False.
   A guard written over this interface can therefore tell "no" from "I could not look", which is
   the whole point.

3. **A service identity is refused at the boundary, and `kind` is DECLARED, never sniffed.** The
   refusal goes through `Initiator.require_person()` rather than a local check, because the SDK's
   own docstring records that inspecting the subject for a `svc:` prefix or a
   `service-account-` shape violates the older rule that identity is carried opaque — and that
   such a parser "mislabels at work, and it mislabels SILENTLY because both readings produce a
   plausible identity". Refusing through the SDK's helper means this file has no opinion about
   subject spellings at all.

4. **Every read records what it read, and THIS OBJECT records it.** `check_live` fails an
   implementation that supplies no provenance reader, with the reason that this is "the property
   that CANNOT be checked offline", and fails one that records nothing with "the abstraction
   records it, not the engine remembering to — an implementation that leaves it to the caller has
   moved the property back to where it was lost". So `provenance()` is part of this class, not a
   hook the route is trusted to call. Each record carries the initiator's subject, which is what
   closes the loop with point 3: refusing a service identity only matters because the subject is
   the thing written into the provenance line, and "a read attributed to a service records
   provenance no person can be asked about" is the SDK's own wording for why.

   Two consequences worth stating rather than leaving to be inferred. The record happens at ONE
   exit (`_read`), not next to each of the four returns, because four placements is four chances
   to forget and the forgotten one looks exactly like a read that never happened. And a request
   refused before any query exists — a service identity, or an IRI the grammar forbids — RAISES
   and records nothing: there is no read to attribute, the caller gets an exception rather than a
   result, and a provenance line for a query that was never sent would be the same false trail
   the property is here to prevent.

WHY `construct` PARSES. The Protocol says "TYPES INTACT IS THE POINT: the SELECT executor drops
them, so a typed read has to be a CONSTRUCT and parse rather than a SELECT and guess." So rows are
parsed rdflib triples, with `URIRef`/`Literal`/`BNode` intact, not Turtle text and not stringified
terms. Handing back the raw Turtle would move the parse to every consumer and lose the types at
the first one that used `str()`.

WHY NO `mode` IS EVER EMITTED. `MeshOntology.MODES` is `()`, and the result type's own comment
says `mode` is "absent for a read with only one way to answer". A SPARQL read has one way. The
conformance checker fails any mode not in the declared set, so emitting a helpful-looking
`mode="sparql"` would red the suite — correctly, because a consumer cannot anticipate it.

AN IRI IS A PARAMETER CROSSING INTO AN EMBEDDED LANGUAGE, AND THIS FILE'S NEIGHBOUR DOES NOT
GUARD IT. `state_sparql.py` has `sparql_lit` for string literals and interpolates IRIs raw as
`<{s}>`. An IRI containing `>` closes the bracket early and the rest of the caller's string is
parsed as SPARQL. That is not a hypothetical about this file: both operations here take an IRI
from the caller and put it inside `<...>`. So `_checked_iri` rejects the characters the grammar
forbids inside an IRIREF before any query text exists, and it raises rather than sanitising —
a silently rewritten IRI would read a DIFFERENT subject and answer confidently about it.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Optional, Tuple

import httpx
from iagent_mesh import Initiator, MeshResult

#: Characters the SPARQL 1.1 grammar forbids inside an IRIREF (`<...>`), plus the control range.
#: Rejected, never escaped: there is no escape for them in an IRIREF, so "escaping" would mean
#: substituting a different IRI and answering about the wrong subject.
_IRI_FORBIDDEN = set('<>"{}|^`\\ \t\n\r')

_DEFAULT_TIMEOUT = 10.0


def _checked_iri(value: str, *, argument: str) -> str:
    """The IRI, or a ValueError naming which argument and which character.

    Raises rather than repairing. A repaired IRI is a different IRI, and a read that answers
    about a subject the caller did not name is worse than a read that refuses.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{argument} must be a non-empty IRI string, got {value!r}")
    bad = sorted(ch for ch in value if ch in _IRI_FORBIDDEN or ord(ch) < 0x21)
    if bad:
        raise ValueError(
            f"{argument}={value!r} contains {bad!r}, which cannot appear inside a SPARQL "
            f"IRIREF. Refused rather than escaped — an IRIREF has no escape for these, so "
            f"any repair would read a different subject."
        )
    return value


class JenaMeshOntology:
    """`MeshOntology` over a Fuseki/Jena SPARQL endpoint.

    `post` is injectable so the offline conformance arm can run without a substrate and so a
    seal can drive the unreachable branch without a network. The default posts with `httpx`.
    """

    #: The Protocol declares `MODES = ()` — a SPARQL read answers one way, so no mode is emitted.
    #: Kept as an explicit attribute rather than inherited so the conformance checker's
    #: `declared_modes` can be read off the class that will be handed to it.
    MODES: Tuple[str, ...] = ()

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        post: Optional[Any] = None,
        provenance_limit: int = 512,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._post = post
        # BOUNDED ON PURPOSE. engine-o is long-lived, and an unbounded provenance list is a slow
        # leak that only shows up in a pod nobody restarted. The cap is a ring, so the property
        # "a completed read recorded something" holds forever while memory does not grow.
        self._provenance: Deque[str] = deque(maxlen=provenance_limit)

    def provenance(self) -> Tuple[str, ...]:
        """What this instance has read, oldest first.

        Required by the interface's live conformance arm, and recorded HERE rather than by a
        caller: a property the caller has to remember is the property that was already lost once.
        """
        return tuple(self._provenance)

    def _record(
        self,
        operation: str,
        *,
        initiator: Initiator,
        target: str,
        graph: Optional[str],
        outcome: str,
    ) -> None:
        """One provenance line per read attempt, carrying WHO asked.

        Attempts are recorded too, not just answers: a read that could not reach the store is
        still a read someone made, and a provenance trail that silently omits the failures is the
        trail you cannot use to explain what happened.
        """
        self._provenance.append(
            f"{operation} target={target} graph={graph or '-'} "
            f"outcome={outcome} initiator={initiator.subject}"
        )

    def _read(
        self,
        operation: str,
        *,
        initiator: Initiator,
        target: str,
        graph: Optional[str],
        query: str,
        accept: str,
        interpret: Callable[[Any], MeshResult],
    ) -> MeshResult:
        """Run one read and record it at the SINGLE exit every outcome passes through.

        Recording here rather than next to each `return` is the point of this method. `ask` and
        `construct` each have four ways to end — rejected, unreachable, unreadable body, and the
        answered/empty pair — and a record placed at each of them is four chances to forget one.
        The one that got forgotten would be indistinguishable from a read that never happened,
        which is the exact failure the provenance property exists to prevent; and a fifth outcome
        added later cannot escape a funnel it has to return through.

        `interpret` sees only a 2xx body: the transport outcomes are decided before it runs, so a
        parser can never be handed an error page and mistake it for an absence.
        """
        try:
            body = self._sparql(query, accept=accept)
        except _Refused as exc:
            result = MeshResult.failed(detail=str(exc))
        except _Unreachable as exc:
            result = MeshResult.unreachable(detail=str(exc))
        else:
            result = interpret(body)

        self._record(
            operation,
            initiator=initiator,
            target=target,
            graph=graph,
            outcome=result.outcome,
        )
        return result

    # ── the two operations ───────────────────────────────────────────────────────────────────

    def ask(
        self, initiator: Initiator, *, iri: str, graph: Optional[str] = None
    ) -> MeshResult:
        """Does this IRI (optionally within this graph) resolve?

        `answered` carries the IRI that resolved — a boolean question still returns rows, because
        the result type forbids `answered` with none, and the IRI is the only honest row: it says
        WHICH subject the yes is about, which a bare `True` does not.
        """
        initiator.require_person("ask")
        subject = _checked_iri(iri, argument="iri")
        named = _checked_iri(graph, argument="graph") if graph is not None else None

        # THE UNION MUST SIT INSIDE A GROUP. `ASK { A } UNION { B }` is a 400, not a result, and
        # the first version of this line was exactly that — caught by the positive control, which
        # is the argument for having one. "Resolves" means the IRI appears in either position:
        # a class nothing points at still resolves, and so does one that is only ever an object.
        pattern = f"{{ {{ <{subject}> ?p ?o }} UNION {{ ?s ?p2 <{subject}> }} }}"
        query = (
            f"ASK {{ GRAPH <{named}> {pattern} }}" if named else f"ASK {pattern}"
        )

        def interpret(body: Any) -> MeshResult:
            try:
                resolved = bool(body.json().get("boolean", False))
            except ValueError as exc:
                # A 200 whose body is not the results JSON is a FAILURE, not an absence: the
                # store answered and we could not read it, which no `empty` stands in for.
                return MeshResult.failed(
                    detail=f"ASK returned a body that is not sparql-results+json: {exc}"
                )
            return MeshResult.answered(rows=(subject,)) if resolved else MeshResult.empty()

        return self._read(
            "ask",
            initiator=initiator,
            target=subject,
            graph=named,
            query=query,
            accept="application/sparql-results+json",
            interpret=interpret,
        )

    def construct(
        self, initiator: Initiator, *, subject: str, graph: Optional[str] = None
    ) -> MeshResult:
        """A typed subgraph as parsed triples, term types intact.

        Rows are rdflib triples, not Turtle text: the Protocol's reason for CONSTRUCT over SELECT
        is that the SELECT executor drops term types, and handing back text moves the parse to
        every consumer and loses the types at the first one that calls `str()`.
        """
        initiator.require_person("construct")
        iri = _checked_iri(subject, argument="subject")
        named = _checked_iri(graph, argument="graph") if graph is not None else None

        inner = f"{{ <{iri}> ?p ?o }}"
        query = (
            f"CONSTRUCT {{ <{iri}> ?p ?o }} WHERE {{ GRAPH <{named}> {inner} }}"
            if named
            else f"CONSTRUCT {{ <{iri}> ?p ?o }} WHERE {inner}"
        )

        def interpret(body: Any) -> MeshResult:
            from rdflib import Graph  # local: rdflib import cost stays off the import path

            parsed = Graph()
            try:
                parsed.parse(data=body.text, format="turtle")
            except Exception as exc:  # rdflib raises several unrelated types for bad Turtle
                return MeshResult.failed(detail=f"CONSTRUCT returned unparseable Turtle: {exc}")

            triples = tuple(parsed)
            return MeshResult.answered(rows=triples) if triples else MeshResult.empty()

        return self._read(
            "construct",
            initiator=initiator,
            target=iri,
            graph=named,
            query=query,
            accept="text/turtle",
            interpret=interpret,
        )

    # ── transport ────────────────────────────────────────────────────────────────────────────

    def _sparql(self, query: str, *, accept: str) -> Any:
        """POST the query, or raise `_Unreachable`/`_Refused` with a detail that says what failed.

        THE SPLIT AT 4xx IS NOT COSMETIC, and I got it wrong first. Everything that means "could
        not ask" — no endpoint configured, connect error, timeout, 5xx — is `_Unreachable`. But a
        **4xx means the store answered and rejected the request**, which is `failed`, not
        unreachable. The first version of this method mapped every non-2xx to unreachable, and
        then my own malformed ASK came back 400 and was reported as "the store is unreachable"
        about a store that had just answered twice in the same second. A classification that
        turns my bug into an infrastructure symptom is worse than no classification, because it
        sends the next person to the network.
        """
        if not self._endpoint:
            raise _Unreachable("no SPARQL endpoint configured")

        try:
            if self._post is not None:
                resp = self._post(
                    self._endpoint, data={"query": query}, headers={"Accept": accept}
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(
                        self._endpoint, data={"query": query}, headers={"Accept": accept}
                    )
        except Exception as exc:
            raise _Unreachable(f"{type(exc).__name__}: {exc}") from exc

        status = getattr(resp, "status_code", None)
        if status is None:
            raise _Unreachable("response carried no status_code")
        if 400 <= status < 500:
            raise _Refused(
                f"endpoint REJECTED the query with HTTP {status} — the store answered, so this "
                f"is a malformed or unauthorised query, not an unreachable store"
            )
        if not (200 <= status < 300):
            raise _Unreachable(f"endpoint answered HTTP {status}")
        return resp


class _Unreachable(RuntimeError):
    """Internal: transport could not ask. Converted to `MeshResult.unreachable` at the boundary.

    Private on purpose — the SDK's vocabulary is the public one, and a second exception type
    escaping this module would give callers two things to catch for one condition.
    """


class _Refused(RuntimeError):
    """Internal: the store answered and rejected the query (4xx). Becomes `MeshResult.failed`.

    Separate from `_Unreachable` because the two send a reader to different places — one to the
    query, one to the network — and the one time they were merged here, a malformed query of mine
    was reported as an unreachable store.
    """
