import os
import asyncio
import httpx
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Tuple

from restate import Context, Service
from smolagents import CodeAgent, ToolCallingAgent, tool
import weaviate
from weaviate.connect import ConnectionParams
import weaviate.classes as wvc

try:
    from llm_utils import get_smolagent_model, init_baml_client
except ImportError:
    try:
        from agent_fleet.llm_utils import get_smolagent_model, init_baml_client
    except ImportError:
        pass

try:
    from utils.weaviate_utils import create_weaviate_client
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import create_weaviate_client
    except ImportError:
        from weaviate_utils import create_weaviate_client

# Shared embedding helper — code owns the contract for "what model" and
# "what task prefix." Engine W is a READ path, so embed_query is the right
# helper (it adds the nomic search_query: prefix).
try:
    from utils.embed import embed_query, observe_query_embedding
except ImportError:
    try:
        from agent_fleet.utils.embed import embed_query, observe_query_embedding
    except ImportError:
        from embed import embed_query, observe_query_embedding

# The fleet's MeshVectors reader. It lives in `utils` so this image has it: engine images copy
# `agent_fleet/utils` -> `/app/utils` and only their OWN engine directory besides.
try:
    from utils.mesh_vectors import WeaviateVectors
except ImportError:
    from agent_fleet.utils.mesh_vectors import WeaviateVectors

from iagent_mesh.interfaces import Initiator

# The SAME canonicalizer doc-tools' S1000D parser mints its root URI with
# (`mil#dmc-<canonical>`, s1000d_rdf.parse_data_module), so the label below is
# read back through the function that wrote it, never re-parsed by hand.
try:
    from utils.dmc_canonicalizer import canonicalize_dmc
except ImportError:
    from agent_fleet.utils.dmc_canonicalizer import canonicalize_dmc


def source_label(doc_id: str, page_number=None) -> str:
    """A retrieved chunk's citation label: the DMC for an S1000D data module.

    An S1000D chunk's ``doc_id`` is its data module's root URI, whose fragment is
    ``dmc-`` + the canonical DMC. Cortex draws ``label`` verbatim and will not
    parse a DMC out of a uri, so the fleet names it: ``DMC-<canonical>``. Any
    other doc_id (DITA, IADS, 40051, a PDF name, "Unknown Document") and any
    fragment the canonicalizer refuses keeps the doc_id unchanged -- an honest
    miss, never a guessed DMC.
    """
    label = f"{doc_id}"
    frag = label.rsplit("#", 1)[-1] if "#" in label else ""
    if frag[:4].lower() == "dmc-":
        dmc = canonicalize_dmc(frag[4:])
        if dmc:
            label = f"DMC-{dmc}"
    return label + (f" · p.{page_number}" if page_number else "")


from baml_client import b


# ADR-0025 engines arc — Engine W's per-document READ gate (single decider).
# ENABLE_AGENTIC_AUTH dark-launches the result-filter: OFF → no filtering (all
# retrieved chunks flow to synthesis, current behavior); ON → each chunk is
# gated on its source document's can_read. Flips LAST (after all enforcement
# points migrate), exactly like the DA-read / query_metadata gates. Deploying
# the filter code with the flag OFF is therefore a no-op (safe) — it does NOT
# deny-all an un-seeded document directory until the flag is turned on.
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")
# Posture ANNOUNCED at import, naming its SOURCE (2026-08-07) — see core/authz.py. A filter
# that is OFF is a no-op by design here, which is exactly why its state must be legible: an
# un-announced no-op filter and a missing filter look identical in a running system.
_AGENTIC_AUTH_RAW = os.getenv("ENABLE_AGENTIC_AUTH")
ENABLE_AGENTIC_AUTH = (_AGENTIC_AUTH_RAW or "false").lower() in ("true", "1", "yes")
print(
    f"agentic auth: {'ENFORCING' if ENABLE_AGENTIC_AUTH else 'DISABLED'} "
    f"({'explicit config' if _AGENTIC_AUTH_RAW is not None else 'DEFAULT'}, "
    f"dark-launch ADR-0025) [weaviate_expert: per-chunk can_read filter]",
    flush=True,
)


