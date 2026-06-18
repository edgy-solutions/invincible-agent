"""Gateway v0.2 substrate writers.

Direct Neo4j + Weaviate writers for the v0.2 atomic-registration saga.
Lifted from ``doc_tools/assets/aitool_linker.py`` per ADR-0006 §Addendum
(2026-06-13). Behavioral difference from the lifted versions:
**exceptions PROPAGATE here.** The sensor's path could swallow Weaviate
failures because Cypher exact-match was the routing fallback. The
saga can't swallow them — it has to know the substrate truth in order
to compensate. The conjunctive-read invariant the rollback decision
rests on is broken the moment a substrate write fails silently.

Each function returns ``None`` on success and raises on failure.
``compensate_*`` mirrors handle "the write succeeded but we now need
to undo it" — they MUST be idempotent so the Restate saga can replay
a compensation step that already partially ran.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers shared with the lifted code
# ---------------------------------------------------------------------------

def _get_verb_local_name(verb_iri: str) -> str:
    """`mesh:lookupOwnership` → `lookupOwnership`. Pure string op."""
    if ":" in verb_iri:
        return verb_iri.split(":", 1)[1]
    if "#" in verb_iri:
        return verb_iri.rsplit("#", 1)[1]
    return verb_iri.rsplit("/", 1)[-1]


def _build_search_text(
    *, verb_iri: str, verb_local: str, synonyms: list[str], description: str
) -> str:
    """The BM25-indexed blob Engine O's hybrid search runs against.

    Anti-synonyms are intentionally NOT folded in — Engine O reads them
    separately and applies a lexical-overlap penalty after Weaviate
    returns candidates.
    """
    parts = [verb_iri, verb_local]
    parts.extend(synonyms)
    if description:
        parts.append(description)
    return " ".join(filter(None, parts))


def _deterministic_predicate_uuid(verb_iri: str, input_uri: str) -> UUID:
    """Same UUID5 derivation as ``aitool_linker.sync_predicate_to_weaviate``
    — keeps the deterministic key compatible across the gateway and the
    historic sensor path so re-syncs upsert the same row."""
    import hashlib
    name = f"{verb_iri}|{input_uri}"
    # uuid5 over NAMESPACE_DNS with a known name string. We compute it
    # without importing weaviate's helper to keep this module
    # dependency-light at import time.
    namespace = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_DNS
    h = hashlib.sha1(namespace.bytes + name.encode("utf-8")).digest()
    return UUID(bytes=h[:16], version=5)


# ---------------------------------------------------------------------------
# Neo4j writer — MERGE the predicate edge
# ---------------------------------------------------------------------------

# Identity for the relationship is `(verb_iri, _tool_urn)` per doc-tools
# a44b9fb. Without _tool_urn in the match-key, N providers offering the
# same predicate collapse into one edge with last-write-wins. The
# substrate-invariant test
# `tests/routing/test_substrate_invariants.py::test_mesh_resolve_instance_has_one_edge_per_provider`
# pins this property; the saga MUST preserve it.
_MERGE_CYPHER = """
MATCH (s:OntologyClass {uri: $input_uri})
MATCH (o:OntologyClass {uri: $output_uri})
WITH s, o
CALL apoc.merge.relationship(
    s,
    $verb_local,
    $match_key,
    $props,
    o,
    $props
) YIELD rel
RETURN type(rel) AS rel_type, rel.iri AS iri
"""


# Compensation: DELETE the predicate edge for this exact identity.
# Critically: filters on BOTH the verb_iri AND the _tool_urn so a
# concurrent registration that already committed for a different
# provider is NOT collaterally deleted.
_COMPENSATE_CYPHER = """
MATCH (s:OntologyClass {uri: $input_uri})-[r]->(o:OntologyClass {uri: $output_uri})
WHERE r.iri = $verb_iri AND r._tool_urn = $tool_urn
DELETE r
RETURN count(r) AS deleted
"""


def merge_neo4j_predicate_edge(
    *,
    driver: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    tool_urn: str,
    rel_props: dict,
) -> None:
    """MERGE the predicate edge from input to output. Raises on failure.

    ``rel_props`` is the full property bag the relationship should carry
    — everything the discovery Cypher reads (provider, timeout_s,
    endpoint_url, owner_persona, ...) plus the `_tool_urn` and `iri`
    that form the identity. Caller is responsible for assembling the
    bag; this function only writes it.

    Idempotency: apoc.merge.relationship UPDATES the relationship with
    the new $props if the match-key already matched. So re-running this
    after the saga replayed past it is safe — the same write happens.
    """
    verb_local = _get_verb_local_name(verb_iri)
    # The match-key is the identity that distinguishes registrations.
    # Anything not in the match-key is part of $props (set on every
    # merge).
    match_key = {"iri": verb_iri, "_tool_urn": tool_urn}
    # Ensure the identity fields are also in $props so a CREATE has them.
    full_props = dict(rel_props)
    full_props["iri"] = verb_iri
    full_props["_tool_urn"] = tool_urn
    full_props["_input_uri"] = input_uri
    full_props["_output_uri"] = output_uri

    with driver.session() as session:
        rec = session.run(
            _MERGE_CYPHER,
            input_uri=input_uri,
            output_uri=output_uri,
            verb_local=verb_local,
            match_key=match_key,
            props=full_props,
        ).single()
    if rec is None:
        raise RuntimeError(
            f"merge_neo4j_predicate_edge: MATCH returned no record. "
            f"Input or output OntologyClass missing? "
            f"input_uri={input_uri!r}, output_uri={output_uri!r}. "
            f"This is a Contract D violation that should have been "
            f"caught upstream of the saga."
        )


def compensate_neo4j_predicate_edge(
    *,
    driver: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    tool_urn: str,
) -> int:
    """DELETE the predicate edge for this registration's identity.

    Returns the count of edges deleted (0 if no edge matched — the saga
    is replaying a compensation step that already ran, which is fine).
    Idempotent by construction: the WHERE clause filters on the exact
    identity; concurrent registrations for other providers survive.
    """
    with driver.session() as session:
        rec = session.run(
            _COMPENSATE_CYPHER,
            input_uri=input_uri,
            output_uri=output_uri,
            verb_iri=verb_iri,
            tool_urn=tool_urn,
        ).single()
    return int(rec["deleted"]) if rec else 0


# ---------------------------------------------------------------------------
# Weaviate writer — Predicate collection upsert
# ---------------------------------------------------------------------------

_PREDICATE_COLLECTION = "Predicate"


def upsert_weaviate_predicate_row(
    *,
    weaviate_client: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    description: str,
    endpoint_url: str,
    owner_persona: str,
    domains: list[str],
    cost_class: str,
    requires_human_approval: bool,
    synonyms: list[str],
    anti_synonyms: list[str],
    tool_urn: str,
) -> None:
    """Upsert the Predicate row Engine O's hybrid search reads against.

    Deterministic UUID over `(verb_iri, input_uri)` keeps re-syncs
    idempotent. Raises on any Weaviate exception — the saga MUST know
    if Weaviate didn't accept the write, because the conjunctive-read
    invariant is only safe if both stores agree.
    """
    verb_local = _get_verb_local_name(verb_iri)
    search_text = _build_search_text(
        verb_iri=verb_iri,
        verb_local=verb_local,
        synonyms=synonyms,
        description=description,
    )

    properties = {
        "verb_iri": verb_iri,
        "verb_local": verb_local,
        "input_uri": input_uri,
        "output_uri": output_uri,
        "endpoint_url": endpoint_url,
        "owner_persona": owner_persona,
        "domains": list(domains),
        "cost_class": cost_class,
        "requires_human_approval": bool(requires_human_approval),
        "search_text": search_text,
        "synonyms": list(synonyms),
        "anti_synonyms": list(anti_synonyms),
        "description": description,
        "tool_urn": tool_urn,
    }

    deterministic_uuid = _deterministic_predicate_uuid(verb_iri, input_uri)
    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)

    # Compute the vector explicitly via embed_text(). Weaviate is dumb
    # storage of the vector — NO server-side text2vec module is used.
    # Both writer (here) and reader (Engine O hybrid) call embed_text(),
    # so the embedding-model contract lives in code (utils/embed.py) and
    # is grep-able. See utils/embed.py for the full rationale.
    #
    # On embed gateway failure we still write the row WITHOUT a vector
    # so the registration saga isn't blocked on the LLM stack being
    # healthy. BM25 queries still work; a backfill can populate vectors
    # once the gateway is restored.
    try:
        from utils.embed import embed_text
    except ImportError:
        from agent_fleet.utils.embed import embed_text

    try:
        predicate_vector = embed_text(search_text)
    except Exception as e:
        print(f"[mesh_registrar v2] embed_text failed for Predicate row "
              f"{verb_iri}|{input_uri}; writing without vector "
              f"(BM25-only until backfill): {e}")
        predicate_vector = None

    write_kwargs: dict = {
        "uuid": deterministic_uuid,
        "properties": properties,
    }
    if predicate_vector is not None:
        write_kwargs["vector"] = predicate_vector

    if collection.data.exists(uuid=deterministic_uuid):
        collection.data.replace(**write_kwargs)
    else:
        collection.data.insert(**write_kwargs)


def compensate_weaviate_predicate_row(
    *, weaviate_client: Any, verb_iri: str, input_uri: str
) -> bool:
    """DELETE the Predicate row for this (verb_iri, input_uri) identity.

    Returns True if the row was deleted, False if it didn't exist (the
    saga is replaying a compensation that already ran). Idempotent.
    """
    deterministic_uuid = _deterministic_predicate_uuid(verb_iri, input_uri)
    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)
    if not collection.data.exists(uuid=deterministic_uuid):
        return False
    collection.data.delete_by_id(uuid=deterministic_uuid)
    return True


# ---------------------------------------------------------------------------
# Read-back probe — the gateway's own postcondition test
# ---------------------------------------------------------------------------

_PROBE_NEO4J_CYPHER = """
MATCH (s:OntologyClass {uri: $input_uri})-[r]->(o:OntologyClass {uri: $output_uri})
WHERE r.iri = $verb_iri AND r._tool_urn = $tool_urn
RETURN r.endpoint_url AS endpoint_url, r.provider AS provider,
       r.timeout_s AS timeout_s
