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


def _deterministic_predicate_uuid(
    verb_iri: str,
    input_uri: str,
    frontend_id: str = "",
    archetype: str = "",
) -> UUID:
    """Same UUID5 derivation as ``aitool_linker.sync_predicate_to_weaviate``
    — keeps the deterministic key compatible across the gateway and the
    historic sensor path so re-syncs upsert the same row.

    TWO SPECIES, TWO KEY SHAPES, and the verb shape is FROZEN.

    A verb is uniquely identified by ``(verb_iri, input_uri)``: one provider
    answers one verb for one input type. Passing no frontend/archetype produces
    a byte-identical name string to the original derivation, so every existing
    verb row upserts to the SAME uuid it already has. Changing that would not
    "migrate" them — it would mint new uuids and leave the originals orphaned as
    duplicates, which is the failure a schema change is most likely to cause
    silently.

    A PRESENTATION is not: a menu entry is ``(subject, archetype)`` and it
    belongs to a specific frontend. Cortex rendering OwnershipFact as a
    KNOWLEDGE_DOCUMENT and OpenDDIL rendering the same subject as a CHART_WIDGET
    are two real, simultaneous menu entries — under the verb-shaped key they
    collide on ``(mesh:rendersAs, OwnershipFact)`` and the second silently
    overwrites the first. That collision was DEFERRED when the manifest learned
    the species, on the grounds that nothing yet read per-frontend menus. The
    read path is what makes it bite, so it is closed here rather than discovered
    as a mystery overwrite by the first two-frontend deployment.
    """
    import hashlib
    name = f"{verb_iri}|{input_uri}"
    if frontend_id or archetype:
        name = f"{name}|{frontend_id}|{archetype}"
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


def _ensure_predicate_collection(weaviate_client: Any) -> None:
    """Create the Weaviate ``Predicate`` collection WITH
    ``IndexPropertyLength=true`` if it does not already exist.

    The registrar is the FIRST writer to touch this collection after a
    substrate wipe — it runs on engine self-registration, BEFORE the
    doc-tools sensor's ``aitool_linker`` pass. A bare ``collections.get()``
    followed by ``data.insert()`` (below) lets Weaviate AUTO-SCHEMA create
    the collection with default config — i.e. WITHOUT the length index. Engine
    O's ``/classify_predicate`` ORs a ``domains length == 0`` clause into its
    domain-scope filter, and Weaviate rejects that clause unless property
    length is indexed:

        "Property length must be indexed to be filterable! add
         IndexPropertyLength: true to the invertedIndexConfig in Predicate."

    When it rejects, the predicate hybrid search returns empty and routing
    silently degrades to the generalist for every entitled-domain caller
    (work 2026-07-18: the doc-tools fold was in place but never fired because
    the registrar had already auto-created the indexless collection). This
    mirrors ``doc_tools/assets/aitool_linker._ensure_predicate_collection`` so
    that WHICHEVER writer creates the collection first sets the index. No-op
    when the collection already exists.
    """
    import weaviate.classes as wvc

    if weaviate_client.collections.exists(_PREDICATE_COLLECTION):
        return
    weaviate_client.collections.create(
        name=_PREDICATE_COLLECTION,
        inverted_index_config=wvc.config.Configure.inverted_index(
            index_property_length=True,
        ),
        properties=[
            wvc.config.Property(name="verb_iri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="verb_local", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="input_uri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="output_uri", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="endpoint_url", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="owner_persona", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="domains", data_type=wvc.config.DataType.TEXT_ARRAY),
            wvc.config.Property(name="cost_class", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="requires_human_approval", data_type=wvc.config.DataType.BOOL),
            wvc.config.Property(name="search_text", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="synonyms", data_type=wvc.config.DataType.TEXT_ARRAY),
            wvc.config.Property(name="anti_synonyms", data_type=wvc.config.DataType.TEXT_ARRAY),
            wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="tool_urn", data_type=wvc.config.DataType.TEXT),
            # ── SECOND SPECIES PAYLOAD (presentations) ────────────────────────
            # A verb row is fully described by (input)-[verb]->(output). A
            # PRESENTATION row is not: the selector also needs to know WHOSE menu
            # it is on, what archetype to name, which fields the archetype needs,
            # and whether it recomputes. Without these the row carries the triple
            # and not the MENU -- `menu_for()` cannot scope, `_satisfies()` cannot
            # evaluate fit, and `_is_live_view()` is always False, which would
            # make ADR-0042 Ruling 9 silently vacuous while reading as enforced.
            wvc.config.Property(name="tool_kind", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="frontend_id", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="archetype", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="expected_fields", data_type=wvc.config.DataType.TEXT_ARRAY),
            # BOOL, and ABSENT MEANS NOTHING -- not False-meaning-live and not
            # True-meaning-live by accident. This mirrors `_is_live_view()` in
            # agent_fleet/presentation_agent/capability_registry.py (ab0bcfd),
            # where a contract that never declared `recomputes` says NOTHING. The
            # two ends of that contract must keep the same honest default, so this
            # cites that author rather than re-deciding it here.
            wvc.config.Property(name="recomputes", data_type=wvc.config.DataType.BOOL),
        ],
    )
    logger.info(
        "Created Weaviate %s collection with IndexPropertyLength=true "
        "(registrar first-writer path).",
        _PREDICATE_COLLECTION,
    )