def _can_read_document(caller_email: str, source_id: str) -> bool:
    """Ask Topaz whether ``caller_email`` may READ the source ``document``.

    The single-decider ASK for Engine W's result-filter: DENY-BY-DEFAULT,
    explicit owner/reader grant only (the same `can_read = reader | owner`
    shape the sealed DA-read gate proved, on the `document` namespace).
    Entitlement / persona / domain are NEVER sufficient — a chunk's source
    document requires an explicit grant (asset_grants.yaml → grant_sync).

    FAIL-CLOSED on empty caller/source, an UNRESOLVABLE source, or ANY error
    → the chunk is DROPPED, never synthesized. An ungated-because-
    unidentifiable chunk is exactly the leak this gate exists to prevent, so
    "can't identify the source" resolves to deny, not allow.
    """
    if not caller_email or not source_id:
        return False
    try:
        r = httpx.post(
            f"{TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
            json={
                "object_type": "document",
                "object_id": source_id,
                "relation": "can_read",
                "subject_type": "user",
                "subject_id": caller_email,
            },
            timeout=5.0,
        )
        r.raise_for_status()
        return bool(r.json().get("check", False))
    except Exception as e:  # noqa: BLE001 — fail-closed on ANY failure
        print(f"[Engine W] can_read check FAILED (fail-closed deny) src={source_id!r}: {e}")
        return False


# ── the knowledge search, behind KNOWLEDGE_SEARCH_VIA_MESH ──────────────────────────────────
#
# OFF: the incumbent query, unchanged — near_vector on an `embed_query` vector,
# bm25 when the embed fails, the domain filter AND-ed with exact-match metadata filters.
# ON (the default since 2026-10-09; live retrieval parity measured 2026-10-08 by
# scripts/probes/engine_w_identity_census.py: 60 shared source decisions identical on both
# paths, 3 runs): the same search through the fleet's `MeshVectors` reader, `mode="vector_only"` (what the
# incumbent already ran), metadata filters passed through. What the reader adds: the collection
# marker checked at open, a degradation that is MARKED in the result (`mode == "bm25"`), and a
# failure that is a refusal rather than an exception's text.
#
# THE IDENTITY GATE IS THE SAME ON BOTH PATHS, BY CONSTRUCTION: both produce hits, and one
# function (`_gate_hits`) decides which reach synthesis. The flag chooses the RETRIEVAL, never the
# ENFORCEMENT. The reader's person guard is an additional refusal on the ON path, not a substitute.
#
# THE DIFFERENCES THE FLAG MAKES, each deliberate and sealed in
# tests/test_engine_w_knowledge_search_via_mesh.py:
#   1. An EMPTY caller is refused before any search on the ON path: the read is attributed to a
#      person, and the SDK's `Initiator` refuses a blank subject. `retrieve_gated_chunks` raises
#      the NAMED `CallerRequired` first, and the tool answers KNOWLEDGE_CALLER_REQUIRED_REFUSAL
#      (not the generic error string). OFF, an empty caller still searches, and the gate denies
#      every chunk only when ENABLE_AGENTIC_AUTH is on.
#   2. A list/set filter value is MEMBERSHIP on the ON path (SDK 0.9.8). OFF, every value is
#      `equal`.
#   3. A chunk with neither `source_url` nor `uri` gets a source URI from doc and page on the ON
#      path, because a reader row carries no Weaviate uuid. Two such chunks of one page then share
#      one Sources card. The GATE is unaffected: it keys on source_url/uri/doc_id, never the uuid.
#   4. An ABSENT collection is "No relevant information" on the ON path (the reader answers
#      `empty`). OFF, the driver raises and the tool returns its error string.
_KNOWLEDGE_VIA_MESH_RAW = os.getenv("KNOWLEDGE_SEARCH_VIA_MESH")
# Unset -> ON. A SET value (even empty) is parsed as written, so "" and "false" turn it off.
KNOWLEDGE_SEARCH_VIA_MESH = (
    True if _KNOWLEDGE_VIA_MESH_RAW is None
    else _KNOWLEDGE_VIA_MESH_RAW.lower() in ("true", "1", "yes")
)
print(
    f"knowledge search: {'MESH (MeshVectors.nominate)' if KNOWLEDGE_SEARCH_VIA_MESH else 'DIRECT'} "
    f"({'explicit config' if _KNOWLEDGE_VIA_MESH_RAW is not None else 'DEFAULT (on)'}) "
    f"[weaviate_expert: KNOWLEDGE_SEARCH_VIA_MESH]",
    flush=True,
)

KNOWLEDGE_SEARCH_LIMIT = 5

