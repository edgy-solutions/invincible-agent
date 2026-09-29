"""``Neo4jGraphWriter`` — this fleet's ``MeshGraphWriter`` over the property graph.

── THE PROTOCOL'S PREMISE IS FALSE, AND MEASURING IT IS THE FIRST CALLER'S JOB ──────────────
``MeshGraphWriter``'s own docstring says no derived inventory exists because "nothing in the fleet
writes the property graph today", and declares itself deliberately minimal — one edge, one verb —
"so the first real caller defines what more is needed". This module is that first caller, and the
premise does not hold. Enumerated 2026-09-28 over the tracked tree, five write paths already exist:

    agent_fleet/mesh_registrar/v2_substrate.py  merge_neo4j_predicate_edge          MERGE
                                                sync_parameterised_by_edges         DELETE + MERGE
                                                compensate_parameterised_by_edges   DELETE
                                                compensate_neo4j_predicate_edge     DELETE
    src/iagent/answer_artifact_writer.py         write_sync()/_tx_merge              MERGE x16

⛔ CORRECTED 2026-09-28, same day, by re-deriving the table instead of re-reading it: the last row
said ``merge()/_tx_merge  MERGE x6``. ``merge()`` DOES NOT EXIST — the entry point is
``write_sync()`` (``answer_artifact_writer.py:270``) — and the count inside ``_tx_merge`` is
**16**, not 6
(``awk 'NR>=445 && NR<=690 && /MERGE/' src/iagent/answer_artifact_writer.py | wc -l``). Both errors
point the same way: the row UNDERSTATED the path it was citing, while the sentence it supports
("the premise is false") was already true on the row's own weakest reading, so nothing here failed
and nothing would have. That is the shape to distrust — a precise figure inside an argument that
does not depend on it is the figure nobody re-checks. The path COUNT (five) is unchanged and was
independently re-derived from the execution sites: 5 of 6 ``session.run`` calls in
``v2_substrate.py`` carry MERGE or DELETE (the 6th, :866, undecided at this resolution), and
``answer_artifact_writer.py`` has 7 execution sites.

So the Protocol was shaped against an inventory of zero when the real inventory is five, and the
shortfall that follows is recorded in :meth:`Neo4jGraphWriter.write_edge` rather than papered over
here. A contract sized to "no callers" is not a smaller version of the contract the callers need.

── THE ROUTE ────────────────────────────────────────────────────────────────────────────────
``driver.session().run(cypher, **params)`` over Bolt, against the same driver the registrar and
engine-o already construct (``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD``). The driver is
INJECTED, never built here: six sites in this repo construct one, and a seventh hidden inside a
writer would be a seventh place to fix when the credentials move.

── THE VERB IS A PARAMETER, NOT AN INTERPOLATION, AND THAT IS STRUCTURAL ────────────────────
A Neo4j relationship TYPE cannot be parameterised in plain Cypher — `MATCH (a)-[r:$type]->(b)` is
not a thing — so the obvious implementation builds the type into the query string, which makes
``verb`` an injection vector in exactly the way ``JenaOntologyWriter`` refuses for an IRI
reference. ``apoc.merge.relationship`` takes the type as an ARGUMENT, so this writer passes
``verb`` as data and there is no interpolation of caller input anywhere in this module. The hazard
is absent by construction rather than defended by a validator, which is the stronger of the two.

What IS interpolated is the node label and key property, and they are validated ONCE at
construction against an identifier pattern, never per call. That split is the whole safety
argument: CONFIG reaches the query text and is checked when it is declared; REQUEST DATA never
reaches the query text at all.

APOC is a real dependency of this choice and the fleet already carries it — ``_MERGE_CYPHER`` in
the registrar has used ``apoc.merge.relationship`` since ``a44b9fb``. Where it is absent the call
returns ``failed`` with Neo4j's own message, which is the honest outcome: we asked, the store
refused.

── MATCH, NEVER CREATE, AND A MISSING ENDPOINT IS `failed` NOT `refused` ────────────────────
Both endpoints must already exist. A ``write_edge`` that created its own endpoints would turn a
typo in ``subject`` into a new node that looks like data, and the fleet already treats a missing
endpoint as a Contract D violation rather than something to invent (``merge_neo4j_predicate_edge``
raises on it). The refusal split then follows the SDK's own rule: a missing endpoint is discovered
BY asking the store, so it is ``failed`` — ``refused`` is reserved for what this writer declines
before touching Neo4j at all.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from iagent_mesh.interfaces import Initiator
from iagent_mesh.write_results import MeshWriteResult

__all__ = ["Neo4jGraphWriter"]

#: A Cypher label or property key this class is willing to interpolate. Deliberately narrower than
#: Neo4j's own rules, which permit backtick-quoted names containing nearly anything: the point is
#: not to support every legal label but to admit only shapes that cannot terminate the token they
#: sit in.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: ``neo4j.exceptions`` names that mean WE NEVER GOT TO ASK — the ``unreachable`` half of the split.
#: Module level so a test can resolve every entry against the real module: these are STRINGS, and a
#: misspelled one is not a compile error, it is a guard that silently never fires and files a dead
#: cluster as a code defect. See ``tests/test_mesh_writers_conform.py``.
#:
#: Deliberately NOT here: ``ConfigurationError`` and ``ResultConsumedError``. Neither is the store
#: being out of reach — one is this process built wrong, the other is this code using a consumed
#: result — and filing either as ``unreachable`` would send an operator to look at a cluster over a
#: defect that travels with the image.
_TRANSPORT = frozenset({
    "ServiceUnavailable",
    "SessionExpired",
    "ConnectionAcquisitionTimeoutError",
})

#: MERGE the edge on the (subject, verb, object) triple. `apoc.merge.relationship` UPDATES when the
#: match-key already matched, so a replayed call is the same write — the idempotency the registrar's
#: own merge documents, inherited by using the same procedure.
_MERGE_EDGE = """
MATCH (mesh_s:{label} {{{key}: $subject}})
MATCH (mesh_o:{label} {{{key}: $object}})
CALL apoc.merge.relationship(mesh_s, $verb, {{}}, {{}}, mesh_o, {{}}) YIELD rel
RETURN type(rel) AS rel_type
"""


class Neo4jGraphWriter:
    """Concrete ``MeshGraphWriter`` over a Bolt driver. One edge, one verb, no properties.

    Structurally satisfies ``iagent_mesh.interfaces.MeshGraphWriter``; no inheritance, matching the
    SDK's own posture.
    """

    def __init__(
        self,
        *,
        driver: Any,
        node_label: str = "OntologyClass",
        node_key: str = "uri",
    ) -> None:
        if driver is None:
            raise ValueError("driver is None — a writer with nothing to write through is not a writer")
        for name, value in (("node_label", node_label), ("node_key", node_key)):
            if not _SAFE_IDENTIFIER.match(value or ""):
                raise ValueError(
                    f"{name}={value!r} is not a bare identifier. This value is interpolated into "
                    f"Cypher, so it is checked HERE, at declaration, where it is a constant — the "
                    f"per-call arguments are passed as parameters and never reach the query text."
                )
        self._driver = driver
        self._label = node_label
        self._key = node_key
        self._cypher = _MERGE_EDGE.format(label=node_label, key=node_key)

    def write_edge(
        self, initiator: Initiator, *, subject: str, verb: str, object: str
    ) -> MeshWriteResult:
        """MERGE ``(subject)-[:verb]->(object)``, both endpoints required to exist.

        ⚠ **THE IDENTITY THIS METHOD CAN EXPRESS IS WEAKER THAN THE FLEET'S, AND THE REGISTRAR
        THEREFORE CANNOT ADOPT IT.** The match-key here is the ``(subject, verb, object)`` triple,
        because that is all the Protocol's signature carries. The registrar's predicate edge is
        keyed on ``(verb_iri, _tool_urn)`` and carries a property bag — ``provider``,
        ``endpoint_url``, ``timeout_s``, ``owner_persona`` — that engine-o's discovery reads.
        Routing this method in its place would:

        * drop every property, so a registered verb becomes undiscoverable; and
        * collapse N providers of one predicate into ONE edge with last-write-wins, which is
          precisely the defect ``a44b9fb`` fixed and which
          ``tests/routing/test_substrate_invariants.py::test_mesh_resolve_instance_has_one_edge_per_provider``
          pins on a LIVE cluster by reading ``r.provider``, ``r.endpoint_url``, ``r.timeout_s`` and
          ``r._tool_urn`` off the edge.

        That is a data-loss regression against a pinned invariant, not a widening preference, so the
        old path stays and the manifest for what ``MeshGraphWriter`` must gain is routed to the
        contract's author. The Protocol says widening it is "a new method with its own manifest and
        seal"; this docstring is the manifest's evidence, measured rather than argued.
        """
        # THE IDENTITY GATE RAISES; IT DOES NOT RETURN `refused`. The first draft converted
        # `ServiceIdentityRefused` into a refused result and `check_writer_offline` rejected it: a
        # `refused` is a value a caller can ignore, and an unauthorized write is not an outcome to
        # weigh but a call that may not be made. `refused` stays for what is declined on the MERITS.
        initiator.require_person_or_delegate("graph.write_edge")

        for label, value in (("subject", subject), ("verb", verb), ("object", object)):
            if not (value or "").strip():
                return MeshWriteResult.refused(f"{label} is empty")

        # `verb` is passed as an argument to apoc.merge.relationship, so it is never interpolated —
        # but an empty-after-strip type would MERGE a relationship whose type is whitespace, which
        # no reader queries for. Refused above rather than stored unfindably.
        return self._run(self._cypher, subject=subject, verb=verb, object=object)

    def _run(self, cypher: str, **params: Any) -> MeshWriteResult:
        """Execute and classify every STORE outcome into a result rather than an exception.

        Narrower than it first read: the identity gate above raises, so "does not raise at its
        caller" is true of the store and false of authorization. What this method promises is that
        no driver exception escapes as a driver exception.
        """
        try:
            with self._driver.session() as session:
                record = session.run(cypher, **params).single()
        except Exception as exc:  # noqa: BLE001 — classified immediately below, never swallowed
            detail = f"{type(exc).__name__}: {exc}"
            if self._is_transport(exc):
                return MeshWriteResult.unreachable(detail)
            # Everything else reached Neo4j and was refused or errored there, including the case
            # where APOC is not installed. `failed` says "we asked"; that distinction is what an
            # operator reads to decide between a deployment problem and a query defect.
            return MeshWriteResult.failed(detail)

        if record is None:
            return MeshWriteResult.failed(
                f"MATCH returned no record: one or both endpoints are missing from the graph "
                f"({self._label}.{self._key} in $subject/$object). This writer does not create its "
                f"endpoints — a typo would otherwise become a node that looks like data."
            )
        return MeshWriteResult.written()

    @staticmethod
    def _is_transport(exc: BaseException) -> bool:
        """Transport-level, i.e. we never got to ask — the ``unreachable`` half of the split.

        Matched on the driver's own exception NAMES rather than by importing them, so this module
        stays importable where the driver is absent (the offline conformance arms construct the
        writer with a stub and never open a socket). The names come from ``neo4j.exceptions``;
        ``OSError`` covers the socket layer underneath them.
        """
        if isinstance(exc, OSError):
            return True
        return type(exc).__name__ in _TRANSPORT