def upsert_weaviate_predicate_row(
    *,
    weaviate_client: Any,
    tool_kind: str = "Engine",
    frontend_id: str = "",
    archetype: str = "",
    expected_fields: "list[str] | None" = None,
    recomputes: "bool | None" = None,
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
        # SECOND SPECIES PAYLOAD. Written for BOTH kinds so a reader never has to
        # infer the species from which fields happen to be present -- the same
        # discriminator-rides-in-the-data rule the manifest follows.
        "tool_kind": tool_kind or "Engine",
        "frontend_id": frontend_id or "",
        "archetype": archetype or "",
        "expected_fields": list(expected_fields or []),
    }
    # ABSENT MEANS NOTHING. `recomputes` is OMITTED rather than written False
    # when the caller did not declare it, because False-by-default and
    # live-by-accident are both lies about a component nobody asked. This
    # mirrors `_is_live_view()` in capability_registry.py (ab0bcfd): "a contract
    # that never declared the flag says NOTHING, and is not read as live." The
    # two ends of ADR-0042 Ruling 9 must keep the same default or the ruling
    # means different things at the writer and the reader.
    if recomputes is not None:
        properties["recomputes"] = bool(recomputes)

    # Presentations key per FRONTEND and per ARCHETYPE; verbs keep the frozen
    # two-part key (empty extras reproduce the original name string byte for
    # byte, so all existing verb rows upsert in place rather than duplicating).
    deterministic_uuid = _deterministic_predicate_uuid(
        verb_iri, input_uri, frontend_id or "", archetype or ""
    )
    # Create the collection WITH the length index if absent, BEFORE the
    # get()+insert below — otherwise Weaviate auto-schema creates it indexless
    # and Engine O's domain-scope filter can never run (see helper docstring).
    _ensure_predicate_collection(weaviate_client)
    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)

    # Compute the vector explicitly via embed_document(). Weaviate is dumb
    # storage of the vector — NO server-side text2vec module is used.
    # Predicate rows are CORPUS (the read-side hybrid query uses embed_query
    # for the QUERY-prefixed vector). Asymmetric prefixes are the contract;
    # using the wrong helper silently splits the embedding space. See
    # utils/embed.py for the rationale.
    #
    # On embed gateway failure we still write the row WITHOUT a vector
    # so the registration saga isn't blocked on the LLM stack being
    # healthy. BM25 queries still work; a backfill can populate vectors
    # once the gateway is restored.
    try:
        from utils.embed import embed_document
    except ImportError:
        from agent_fleet.utils.embed import embed_document

    try:
        predicate_vector = embed_document(search_text)
    except Exception as e:
        print(f"[mesh_registrar v2] embed_document failed for Predicate row "
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
    *, weaviate_client: Any, verb_iri: str, input_uri: str,
    frontend_id: str = "", archetype: str = "",
) -> bool:
    """DELETE the Predicate row for this identity.

    Returns True if the row was deleted, False if it didn't exist (the
    saga is replaying a compensation that already ran). Idempotent.

    THE IDENTITY MUST MATCH THE WRITE'S. When the key gained its
    frontend/archetype parts for presentations, this call site kept the
    two-part form and silently addressed a DIFFERENT row — so a
    compensation would delete nothing while reporting success, leaving the
    half-written row it was supposed to remove.
    """
    deterministic_uuid = _deterministic_predicate_uuid(
        verb_iri, input_uri, frontend_id or "", archetype or ""
    )
    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)
    if not collection.data.exists(uuid=deterministic_uuid):
        return False
    collection.data.delete_by_id(uuid=deterministic_uuid)
    return True