KNOWLEDGE_CALLER_REQUIRED_REFUSAL = (
    "Knowledge search refused: it reads on a person's behalf, and this request names no caller "
    "(user_email is missing or blank). No search was run."
)


class CallerRequired(ValueError):
    """The mesh path was asked to search with no caller. Raised BEFORE any search."""


class _MeshHit:
    """A reader row in the shape the gate and the source projection read off a driver object.

    `score` moves from the row to `metadata.score`; the projection reads a positive score first,
    and the reader puts a near_vector hit's similarity there (never the driver's 0.0). `uuid` is
    NOT the object's: a reader row carries none, so it is derived from doc and page, which is the
    difference numbered 3 above.
    """

    def __init__(self, row: Dict[str, Any]):
        props = dict(row)
        score = props.pop("score", None)
        self.properties = props
        self.metadata = SimpleNamespace(score=score, certainty=None, distance=None)
        page = props.get("page_number")
        self.uuid = f"{props.get('doc_id') or 'unknown'}" + (f"/p{page}" if page is not None else "")


def _hit_relevance(obj) -> Optional[float]:
    """The Sources card's relevance for one hit: a POSITIVE score, else certainty, else
    1 - distance. A near_vector hit's `score` is 0.0, not None (banked 2026-06-28), hence > 0."""
    md = getattr(obj, "metadata", None)
    if md is None:
        return None
    score = getattr(md, "score", None)
    certainty = getattr(md, "certainty", None)
    distance = getattr(md, "distance", None)
    if score is not None and float(score) > 0:
        return float(score)
    if certainty is not None:
        return float(certainty)
    if distance is not None:
        return max(0.0, 1.0 - float(distance))
    return None


def _search_direct(weaviate_client, collection_name: str, domain_label: str,
                   semantic_query: str, metadata_filters) -> list:
    """The incumbent query, moved here verbatim from the tool body."""
    collection = weaviate_client.collections.get(collection_name)
    base_filter = wvc.query.Filter.by_property("domain").equal(domain_label)
    if metadata_filters and isinstance(metadata_filters, dict):
        filter_list = [base_filter]
        for key, value in metadata_filters.items():
            filter_list.append(wvc.query.Filter.by_property(key).equal(value))
        final_filter = wvc.query.Filter.all_of(filter_list)
    else:
        final_filter = base_filter

    metadata_query = wvc.query.MetadataQuery(score=True, certainty=True, distance=True)
    try:
        query_vector = embed_query(semantic_query)
        response = collection.query.near_vector(
            near_vector=query_vector,
            limit=KNOWLEDGE_SEARCH_LIMIT,
            filters=final_filter,
            return_metadata=metadata_query,
        )
    except Exception as embed_err:
        print(f"embed_query failed in Engine W; BM25 fallback: {embed_err}")
        response = collection.query.bm25(
            query=semantic_query,
            limit=KNOWLEDGE_SEARCH_LIMIT,
            filters=final_filter,
            return_metadata=metadata_query,
        )
    return list(response.objects)


def _search_via_mesh(weaviate_client, collection_name: str, domain_label: str,
                     semantic_query: str, metadata_filters, caller_email: str) -> list:
    """The same search through `MeshVectors.nominate`. Raises on a refusal or a failure; the tool
    turns that into its error string, as it does for the incumbent's exceptions.

    NO BLANK-CALLER CHECK HERE, deliberately: the SDK's `Initiator` refuses a blank subject (a
    ValueError, raised while the arguments are built, so before any search). That guard is the
    one any DIRECT caller of this function meets (scripts/probes/engine_w_identity_census.py's
    empty-caller control calls it directly). The shipping path never reaches it with a blank
    caller: `retrieve_gated_chunks` raises the named `CallerRequired` first, so the live tool can
    answer a refusal that says what is missing instead of the generic error string.
    """
    impl = WeaviateVectors(
        client=weaviate_client,
        embed=observe_query_embedding,
        filters=wvc.query.Filter,
        metadata=wvc.query.MetadataQuery,
        report=lambda m: print(f"[Engine W] mesh knowledge search: {m}", flush=True),
    )
    result = impl.nominate(
        # Declared a person, as engine-o's class pool does: `user_email` is the end user's
        # entitlement key, threaded from the supervisor's specialist dispatch.
        Initiator(subject=caller_email, kind="person"),
        collection=collection_name,
        text=semantic_query,
        domains=[domain_label],
        limit=KNOWLEDGE_SEARCH_LIMIT,
        mode="vector_only",
        metadata_filters=dict(metadata_filters) if isinstance(metadata_filters, dict) else {},
    )
    if result.outcome in ("failed", "unreachable"):
        raise RuntimeError(f"knowledge search {result.outcome}: {result.detail}")
    if result.mode == "bm25":
        print("[Engine W] knowledge search DEGRADED to bm25 (embed failed; marked by the reader)",
              flush=True)
    return [_MeshHit(row) for row in (result.rows or ())]


