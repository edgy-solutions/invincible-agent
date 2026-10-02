"""``Neo4jGraphWriter`` — this fleet's ``MeshGraphWriter`` over the property graph (SDK v0.9.5).

── ONE CLASS, SEVERAL EDGE FAMILIES ─────────────────────────────────────────────────────────
``EdgeIdentity`` is four opaque strings — subject, verb, object, key. The graph spells them
differently per family of edge, and the writer is CONFIGURED with the spelling rather than
guessing it:

    family            node label / key        relationship type        verb prop   key prop
    predicate         OntologyClass / uri     local name of the verb   iri         _tool_urn
    PARAMETERISED_BY  OntologyClass / uri     PARAMETERISED_BY         verb_iri    _tool_urn
    ingest facts      IngestArtifact / ...    fixed                    verb        ingest_id

The predicate row is what ``Neo4jGraph.edge()`` reads (``r.iri = $verb``); the second is what
engine-o's pool reads (``p.verb_iri``/``p._tool_urn``); the third is the promotion family. A
delete or existence check ALWAYS requires both identity properties to be present on the edge
(``r[verb_property] IS NOT NULL AND r[key_property] IS NOT NULL``), and — when the type is fixed —
``type(r) = $rel_type``. That is what keeps a key-only filter from crossing families: a
PARAMETERISED_BY edge carries no ``iri`` and a predicate edge no ``verb_iri``, so neither
family's sweep can reach the other's edges, whatever the filter leaves unbound.

── WHAT REACHES THE QUERY TEXT, AND WHAT NEVER DOES ─────────────────────────────────────────
CONFIG is interpolated: the node label and the three property names. Each is checked ONCE at
construction against ``_SAFE_IDENTIFIER``. REQUEST DATA never is: subject, object, verb and key
are parameters, and the relationship TYPE is passed to ``apoc.merge.relationship`` as an argument
and compared with ``type(r) = $rel_type`` — a Neo4j type cannot be parameterised in a pattern, so
the obvious implementation interpolates it, and this one does not. A verb is therefore never an
injection vector, by construction rather than by a validator.

── MATCH, NEVER CREATE ──────────────────────────────────────────────────────────────────────
Both endpoints must already exist. A write that created its own endpoints would turn a typo in
``subject`` into a node that looks like data. A missing endpoint is discovered BY asking the store,
so it is ``failed`` (SDK: "refused — declined before touching the store"), and its detail starts
with :data:`ENDPOINT_ABSENT` so a caller that treats an absent referent differently from a store
fault — the registrar's ``unresolved`` — can tell the two apart without parsing prose.

── PAYLOAD: WIDER THAN THE PROTOCOL'S ANNOTATION, REFUSED NOT STRIPPED ──────────────────────
``write_edge`` annotates ``payload: Mapping[str, str]``. The registrar's predicate edge carries
lists (``domains``, ``synonyms``) and a bool (``requires_human_approval``) that engine-o reads as
those types, so this writer accepts what Neo4j itself accepts as a property: a primitive, or a
homogeneous list of one primitive type. Anything else — a map, ``None``, a nested or mixed list —
REFUSES the whole write before the store is touched; nothing is dropped from the payload to make
the rest fit. A payload key equal to the verb or key property is refused too: identity is set
from ``identity`` alone, never overridden by the payload riding beside it.

── THE ROUTE ────────────────────────────────────────────────────────────────────────────────
``driver.session().run(cypher, **params)``. The driver is INJECTED, never built here.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Optional, Union

from iagent_mesh.interfaces import EdgeIdentity, EdgeIdentityFilter, Initiator
from iagent_mesh.results import MeshResult
from iagent_mesh.write_results import MeshWriteResult

__all__ = ["ENDPOINT_ABSENT", "Neo4jGraphWriter"]

#: A label or property name this class will interpolate. Narrower than Neo4j's own rules on
#: purpose: only shapes that cannot terminate the token they sit in.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Characters that survive into a relationship type only when an IRI was not reduced to its local
#: name. A type is passed to apoc as a parameter, so Neo4j accepts `//invincible-agent/mesh#explain`
#: as a type; nothing that reads the graph by the verb's local name will ever find it. The writer
#: refuses rather than writes it, whichever family function produced it.
_IRI_MARKS = frozenset(":/#")

#: ``neo4j.exceptions`` names meaning WE NEVER GOT TO ASK — the ``unreachable`` half. Matched by
#: name so this module imports where the driver is absent; each is resolved against the real module
#: by a test, because a misspelled entry is a guard that never fires.
_TRANSPORT = frozenset({
    "ServiceUnavailable",
    "SessionExpired",
    "ConnectionAcquisitionTimeoutError",
})

#: The detail prefix of the ``failed`` a write returns when an endpoint node is not in the graph.
ENDPOINT_ABSENT = "endpoint_absent"

_PRIMITIVES = (str, bool, int, float)

_WRITE = """
MATCH (mesh_s:{label} {{{key}: $subject}})
MATCH (mesh_o:{label} {{{key}: $object}})
CALL apoc.merge.relationship(mesh_s, $rel_type, $identity, $props, mesh_o, $props) YIELD rel
RETURN count(rel) AS n
"""

#: Shared by delete and has: every bound filter field narrows, every unbound one is a wildcard,
#: and the family discriminator is unconditional.
_MATCH_FILTER = """
MATCH (mesh_s:{label})-[mesh_r]->(mesh_o:{label})
WHERE mesh_r.{verb_prop} IS NOT NULL AND mesh_r.{key_prop} IS NOT NULL
  AND ($rel_type IS NULL OR type(mesh_r) = $rel_type)
  AND ($subject IS NULL OR mesh_s.{key} = $subject)
  AND ($object IS NULL OR mesh_o.{key} = $object)
  AND ($verb IS NULL OR mesh_r.{verb_prop} = $verb)
  AND ($edge_key IS NULL OR mesh_r.{key_prop} = $edge_key)