# ---------------------------------------------------------------------------
# Compensate-on-rescope sweep (Step 1 of the contamination-fix sequence)
# ---------------------------------------------------------------------------
#
# Background. The Weaviate Predicate collection's row UUID is
# ``uuid5(verb_iri, input_uri)``. When an engine *migrates* the
# ``input_uri`` it registers a verb against (e.g. the catalog-verb
# migration that moved ``analyzeDataset`` from
# ``mesh:DatasetAnalysisRequest`` to ``idp#Dataset``), the new
# registration mints a *new* UUID. The OLD row — same engine, same
# verb, prior input_uri — is left orphaned, because nothing in the
# registration path knew to delete it. After enough migrations the
# collection accretes rename-stale duplicates, and Weaviate's
# vector-similarity search can return the wrong one — which is how a
# verb resolved correctly but dispatched to the wrong endpoint.
#
# This sweep is the per-call compensate-on-rescope. Each registration
# now sweeps rows where:
#
#   * ``tool_urn`` equals the engine's CURRENT tool_urn (the
#     cross-engine isolation guarantee — the sweep cannot touch
#     another engine's records because the tool_urn would differ).
#   * ``verb_iri`` equals the verb being registered (so the sweep
#     touches only the verb under registration; an engine registering
#     N verbs runs N independent narrow sweeps).
#   * Canonicalized ``input_uri`` does NOT match the canonicalized
#     current input_uri (so the row being upserted survives the sweep).
#
# The compact-form vs full-IRI hazard is handled by canonicalizing
# both sides through ``_canonical_iri`` before comparison. A row
# stored as ``mesh:AgentTask`` is canonicalized to
# ``http://invincible-agent/mesh#AgentTask`` for the comparison, so a
# row in compact form still gets deleted when the current registration
# is in full form (and vice versa). Without canonicalization, the
# sweep would either fail to delete (under-delete) or delete its own
# current registration (over-delete — catastrophic).
#
# What the sweep deliberately does NOT catch:
#
#   * Rename-orphans where the tool_urn itself changed
#     (e.g. ``engine_a_analyze_dataset`` → ``engine_a_restate_analyst``).
#     A sweep keyed on the engine's CURRENT tool_urn can't see records
#     under the OLD tool_urn. That's the correct safety boundary — a
#     fuzzy "looks like one of my old names" match would risk deleting
#     records that aren't actually yours. Rename-orphans are caught
#     downstream by the substrate dedup guard (catches
#     ``(verb_iri, input_uri)`` collisions on the SAME canonical pair)
#     and the seed-collection drop+recreate (kills the historical
#     artifact permanently, since the writer that created it is
#     retired and the orphan never recurs).
#
# Failure shape:
#
#   * Sweep failure must NOT block the registration itself. The new
#     row was already upserted; failing the sweep would leave the
#     substrate in a coherent (though duplicated) state. Logged at
#     WARNING, the dedup guard catches the residual.