def _gate_hits(hits: list, caller_email: str) -> Tuple[List[Tuple[int, Any]], int]:
    """THE RESULT-FILTER, one function for both retrieval paths. Returns the kept hits with
    their retrieval positions, and how many were dropped.

    Each chunk is gated on can_read of its SOURCE DOCUMENT before synthesis: a chunk this lets
    through is one the LLM can synthesize into the answer. The source identity is stamped at
    ingest (source_url/uri/doc_id); an UNRESOLVABLE source fails CLOSED, because an unidentifiable
    chunk cannot be gated and letting it through is the leak. The domain filter is RELEVANCE
    scope, not enforcement — this gate is the enforcement, whatever the search already did.
    """
    kept: List[Tuple[int, Any]] = []
    dropped = 0
    for idx, obj in enumerate(hits):
        source_id = (
            obj.properties.get("source_url")
            or obj.properties.get("uri")
            or obj.properties.get("doc_id")
        )
        if source_id == "Unknown Document":
            source_id = None
        if ENABLE_AGENTIC_AUTH and not _can_read_document(caller_email, source_id):
            dropped += 1
            continue
        kept.append((idx, obj))
    return kept, dropped


def retrieve_gated_chunks(weaviate_client, *, collection_name: str, domain_label: str,
                          semantic_query: str, metadata_filters, caller_email: str
                          ) -> Tuple[List[Tuple[int, Any]], int, int]:
    """Search (by the flag's path), then gate. Returns (kept, dropped, retrieved)."""
    if KNOWLEDGE_SEARCH_VIA_MESH:
        if not (caller_email or "").strip():
            raise CallerRequired(KNOWLEDGE_CALLER_REQUIRED_REFUSAL)
        hits = _search_via_mesh(weaviate_client, collection_name, domain_label,
                                semantic_query, metadata_filters, caller_email)
    else:
        hits = _search_direct(weaviate_client, collection_name, domain_label,
                              semantic_query, metadata_filters)
    kept, dropped = _gate_hits(hits, caller_email)
    return kept, dropped, len(hits)

# Initialize runtime BAML configuration
b = init_baml_client(b)

service = Service("WeaviateExpertService")

# ---------------------------------------------------------------------------
# GLOBAL SINGLETON: Persistent Weaviate Client
# ---------------------------------------------------------------------------
_GLOBAL_WEAVIATE_CLIENT = None

def get_weaviate_client():
    """Lazy-loads a persistent, global Weaviate connection pool."""
    global _GLOBAL_WEAVIATE_CLIENT
    
    # Return existing client if it's already connected
    if _GLOBAL_WEAVIATE_CLIENT is not None and _GLOBAL_WEAVIATE_CLIENT.is_connected():
        return _GLOBAL_WEAVIATE_CLIENT

    _GLOBAL_WEAVIATE_CLIENT = create_weaviate_client()
    return _GLOBAL_WEAVIATE_CLIENT

def fetch_weaviate_schema(weaviate_client, collection_name: str) -> str:
    """Fetches the live metadata properties available in Weaviate."""
    try:
        collection = weaviate_client.collections.get(collection_name)
        config = collection.config.get()
        
        # Extract the property names and their data types
        properties = []
        for prop in config.properties:
            properties.append(f"- {prop.name} (Type: {prop.data_type.name})")
            
        schema_str = f"Available Metadata Filters for {collection_name}:\n" + "\n".join(properties)
        return schema_str
    except Exception as e:
        return f"Could not fetch Weaviate schema: {str(e)}"