"""

_DELETE = _MATCH_FILTER + """
WITH collect(mesh_r) AS rs
FOREACH (r IN rs | DELETE r)
RETURN size(rs) AS n
"""

_HAS = _MATCH_FILTER + """
RETURN mesh_s.{key} AS subject, mesh_r.{verb_prop} AS verb, mesh_o.{key} AS object,
       mesh_r.{key_prop} AS key
"""


class Neo4jGraphWriter:
    """Concrete ``MeshGraphWriter``. Structurally satisfies the Protocol; no inheritance."""

    def __init__(
        self,
        *,
        driver: Any,
        node_label: str,
        node_key: str,
        relationship_type: Union[str, Callable[[str], str]],
        verb_property: str,
        key_property: str,
    ) -> None:
        for label, value in (("node_label", node_label), ("node_key", node_key),
                             ("verb_property", verb_property), ("key_property", key_property)):
            if not isinstance(value, str) or not _SAFE_IDENTIFIER.match(value):
                raise ValueError(f"{label}={value!r} is not a safe Cypher identifier")
        if verb_property == key_property:
            raise ValueError("verb_property and key_property are one property — identity would "
                             "collapse from four fields to three")
        if isinstance(relationship_type, str):
            if not relationship_type.strip():
                raise ValueError("relationship_type is empty")
        elif not callable(relationship_type):
            raise ValueError("relationship_type is neither a type name nor a function of the verb")
        self._driver = driver
        self._rel_type = relationship_type
        self._verb_prop = verb_property
        self._key_prop = key_property
        names = dict(label=node_label, key=node_key, verb_prop=verb_property,
                     key_prop=key_property)
        self._write_cypher = _WRITE.format(**names)
        self._delete_cypher = _DELETE.format(**names)
        self._has_cypher = _HAS.format(**names)

    # ── the three operations ────────────────────────────────────────────────────────────────

    def write_edge(
        self,
        initiator: Initiator,
        *,
        identity: EdgeIdentity,
        payload: Mapping[str, Any] = {},
    ) -> MeshWriteResult:
        initiator.require_person_or_delegate("graph.write_edge")
        if not isinstance(identity, EdgeIdentity):
            return MeshWriteResult.refused(
                f"identity is {type(identity).__name__}, not EdgeIdentity")
        props, why = self._payload(payload)
        if why:
            return MeshWriteResult.refused(why)
        rel_type = self._type_for(identity.verb)
        if not rel_type:
            return MeshWriteResult.refused(f"verb {identity.verb!r} names no relationship type")
        if _IRI_MARKS.intersection(rel_type):
            return MeshWriteResult.refused(
                f"verb {identity.verb!r} yields relationship type {rel_type!r}, which still "
                "carries an IRI's ':', '/' or '#'; the family's type function did not reduce it "
                "to a local name")
        props[self._verb_prop] = identity.verb
        props[self._key_prop] = identity.key
        record, failure = self._run(
            self._write_cypher, subject=identity.subject, object=identity.object,
            rel_type=rel_type, identity={self._verb_prop: identity.verb,
                                         self._key_prop: identity.key},
            props=props,
        )
        if failure is not None:
            return failure
        if record is None or not record["n"]:
            return MeshWriteResult.failed(
                f"{ENDPOINT_ABSENT}: MATCH found no node for subject={identity.subject!r} or "
                f"object={identity.object!r}; this writer never creates an endpoint")
        return MeshWriteResult.written()

    def delete_edges(
        self, initiator: Initiator, *, identity_filter: EdgeIdentityFilter
    ) -> MeshWriteResult:
        initiator.require_person_or_delegate("graph.delete_edges")
        if not isinstance(identity_filter, EdgeIdentityFilter):
            return MeshWriteResult.refused(
                f"identity_filter is {type(identity_filter).__name__}, not EdgeIdentityFilter")
        _record, failure = self._run(self._delete_cypher, **self._filter_params(identity_filter))
        return failure if failure is not None else MeshWriteResult.written()

    def has_edges(
        self, initiator: Initiator, *, identity_filter: EdgeIdentityFilter
    ) -> MeshResult:
        initiator.require_person_or_delegate("graph.has_edges")
        if not isinstance(identity_filter, EdgeIdentityFilter):
            return MeshResult.failed(
                f"identity_filter is {type(identity_filter).__name__}, not EdgeIdentityFilter")
        if self._driver is None:
            return MeshResult.unreachable("has_edges: no Neo4j driver is configured")
        try:
            with self._driver.session() as session:
                rows = [dict(r) for r in session.run(
                    self._has_cypher, **self._filter_params(identity_filter))]
        except Exception as exc:  # noqa: BLE001 — classified, never swallowed
            detail = f"has_edges: {type(exc).__name__}: {exc}"
            if self._is_transport(exc):
                return MeshResult.unreachable(detail)
            return MeshResult.failed(detail)
        return MeshResult.answered(rows) if rows else MeshResult.empty()

    # ── helpers ─────────────────────────────────────────────────────────────────────────────

    def _type_for(self, verb: str) -> str:
        if isinstance(self._rel_type, str):
            return self._rel_type
        return self._rel_type(verb) or ""

    def _filter_params(self, f: EdgeIdentityFilter) -> dict:
        # A fixed type always narrows; a type derived from the verb narrows only when the verb is
        # bound — otherwise the family discriminator alone scopes the match.
        if isinstance(self._rel_type, str):
            rel_type: Optional[str] = self._rel_type
        else:
            rel_type = self._rel_type(f.verb) if f.verb is not None else None
        return dict(rel_type=rel_type, subject=f.subject, object=f.object, verb=f.verb,
                    edge_key=f.key)

    def _payload(self, payload: Any) -> tuple[dict, str]:
        if not isinstance(payload, Mapping):
            return {}, f"payload is {type(payload).__name__}, not a mapping"
        out: dict = {}
        for name, value in payload.items():
            if not isinstance(name, str) or not name:
                return {}, f"payload key {name!r} is not a non-empty string"
            if name in (self._verb_prop, self._key_prop):
                return {}, (f"payload key {name!r} is an identity property; identity comes from "
                            f"`identity` alone")
            if not self._storable(value):
                return {}, (f"payload[{name!r}] is {type(value).__name__}; Neo4j stores a "
                            f"primitive or a homogeneous list of one — refused, not stripped")
            out[name] = list(value) if isinstance(value, (list, tuple)) else value
        return out, ""

    @staticmethod
    def _storable(value: Any) -> bool:
        if isinstance(value, _PRIMITIVES):
            return True
        if isinstance(value, (list, tuple)):
            kinds = {type(v) for v in value}
            return len(kinds) <= 1 and all(k in _PRIMITIVES for k in kinds)
        return False

    def _run(self, cypher: str, **params: Any) -> tuple[Any, Optional[MeshWriteResult]]:
        """Execute once; every store outcome becomes a result, never a driver exception."""
        if self._driver is None:
            return None, MeshWriteResult.unreachable("no Neo4j driver is configured")
        try:
            with self._driver.session() as session:
                record = session.run(cypher, **params).single()
        except Exception as exc:  # noqa: BLE001 — classified immediately below, never swallowed
            detail = f"{type(exc).__name__}: {exc}"
            if self._is_transport(exc):
                return None, MeshWriteResult.unreachable(detail)
            return None, MeshWriteResult.failed(detail)
        return record, None

    @staticmethod
    def _is_transport(exc: BaseException) -> bool:
        return isinstance(exc, OSError) or type(exc).__name__ in _TRANSPORT