# Compact-prefix → full-IRI base. Mirrors the seed script's _MESH /
# _IDP discipline (canonical full-IRI for subject/object URIs,
# compact-form for verbs). Adding a new namespace prefix: add an
# entry here and the sweep handles compact-vs-full equivalence.
_IRI_PREFIXES: dict[str, str] = {
    "mesh:": "http://invincible-agent/mesh#",
    "idp:": "http://invincible-agent/idp#",
}


def _canonical_iri(iri: str) -> str:
    """Expand a compact-form CURIE to its full IRI.

    Idempotent on full IRIs — anything that doesn't start with a known
    compact prefix is returned unchanged, so this can be applied to
    both sides of a comparison without surprises. Falsy input maps to
    empty string so set-membership comparisons stay stable.
    """
    if not iri:
        return ""
    for prefix, expansion in _IRI_PREFIXES.items():
        if iri.startswith(prefix):
            return expansion + iri[len(prefix):]
    return iri


def sweep_stale_weaviate_predicate_rows(
    *,
    weaviate_client: Any,
    verb_iri: str,
    current_input_uri: str,
    tool_urn: str,
) -> list[dict]:
    """Compensate-on-rescope sweep for the engine's prior registrations of this verb.

    Deletes rows in the Predicate collection where:

      * ``tool_urn`` equals the engine's current ``tool_urn``, AND
      * ``verb_iri`` equals the verb being registered, AND
      * canonical(``input_uri``) does NOT equal canonical(``current_input_uri``).

    The first two clauses keep the sweep cross-engine-isolated and
    cross-verb-isolated; the third clause is what makes the sweep an
    *upsert* in effect — the row being upserted is preserved by
    matching the canonical input_uri, every other input_uri for this
    (engine, verb) pair is treated as a rename-stale orphan.

    Returns a list of ``{uuid, input_uri}`` dicts for the rows
    deleted, so the saga and tests can assert the surgical scope.
    Empty list = nothing to sweep, the steady-state condition after
    the first post-deploy boot.

    Raises only on Weaviate transport errors; the caller should log
    and continue rather than failing the registration. The new row
    was already upserted; the sweep is best-effort hygiene.
    """
    from weaviate.classes.query import Filter

    collection = weaviate_client.collections.get(_PREDICATE_COLLECTION)
    canonical_current = _canonical_iri(current_input_uri)

    candidates = collection.query.fetch_objects(
        filters=(
            Filter.by_property("tool_urn").equal(tool_urn)
            & Filter.by_property("verb_iri").equal(verb_iri)
        ),
        limit=100,
    )

    deleted: list[dict] = []
    for obj in candidates.objects:
        row_input_uri = (obj.properties or {}).get("input_uri") or ""
        if _canonical_iri(row_input_uri) == canonical_current:
            # Row matches the registration we just upserted — keep it.
            continue
        collection.data.delete_by_id(uuid=obj.uuid)
        deleted.append({"uuid": str(obj.uuid), "input_uri": row_input_uri})

    return deleted


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
    frontend_id: str = "",
    archetype: str = "",
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

    # Weaviate side.
    # SAME IDENTITY AS THE WRITE. This read-back is the saga's proof that the
    # upsert landed; addressing a different uuid than the writer used makes it
    # report "the upsert claimed success but the read-back disagrees" for a row
    # that is sitting there perfectly — and the saga then COMPENSATES a good
    # write and returns 503. Observed 2026-08-21 the moment presentation rows
    # gained a per-frontend key and this call site did not.
    deterministic_uuid = _deterministic_predicate_uuid(
        verb_iri, input_uri, frontend_id or "", archetype or ""
    )
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