@service.handler()
async def query_knowledge(ctx: Context, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Durable entrypoint for the Weaviate Semantic Expert (Engine W).
    Handles pure KNOWLEDGE_RETRIEVAL intents.
    """
    user_query = request.get("user_query")
    domain = request.get("domain", "MAINTENANCE").upper()
    domain_label = domain.replace(" ", "_").replace("-", "_")
    doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

    # ADR-0025 engines arc (Engine W): the caller's ENTITLEMENT KEY (email),
    # threaded from auth → supervisor's specialist dispatch (which already
    # carries `user_email`) → the /query_knowledge proxy (full-payload
    # forward) → here. This is the SUBJECT of the per-chunk can_read gate that
    # the result-filter applies before synthesis (a chunk whose source
    # document the caller isn't granted must never reach the LLM). Engine W
    # started with NO caller identity (only query+domain) — reading it here is
    # the identity-reaches-the-enforcement-point prerequisite. Empty when
    # absent → the gate denies (fail-closed).
    caller_email = request.get("user_email") or ""
    print(f"[Engine W] query_knowledge caller_email={caller_email!r} domain={domain}")

    # Safely fetch the persistent client without blocking the async loop
    weaviate_client = await asyncio.to_thread(get_weaviate_client)

    # Fetch Weaviate schema dynamically via Restate
    async def fetch_weaviate_schema_task() -> str:
        return await asyncio.to_thread(fetch_weaviate_schema, weaviate_client, doc_collection_name)
        
    weaviate_schema_string = await ctx.run("fetch-weaviate-schema", fetch_weaviate_schema_task)

    # --------------------------------------------------------------------------
    # Source attribution (Phase 3 of grounding panel)
    # --------------------------------------------------------------------------
    # Source records are now collected INSIDE `run_smolagent` (see below)
    # and returned through Restate's `ctx.run` journal so they survive
    # replay. The previous closure-scoped accumulator broke under
    # journal replay because mutations to outer-scope variables don't
    # replay when ctx.run returns its cached result. See run_smolagent's
    # docstring for the full failure-mode explanation.
    #
    # Architect's discipline (carried through to citation layer):
    # snippet = matched-chunk text VERBATIM (NOT an LLM summary). Synthesis
    # at the citation layer is the exact failure this panel exists to
    # prevent — users must be able to read the words the retriever
    # actually saw.
    #
    # Dedup-by-uri so a multi-tool-call loop that hits the same chunk
    # twice doesn't produce duplicate sources. First-seen relevance wins
    # (the agent's first call gets the most relevant ordering; later
    # exploratory calls are weaker and shouldn't override the first
    # relevance score).
    sources_collected: List[Dict[str, Any]] = []

    def _collect_weaviate_source_DEAD(obj, search_query: str) -> None:
        """DEAD: replaced by `_collect_local` inside run_smolagent. Kept
        as a stub to avoid disturbing the rest of the file's structure;
        retire in a follow-up cleanup. Original docstring: Project a
        Weaviate object into the Source shape the UI expects."""
        try:
            doc_id = obj.properties.get("doc_id") or "Unknown Document"
            text = obj.properties.get("text") or ""
            page_number = obj.properties.get("page_number")
            object_uri = obj.properties.get("source_url") or obj.properties.get("uri") or f"weaviate://{doc_collection_name}/{obj.uuid}"
            if object_uri in sources_seen_uris:
                return
            sources_seen_uris.add(object_uri)
            # relevance: weaviate-client v4 surfaces `score` (hybrid) or
            # `certainty` (near_*). Either is a 0..1 signal that maps
            # directly to the cortex-ui ConfidenceBar.
            #
            # WATCH: for a `near_vector` query, Weaviate v4 returns
            # `metadata.score = 0.0` (NOT None) — score only carries
            # signal in hybrid/BM25 queries. The naive `is not None`
            # check picked up the 0.0 and locked the UI's MATCH bar to
            # 0% even when the chunk was a strong vector hit. The fix
            # below prefers a POSITIVE score, then certainty, then
            # 1.0 - distance (for near_*) so the projection always
            # carries the strongest available signal.
            # Banked at 2026-06-28 when the cortex-ui SourcesTrail
            # showed real helmet chunks at MATCH=0% on a clean query.
            relevance: float | None = None
            md = getattr(obj, "metadata", None)
            if md is not None:
                score = getattr(md, "score", None)
                certainty = getattr(md, "certainty", None)
                distance = getattr(md, "distance", None)
                if score is not None and float(score) > 0:
                    relevance = float(score)
                elif certainty is not None:
                    relevance = float(certainty)
                elif distance is not None:
                    # Cosine distance: 0 = perfect, 2 = opposite. Map to
                    # [0, 1] confidence as max(0, 1 - distance) — only
                    # used when neither score nor certainty is set,
                    # which is rare but possible for some query shapes.
                    relevance = max(0.0, 1.0 - float(distance))
            label = source_label(doc_id, page_number)
            sources_collected.append({
                "type": "document",
                "label": label,
                "uri": str(object_uri),
                # First ~240 chars of matched-chunk text (snippet, not
                # summary — see discipline note above).
                "snippet": (text[:240].strip() + ("…" if len(text) > 240 else "")) if text else None,
                "relevance": relevance,
                "open_url": str(object_uri) if str(object_uri).startswith(("http://", "https://", "s3://")) else None,
                # search_query is the actual semantic_query the agent
                # passed in — useful as audit trail (which query call
                # produced this match).
                "matched_for": search_query,
            })
        except Exception as collect_err:
            # Source-collection failure must NEVER kill the search;
            # log and continue. [[trailing-steps-nonfatal]] applied
            # to the citation accumulator.
            print(f"Source-collection failed in Engine W (non-fatal): {collect_err}")

    # --------------------------------------------------------------------------
    # The Semantic Tool
    # --------------------------------------------------------------------------
    @tool
    def search_knowledge_base(semantic_query: str, metadata_filters: dict = None) -> str:
        """
        Searches the text of the technical manuals for policies, definitions, summaries, and general knowledge.

        Args:
            semantic_query: The natural language search phrase.
            metadata_filters: Optional dictionary of metadata fields and exact values to filter by (e.g., {"doc_id": "TM-123"}).
        """
        try:
            collection = weaviate_client.collections.get(doc_collection_name)

            # Base filter: strict domain segregation
            base_filter = wvc.query.Filter.by_property("domain").equal(domain_label)

            if metadata_filters and isinstance(metadata_filters, dict):
                filter_list = [base_filter]
                for key, value in metadata_filters.items():
                    filter_list.append(wvc.query.Filter.by_property(key).equal(value))
                final_filter = wvc.query.Filter.all_of(filter_list)
            else:
                final_filter = base_filter

            # STRICT DOMAIN SEGREGATION FILTER + explicit vector.
            # We compute the query vector via embed_query() (LiteLLM
            # /embeddings, search_query: prefix) instead of letting
            # Weaviate vectorize the query via a text2vec module — code
            # owns the contract, NOT infra. See agent_fleet/utils/embed.py.
            # return_metadata=ALL surfaces score/certainty so the
            # source-attribution accumulator can populate `relevance`.
            metadata_query = wvc.query.MetadataQuery(score=True, certainty=True, distance=True)
            try:
                query_vector = embed_query(semantic_query)
                response = collection.query.near_vector(
                    near_vector=query_vector,
                    limit=5,
                    filters=final_filter,
                    return_metadata=metadata_query,
                )
            except Exception as embed_err:
                # If the embedding gateway is down, fall back to BM25 so
                # the engine still returns something instead of error.
                # Logs the failure so observability surfaces the gap.
                print(f"embed_query failed in Engine W; BM25 fallback: {embed_err}")
                response = collection.query.bm25(
                    query=semantic_query,
                    limit=5,
                    filters=final_filter,
                    return_metadata=metadata_query,
                )

            if not response.objects:
                return f"No relevant information found for '{semantic_query}' in the {domain} domain."

            results = []
            dropped = 0
            for idx, obj in enumerate(response.objects):
                text = obj.properties.get("text", "")
                doc_id = obj.properties.get("doc_id", "Unknown Document")
                # RESULT-FILTER — runs BEFORE synthesis (this string is the
                # LLM's tool result). Gate each chunk on can_read of its SOURCE
                # DOCUMENT; drop ungated chunks so the smolagent NEVER sees
                # them — a chunk in `results` is a chunk the LLM can synthesize
                # into the answer, so filtering here (not after) is what makes
                # this a real gate and not a fig leaf. The source identity is
                # stamped at ingest (source_url/uri/doc_id); an UNRESOLVABLE
                # source fails CLOSED (dropped), because an unidentifiable
                # chunk can't be gated and letting it through is the leak.
                # NB the "strict domain segregation" filter above is RELEVANCE
                # scope, NOT enforcement — this can_read gate is the enforcement,
                # and it runs regardless of what segregation already did.
                source_id = (
                    obj.properties.get("source_url")
                    or obj.properties.get("uri")
                    or obj.properties.get("doc_id")
                )
                if source_id == "Unknown Document":
                    source_id = None
                if ENABLE_AGENTIC_AUTH and not _can_read_document(caller_email, source_id):
                    dropped += 1
                    continue
                results.append(f"--- Excerpt {idx + 1} (Source: {doc_id}) ---\n{text}")
                # Accumulate the source record for the engine's response.
                _collect_weaviate_source(obj, semantic_query)

            if dropped:
                print(
                    f"[Engine W] result-filter DROPPED {dropped} ungated/unresolvable "
                    f"chunk(s) BEFORE synthesis (caller={caller_email!r})"
                )
            if not results:
                return (
                    f"No accessible information found for '{semantic_query}' in the "
                    f"{domain} domain. Matching documents exist but you are not granted "
                    f"read access to them — request access to the specific document."
                )
            return "\n\n".join(results)
        except Exception as e:
            return f"Error executing semantic search: {str(e)}"

    # --------------------------------------------------------------------------
    # The Agent Execution Loop
    # --------------------------------------------------------------------------
    async def run_smolagent() -> Dict[str, Any]:
        """Run the smolagent and return a dict containing BOTH the agent's
        text response AND the collected sources.

        Why a dict (not just str): the previous version returned only the
        agent response and mutated the OUTER-scope ``sources_collected`` /
        ``sources_seen_uris`` closure variables via
        ``_collect_weaviate_source``. That worked for fresh invocations
        but broke under Restate's `ctx.run` JOURNAL REPLAY: on resume
        after suspension, Restate returns the cached `ctx.run` result
        WITHOUT re-executing the function, so the closure mutations
        don't replay — `sources_collected` stays `[]` and the engine
        returned a response with empty sources. Caught 2026-06-30 when
        the cortex-ui Sources card was empty for some helmet queries
        despite Engine W having 5+ hits.

        Fix: include the collected sources in the journal-captured
        return value so they're durable across replays. Closure no
        longer relied on. The outer `sources_collected` initialization
        is removed — collection happens locally to this function and
        flows back through ctx.run's journal.
        """
        local_sources: List[Dict[str, Any]] = []
        local_seen_uris: set[str] = set()

        def _collect_local(obj, search_query: str) -> None:
            try:
                doc_id = obj.properties.get("doc_id") or "Unknown Document"
                text = obj.properties.get("text") or ""
                page_number = obj.properties.get("page_number")
                object_uri = (
                    obj.properties.get("source_url")
                    or obj.properties.get("uri")
                    or f"weaviate://{doc_collection_name}/{obj.uuid}"
                )
                if object_uri in local_seen_uris:
                    return
                local_seen_uris.add(object_uri)

                relevance = _hit_relevance(obj)

                label = source_label(doc_id, page_number)
                local_sources.append({
                    "type": "document",
                    "label": label,
                    "uri": str(object_uri),
                    "snippet": (
                        text[:240].strip() + ("…" if len(text) > 240 else "")
                    ) if text else None,
                    "relevance": relevance,
                    "open_url": str(object_uri) if str(object_uri).startswith(
                        ("http://", "https://", "s3://")
                    ) else None,
                    "matched_for": search_query,
                })
            except Exception as collect_err:
                print(
                    f"Source-collection failed in Engine W (non-fatal): "
                    f"{collect_err}"
                )

        # Inner search tool — same body as the outer `search_knowledge_base`
        # but collects into `local_sources` instead of the closure
        # variable. Wrapped as a tool so smolagent can call it.
        @tool
        def search_knowledge_base_local(
            semantic_query: str, metadata_filters: dict = None
        ) -> str:
            """
            Searches the text of the technical manuals for policies,
            definitions, summaries, and general knowledge.

            Args:
                semantic_query: The natural language search phrase.
                metadata_filters: Optional dictionary of metadata fields
                    and exact values to filter by (e.g., {"doc_id": "TM-123"}).
            """
            try:
                # RESULT-FILTER (before synthesis) — THIS is the LIVE tool (the agent below is
                # given `search_knowledge_base_local`, NOT the outer `search_knowledge_base`).
                # `retrieve_gated_chunks` searches by KNOWLEDGE_SEARCH_VIA_MESH's path and gates
                # every hit with ONE function on either path; a chunk not in `kept` never reaches
                # the smolagent. Unresolvable source fails CLOSED.
                kept, dropped, retrieved = retrieve_gated_chunks(
                    weaviate_client,
                    collection_name=doc_collection_name,
                    domain_label=domain_label,
                    semantic_query=semantic_query,
                    metadata_filters=metadata_filters,
                    caller_email=caller_email,
                )

                if not retrieved:
                    return f"No relevant information found for '{semantic_query}' in the {domain} domain."

                results = []
                for idx, obj in kept:
                    text = obj.properties.get("text", "")
                    doc_id = obj.properties.get("doc_id", "Unknown Document")
                    results.append(
                        f"--- Excerpt {idx + 1} (Source: {doc_id}) ---\n{text}"
                    )
                    _collect_local(obj, semantic_query)
                if dropped:
                    print(
                        f"[Engine W] result-filter DROPPED {dropped} ungated/unresolvable "
                        f"chunk(s) BEFORE synthesis (caller={caller_email!r})"
                    )
                if not results:
                    return (
                        f"No accessible information found for '{semantic_query}' in the "
                        f"{domain} domain. Matching documents exist but you are not granted "
                        f"read access to them — request access to the specific document."
                    )
                return "\n\n".join(results)
            except CallerRequired:
                return KNOWLEDGE_CALLER_REQUIRED_REFUSAL
            except Exception as e:
                return f"Error executing semantic search: {str(e)}"

        model = get_smolagent_model()
        # ToolCallingAgent (structured tool-calls) — NOT CodeAgent (free-form
        # Python in <code> tags). gpt-oss intermittently fumbles the CodeAgent
        # envelope (prose-glued-to-code parse errors -> empty answers); the
        # structured format is low-load enough that it doesn't. Proven on E/A.
        # The search_knowledge_base_local GATE (per-document result-filter before
        # synthesis) is unchanged — the agent CALLS the tool instead of writing
        # code that calls it; the gate still runs inside the tool. Requires the
        # litellm ollama_chat/ route (ollama/ dropped tool_calls).
        agent = ToolCallingAgent(
            tools=[search_knowledge_base_local],
            model=model,
            add_base_tools=False
        )

        system_prompt = f"""
        You are a Technical Librarian and Policy Expert for the {domain} domain.
        Your sole job is to answer the user's query by searching the knowledge base and summarizing the findings accurately.
        Never invent information. If the search tool returns no results, state clearly that the information is unavailable.
        ALWAYS include the Source Document IDs in your final answer so the user knows where the information came from.

        When using the search_knowledge_base_local tool, you may only filter using the following metadata properties:
{weaviate_schema_string}
        """

        tool_reminder = """
HOW TO ANSWER: call search_knowledge_base_local to retrieve relevant passages,
then call final_answer with your summary. Use only what the tool returns — never
invent information. If the tool returns no results, say the information is
unavailable. ALWAYS include the Source Document IDs from the results in your
final answer so the user knows where the information came from.
"""

        full_query = f"{system_prompt}\n{tool_reminder}\n\nUser Query: {user_query}"
        agent_response = str(await asyncio.to_thread(agent.run, full_query))
        # Both pieces of state cross the ctx.run boundary together. On
        # replay the entire dict (including local_sources) is returned
        # from the journal — sources survive.
        return {"agent_response": agent_response, "sources": local_sources}

    smolagent_result = await ctx.run("run-smolagent", run_smolagent)
    raw_agent_response = smolagent_result.get("agent_response", "")
    # Replace the outer closure-mutated list with the durable result so
    # the downstream `final_structured_dict["sources"] = sources_collected`
    # assignment works on both fresh AND replayed invocations.
    sources_collected = smolagent_result.get("sources", [])

    # --------------------------------------------------------------------------
    # BAML Strict Formatting
    # --------------------------------------------------------------------------
    async def format_baml() -> Dict[str, Any]:
        # Use our new dedicated Knowledge format contract
        baml_response = await b.FormatKnowledgeResponse(raw_agent_response, domain)
        return baml_response.model_dump()
        
    final_structured_dict = await ctx.run("format-baml", format_baml)

    # Phase 3 source attribution: attach the accumulated source records
    # to the engine's response. The supervisor reads this in
    # execute_subtask and materializes a Dagster `subtask_sources` asset
    # which the gateway projects into the typed `sources` SSE event.
    # The field name `sources` is the supervisor's expected key (other
    # engines W/E/A use the same key for a uniform contract).
    #
    # Dropped silently if the BAML response already has a `sources` key
    # (defensive against a future BAML schema change that adds one).
    if "sources" not in final_structured_dict:
        final_structured_dict["sources"] = sources_collected

    return final_structured_dict