LIMIT 1
"""


def probe_both_stores(
    *,
    driver: Any,
    weaviate_client: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    tool_urn: str,
) -> dict:
    """Read both stores back and assert the registration is observable.

    Returns a small dict with what each store reported. Raises if either
    store is missing the row — that's the "saga claims success but the
    substrate disagrees" failure mode the read-back probe exists to
    catch BEFORE returning 200 to the caller.
    """
    # Neo4j side
    with driver.session() as session:
        n_rec = session.run(
            _PROBE_NEO4J_CYPHER,
            input_uri=input_uri,
            output_uri=output_uri,
            verb_iri=verb_iri,
            tool_urn=tool_urn,
        ).single()
    if n_rec is None:
        raise RuntimeError(
            f"probe_both_stores: Neo4j has no edge for "
            f"({input_uri})-[{verb_iri} tool_urn={tool_urn}]->({output_uri}). "
            f"The merge claimed success but the read-back disagrees — saga "
            f"will compensate."
        )

    # Weaviate side
    deterministic_uuid = _deterministic_predicate_uuid(verb_iri, input_uri)
    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)
    if not collection.data.exists(uuid=deterministic_uuid):
        raise RuntimeError(
            f"probe_both_stores: Weaviate has no Predicate row for "
            f"verb_iri={verb_iri!r} input_uri={input_uri!r} "
            f"(uuid={deterministic_uuid}). The upsert claimed success "
            f"but the read-back disagrees — saga will compensate."
        )

    return {
        "neo4j": dict(n_rec),
        "weaviate_uuid": str(deterministic_uuid),
    }
