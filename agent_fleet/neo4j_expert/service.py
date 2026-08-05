import os
import sys
import asyncio
import json
import logging
import httpx
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Add baml_shared to Python path so we can import telemetry
_CURRENT_FILE = Path(__file__).resolve()
try:
    _REPO_ROOT = _CURRENT_FILE.parents[2]
    _BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
    if _BAML_SHARED_PATH.exists() and str(_BAML_SHARED_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_SHARED_PATH))
except IndexError:
    pass

try:
    from telemetry import (safe_observe, safe_update_observation,
                           observed_trace, MAPPING, build_trace_values)
except ImportError:
    def safe_observe(**kwargs):
        def decorator(func):
            return func
        return decorator
    def safe_update_observation(input_data=None, output_data=None):
        pass
    from contextlib import contextmanager as _cm
    @_cm
    def observed_trace(*_a, **_k):
        yield
    def build_trace_values(**_k):
        return {}
    MAPPING = None

from restate import Context, Service
from smolagents import CodeAgent, ToolCallingAgent

# ---------------------------------------------------------------------------
# Fleet-standard utilities — memoized Weaviate client + shared mem0 singleton.
# Previously this engine built its own Weaviate client AND the full mem0 stack
# inside every /query_graph request, which (a) leaked one gRPC + HTTP
# connection per request and (b) blocked the async event loop with sync
# Memory.from_config() schema verification. The shared singleton in
# utils.mem0_utils builds the stack exactly once per pod on a worker thread.
# ---------------------------------------------------------------------------
try:
    from utils.weaviate_utils import get_weaviate_client
    from utils.mem0_utils import get_mem0_memory
    from utils.embed import embed_query
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import get_weaviate_client
        from agent_fleet.utils.mem0_utils import get_mem0_memory
        from agent_fleet.utils.embed import embed_query
    except ImportError:
        # Fallback for flat layout in container
        from weaviate_utils import get_weaviate_client
        from mem0_utils import get_mem0_memory
        from embed import embed_query

try:
    # Workspace root (Container)
    from llm_utils import get_smolagent_model
except ImportError:
    try:
        # Module-relative (Local dev)
        from .llm_utils import get_smolagent_model
    except ImportError:
        # Parent-relative (Local dev)
        from agent_fleet.llm_utils import get_smolagent_model

# Import from standard shared schemas & the ones just generated in Step 1
from baml_client import b
from baml_py import baml_py


# ADR-0025 engines arc — Engine E's per-document READ gate. IDENTICAL to Engine
# W's `_can_read_document` (both gate DocumentChunks on the SAME `document`
# namespace / IRIs / grants) — this is the PORT of W's proven filter to E's
# `search_manual_text` tool (tool 1 of 3). Candidate for a shared authz-client
# module; duplicated for now so E is self-contained (separate deployment).
# ENABLE_AGENTIC_AUTH dark-launches it (OFF → no filtering, current behavior;
# flips LAST with all engines).
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")
ENABLE_AGENTIC_AUTH = os.getenv("ENABLE_AGENTIC_AUTH", "false").lower() in ("true", "1", "yes")


def _can_read_document(caller_email: str, source_id: str) -> bool:
    """Ask Topaz whether ``caller_email`` may READ the source ``document``.
    DENY-BY-DEFAULT, explicit owner/reader grant only (same gate/objects/grants
    as Engine W — shared `document` namespace). FAIL-CLOSED on empty
    caller/source, unresolvable source, or ANY error → the chunk is DROPPED,
    never synthesized (an unidentifiable chunk is the leak)."""
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
        print(f"[Engine E] can_read check FAILED (fail-closed deny) src={source_id!r}: {e}")
        return False

# Initialize runtime BAML configuration logic
try:
    # Workspace root (Container)
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        # Module-relative
        from .llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        try:
            # Parent-relative
            from agent_fleet.llm_utils import init_baml_client
            b = init_baml_client(b)
        except ImportError:
            pass

try:
    from tools import execute_cypher as _module_execute_cypher, get_graph_schema, get_neo4j_driver
    from prompts import PERSONA_PROMPTS
except ImportError:
    from .tools import execute_cypher as _module_execute_cypher, get_graph_schema, get_neo4j_driver
    from .prompts import PERSONA_PROMPTS

# Phase 3 source attribution wraps `execute_cypher` inside the request
# handler so each Cypher result's URI/IRI fields flow into
# sources_collected. The module-level tool is aliased above; the
# handler-scope wrapper is defined alongside the other closure-bound
# helpers (see query_graph()).

service = Service("Neo4jExpertService")

def fetch_dynamic_schema_from_neo4j() -> str:
    """Fetches the live Neo4j database schema at boot-time."""
    try:
        from tools import get_neo4j_driver
        driver = get_neo4j_driver()
        with driver.session() as session:
            result = session.execute_read(lambda tx: list(tx.run("CALL apoc.meta.schema() YIELD value RETURN value")))
            if not result:
                return "Schema not available."
            return json.dumps(result[0]["value"], indent=2)
    except Exception as e:
        return f"Error fetching schema: {e}"

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
async def query_graph(ctx: Context, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Durable entrypoint for the Neo4j Graph Expert.
    Runs the smolagent CodeAgent, then formats the result via BAML.
    
    Expected Request Dict:
    {
      "user_query": "What tools are needed to remove the main rotor?",
      "persona": "MECHANIC",
      "user_id": "mechanic_bob123"
    }
    """
    user_query = request.get("user_query")
    # Per ADR-0009 persona split: Engine E's PERSONA_PROMPTS drives the
    # smolagent's *answerer* voice — what response shape and tone the engine
    # produces. Read answerer_persona first; fall back to legacy `persona`
    # for callers that haven't migrated; finally default to MECHANIC.
    answerer_persona = (
        request.get("answerer_persona")
        or request.get("persona")
        or "MECHANIC"
    )
    persona_str = answerer_persona.upper()
    # user_persona is captured for observability / future per-caller policy
    # (e.g. response filtering) but does not currently change the prompt.
    user_persona = (request.get("user_persona") or persona_str).upper()
    user_id = request.get("user_id")
    # ADR-0025 engines arc: the caller's ENTITLEMENT KEY (email), threaded from
    # the supervisor's specialist dispatch (same payload W reads) → the subject
    # of the per-document can_read gate the search_manual_text result-filter
    # applies before synthesis. Empty when absent → gate denies (fail-closed).
    caller_email = request.get("user_email") or ""
    print(f"[Engine E] query_graph caller_email={caller_email!r}")

    system_prompt = PERSONA_PROMPTS.get(persona_str, PERSONA_PROMPTS["MECHANIC"])
    
    # Fetch schema dynamically via Restate to ensure durability
    async def fetch_schema() -> str:
        return fetch_dynamic_schema_from_neo4j()
        
    db_schema_string = await ctx.run("fetch-schema", fetch_schema)
    
    schema_injection = f"""
CRITICAL GRAPH SCHEMA:
You must ONLY use the following Nodes, Properties, and Relationships. Do not guess.
{db_schema_string}
"""
    
    # 🔗 DOMAIN-SPECIFIC NODE LABEL CONSTRAINTS (Strict Data Segregation)
    domain = request.get("domain", "MAINTENANCE").upper()
    
    # Sanitize the domain string for safe Neo4j label usage
    domain_label = domain.replace(" ", "_").replace("-", "_")

    domain_constraints = f"""
{schema_injection}

    You are operating within the {domain} domain (queries are automatically
    scoped to it).

    HOW TO QUERY THE GRAPH — use these STRUCTURED tools (you do NOT write raw
    Cypher; these are Cypher-shaped operations):
      • find_nodes(label, name_contains) — DISCOVER nodes of a type; returns
        their {{uri, label}} IDENTITIES (not their content).
        e.g. find_nodes("Procedure", "rotor removal"), find_nodes("Hazard").
      • traverse(from_uri, relationship, to_label) — follow ONE hop from a node
        to connected nodes' identities.
        e.g. traverse("<a-uri>", "HAS_PART", "Part").
      • fetch_content(uris) — get the CONTENT of nodes, but ONLY those you are
        granted to read (ungated ones are omitted). Pass uris from find_nodes.
      • count_accessible(label, name_contains) — count nodes you can read.

    THE WORKFLOW: find_nodes / traverse to DISCOVER identities → fetch_content
    with those uris to READ the content you're permitted. Use get_graph_schema
    to see available labels (e.g. Procedure, Part, Tool, Hazard, DataModule,
    WorkInstruction, WorkPackage). Use search_manual_text for conceptual,
    symptom, or how-to questions where the answer is in unstructured manual text.
    """
    
    system_prompt_with_segregation = system_prompt + "\n" + domain_constraints

    # --------------------------------------------------------------------------
    # Acquire shared Weaviate client + mem0 Memory singleton. Both are
    # process-wide (built once per pod on a worker thread, see utils.*).
    # Previously this section built a fresh Weaviate client AND the entire
    # mem0 stack inside every request — leaking gRPC connections and
    # starving the asyncio loop with sync Memory.from_config() schema work.
    # --------------------------------------------------------------------------
    weaviate_client = await asyncio.to_thread(get_weaviate_client)
    m = await get_mem0_memory()

    from smolagents import tool
    import weaviate.classes as wvc

    # The collection name where doc-tools ingests manual chunks
    doc_collection_name = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")

    # Fetch Weaviate schema dynamically via Restate (on a thread — gRPC is sync)
    async def fetch_weaviate_schema_task() -> str:
        return await asyncio.to_thread(
            fetch_weaviate_schema, weaviate_client, doc_collection_name
        )

    weaviate_schema_string = await ctx.run("fetch-weaviate-schema", fetch_weaviate_schema_task)

    weaviate_constraints = f"""
    When using the search_manual_text tool, you may only filter using the following metadata properties:
{weaviate_schema_string}
"""
    system_prompt_with_segregation += "\n" + weaviate_constraints

    # ADR-0016 r2 Open Items: port Engine A's grounding rule into Engine E.
    # Engine A had the "PAST EXPERIENCE IS A HINT, NEVER A FACT" guard at
    # restate_analyst/main.py:577-580; Engine E lacked it, which made
    # Engine E re-enable a known regression risk. Even though infer=False
    # neuters the write-side extractor poisoning, the read-side surfacing
    # of past raw transcripts still needs a grounding fence so the agent
    # doesn't treat stale summaries as authoritative.
    grounding_rule = (
        "\n\n"
        "CRITICAL GROUNDING RULE: You must NEVER invent, guess, or extrapolate facts. "
        "Use only what the tools return (find_nodes, traverse, fetch_content, "
        "count_accessible, get_graph_schema, "
        "search_manual_text). If a specific field the user asked about is genuinely "
        "absent from the tool result, state it is not available — but do NOT claim a "
        "field is missing if the tool returned it.\n\n"
        "PAST EXPERIENCE IS A HINT, NEVER A FACT.\n"
        "The \"Relevant Past Experience\" block (when present below) is drawn from "
        "earlier sessions in this engine's own memory partition — raw user questions "
        "and the agent's prior summaries of how it answered them. It MAY reflect "
        "summaries of your own previous answers — and you have been wrong before. "
        "Treat past experience as a possibly-stale starting hypothesis, NEVER as "
        "ground truth. You MUST verify against the current tool output before "
        "reporting anything. If past experience says \"no X exists\" for the current "
        "question, IGNORE that claim and run the tool anyway; an empty result must "
        "come from a fresh search, not from memory. Repeating a past wrong answer "
        "because it appears in past experience is the most common cascading failure "
        "in this system. The tool is authoritative; past experience is conversational "
        "background only.\n"
    )
    system_prompt_with_segregation += grounding_rule

    # Phase 3 source attribution — closure-scoped accumulator matching
    # Engine W's pattern. Sources collected here from search_manual_text
    # ride out to the supervisor in the response's `sources` key. Cypher-
    # result source attribution (graph_node typed sources from execute_cypher
    # node URIs) is a separate follow-up — same accumulator, additional
    # collection site.
    sources_collected: List[Dict[str, Any]] = []
    sources_seen_uris: set[str] = set()

    def _collect_weaviate_source(obj, search_query: str) -> None:
        """Project a Weaviate object into the Source shape the UI expects.
        See Engine W's _collect_weaviate_source for the architect's
        discipline (snippet = matched-chunk text verbatim, never a
        summary; dedup by uri so multi-tool-call loops don't duplicate).
        """
        try:
            doc_id = obj.properties.get("doc_id") or "Unknown Document"
            text = obj.properties.get("text") or ""
            page_number = obj.properties.get("page_number")
            object_uri = obj.properties.get("source_url") or obj.properties.get("uri") or f"weaviate://{doc_collection_name}/{obj.uuid}"
            if object_uri in sources_seen_uris:
                return
            sources_seen_uris.add(object_uri)
            relevance: float | None = None
            md = getattr(obj, "metadata", None)
            if md is not None:
                if getattr(md, "score", None) is not None:
                    relevance = float(md.score)
                elif getattr(md, "certainty", None) is not None:
                    relevance = float(md.certainty)
            label = f"{doc_id}" + (f" · p.{page_number}" if page_number else "")
            sources_collected.append({
                "type": "document",
                "label": label,
                "uri": str(object_uri),
                "snippet": (text[:240].strip() + ("…" if len(text) > 240 else "")) if text else None,
                "relevance": relevance,
                "open_url": str(object_uri) if str(object_uri).startswith(("http://", "https://", "s3://")) else None,
                "matched_for": search_query,
            })
        except Exception as collect_err:
            print(f"Source-collection failed in Engine E (non-fatal): {collect_err}")

    def _walk_for_uris(obj):
        """Yield URI/IRI-like string values found anywhere in a parsed
        JSON structure. Catches both shape conventions Neo4j produces:
        (1) a field literally named ``iri``/``uri``/``urn`` carrying a
        URI value, and (2) any string value that looks like a URI by
        prefix (``http://``, ``https://``, ``urn:``). The second covers
        properties that aren't conventionally named but still carry
        attributable references (e.g. ``source_url``, ``manual_url``).
        """
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v and (
                    str(k).lower() in ("iri", "uri", "urn")
                    or v.startswith(("http://", "https://", "urn:"))
                ):
                    yield v
                elif isinstance(v, (dict, list)):
                    yield from _walk_for_uris(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from _walk_for_uris(item)

    def _collect_cypher_source(uri: str, query: str) -> None:
        """Append a Source record for a URI surfaced by a Cypher
        result. Dedupes by URI through sources_seen_uris (shared with
        the Weaviate-side collector so the same instance hit by both
        text and graph paths doesn't double-render in the
        SourcesTrail). Label strips the namespace prefix for
        readability while the full URI rides on the ``uri`` field for
        click-through and audit.
        """
        if not uri or uri in sources_seen_uris:
            return
        sources_seen_uris.add(uri)
        label = uri
        for sep in ("#", "/", ":"):
            if sep in label:
                label = label.rsplit(sep, 1)[-1] or label
        snippet = f"Returned by Cypher: {query[:200].strip()}"
        if len(query) > 200:
            snippet += "…"
        sources_collected.append({
            "type": "graph_node",
            "label": label or uri,
            "uri": uri,
            "snippet": snippet,
            "relevance": None,
            "open_url": uri if uri.startswith(("http://", "https://")) else None,
        })

    try:

        # ADR-0025 engines arc — TOOL 2: the DENY-BY-CONSTRUCTION query DSL.
        # Replaces the old `execute_cypher` (arbitrary Cypher → could project
        # `RETURN n.instructionText`, `count(n)` over ungated, unbounded paths).
        # The LLM now emits a BOUNDED, Cypher-flavored API. Unsafe queries are
        # INEXPRESSIBLE: discovery (find_nodes/traverse) returns only gateable
        # IDENTITIES (uri+label, never content); CONTENT flows ONLY through
        # fetch_content, which gates each node on can_read (shared `document`
        # namespace with W); aggregation (count_accessible) is GATE-THEN-
        # AGGREGATE (counts only the caller's granted set → no existence/
        # quantity oracle). The rendered Cypher is PARAMETERIZED ($name/$uri);
        # the ONLY interpolation is `label`/`domain_label`, each validated
        # against a strict identifier regex → no injection. Certifiable by
        # reading THIS API surface: no operation projects ungated content.
        import re as _re
        _LABEL_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

        def _valid_ident(s: str) -> bool:
            return bool(s) and bool(_LABEL_RE.match(str(s)))

        def _run_read(cypher: str, params: dict):
            drv = get_neo4j_driver()
            with drv.session() as session:
                return session.execute_read(
                    lambda tx: [dict(r) for r in tx.run(cypher, **params)]
                )

        # ── DSL CALIBRATION LOG (per-request, CONTENT-FREE by construction) ──────
        # Purpose: measure the DSL's WIDTH and the agent's FLUENCY with it — the
        # one open judgment deny-by-construction carries. With raw Cypher removed
        # there is no rejected-query stream to diff against "ran"; a coverage gap
        # therefore manifests as STRUGGLE (tool errors, shape-misuse, retries),
        # not as a rejected query. So we capture the realized op-sequence, the
        # gate decisions, and the struggle signal — and calibrate the DSL against
        # real query patterns rather than the known-query set it was built on.
        #
        # LEAK DISCIPLINE (this log sits right next to what it protects):
        #   • NEVER record content payloads (props/text/instructionText). Content
        #     in the log would be a SECOND uncontrolled copy past the gate — a
        #     side-channel leak. We record ONLY op names, non-content args
        #     (label/intent/uri identities), and gate-decision COUNTS + denied
        #     identities. Enforced by construction: no event carries `props`.
        #   • The log is itself a GATED resource, classified at the level of what
        #     it references — an intended query encodes existence-oracle knowledge
        #     (the tool-3 finding, now at the query layer). Emitted under a
        #     distinct `[Engine E CALIB]` tag so a real deployment routes it to a
        #     need-to-know sink, not the general app log.
        calib_events: list = []
        # Struggle stats captured from the agent's OWN step memory (the
        # execution_trace built from `agent.logs` is empty in smolagents 1.24 —
        # that attribute no longer exists — so parse/exec errors were invisible).
        # Populated by run_smolagent from agent.memory.steps; content-free
        # (COUNTS + a final-answer bool only, never step observations/output).
        run_stats: dict = {"n_steps": 0, "step_errors": 0, "reached_final": False}

        def _calib(**event) -> None:
            # Defensive: strip any accidental content-bearing key so a future
            # edit can't silently turn this into a leak. Only the allow-listed
            # metadata keys survive.
            _ALLOWED = {
                "op", "label", "name_filter", "to_label", "rel", "from_uri",
                "intent", "requested_n", "result_n", "granted_n", "denied_n",
                "denied_uris", "kept_n", "dropped_n", "accessible_count", "error",
            }
            calib_events.append({k: v for k, v in event.items() if k in _ALLOWED})

        @tool
        def find_nodes(label: str, name_contains: str = None) -> list:
            """Find graph nodes of a given TYPE, returning their IDENTITIES
            (uri + label) — NOT their content. Use this to DISCOVER what exists,
            then call fetch_content() with the uris you need.

            Args:
                label: the node type — e.g. "Procedure", "Part", "Tool",
                    "Hazard", "DataModule", "WorkInstruction", "WorkPackage".
                name_contains: optional case-insensitive substring filter on the
                    node's name/label.
            Returns: a Python list of {"uri":..., "label":...} dicts you can
                iterate directly (e.g. uris = [n["uri"] for n in result]).
                Domain-scoped, LIMIT 50.
            """
            if not _valid_ident(label) or not _valid_ident(domain_label):
                _calib(op="find_nodes", label=label, error=True)
                return [{"error": f"Invalid label {label!r} — use one node type like 'Procedure'."}]
            cypher = (
                f"MATCH (n:`{label}`:`{domain_label}`) "
                + ("WHERE toLower(coalesce(n.label,'')) CONTAINS toLower($name) " if name_contains else "")
                + "RETURN n.uri AS uri, coalesce(n.label, n.uri) AS label LIMIT 50"
            )
            try:
                rows = _run_read(cypher, {"name": name_contains} if name_contains else {})
                _calib(op="find_nodes", label=label, name_filter=bool(name_contains), result_n=len(rows))
                return rows
            except Exception as e:  # noqa: BLE001
                _calib(op="find_nodes", label=label, error=True)
                return [{"error": f"find_nodes error: {e}"}]

        @tool
        def traverse(from_uri: str, relationship: str = None, to_label: str = None) -> list:
            """Follow relationships ONE hop from a node (by uri) to connected
            nodes, returning their IDENTITIES (uri + label + relationship) —
            NOT content. Bounded to one hop by design.

            Args:
                from_uri: the starting node's uri (from find_nodes).
                relationship: optional relationship type to follow (e.g. "HAS_PART").
                to_label: optional node type to filter the destination.
            Returns: a Python list of {"uri":..., "label":..., "relationship":...}
                dicts you can iterate directly.
            """
            if to_label and not _valid_ident(to_label):
                _calib(op="traverse", from_uri=from_uri, error=True)
                return [{"error": f"Invalid to_label {to_label!r}."}]
            if relationship and not _valid_ident(relationship):
                _calib(op="traverse", from_uri=from_uri, error=True)
                return [{"error": f"Invalid relationship {relationship!r}."}]
            rel = f":`{relationship}`" if relationship else ""
            tgt = f":`{to_label}`" if to_label else ""
            cypher = (
                f"MATCH (n {{uri:$uri}})-[r{rel}]-(m{tgt}) "
                "RETURN m.uri AS uri, coalesce(m.label, m.uri) AS label, type(r) AS relationship LIMIT 50"
            )
            try:
                rows = _run_read(cypher, {"uri": from_uri})
                _calib(op="traverse", from_uri=from_uri, rel=relationship, to_label=to_label, result_n=len(rows))
                return rows
            except Exception as e:  # noqa: BLE001
                _calib(op="traverse", from_uri=from_uri, error=True)
                return [{"error": f"traverse error: {e}"}]

        @tool
        def fetch_content(uris: list) -> dict:
            """Fetch the CONTENT of specific nodes by uri — but ONLY for nodes
            you are GRANTED to read. Ungated nodes are omitted (listed under
            'denied_not_granted'). Pass uris from find_nodes()/traverse().

            Args:
                uris: list of node uri strings.
            Returns: a Python dict with TWO keys — NOT a list. It is keyed by uri,
                so DO NOT zip() it against your uris. Shape:
                  {"granted": {uri: {props...}}, "denied_not_granted": [uri, ...]}
                USAGE (iterate the granted map by uri):
                  result = fetch_content(uris)
                  for uri, props in result["granted"].items():
                      print(uri, props)         # props is this node's content
                  # result.get("denied_not_granted", []) = uris you may NOT read
            """
            if not isinstance(uris, list):
                uris = [uris]
            granted, denied = {}, []
            for uri in uris:
                if not isinstance(uri, str) or not uri:
                    continue
                # GATE before returning any content — shared document namespace
                # with W; fail-closed. This is the ONLY content path in the DSL.
                if ENABLE_AGENTIC_AUTH and not _can_read_document(caller_email, uri):
                    denied.append(uri)
                    continue
                try:
                    rows = _run_read("MATCH (n {uri:$uri}) RETURN properties(n) AS props LIMIT 1", {"uri": uri})
                    if rows:
                        granted[uri] = rows[0].get("props", {})
                        _collect_cypher_source(uri, "fetch_content")
                except Exception:  # noqa: BLE001
                    denied.append(uri)
            out = {"granted": granted}
            if denied:
                out["denied_not_granted"] = denied
                print(f"[Engine E] fetch_content DENIED {len(denied)} ungated node(s) (caller={caller_email!r})")
            # CONTENT-FREE calibration: counts + denied IDENTITIES only, never props.
            _calib(op="fetch_content", requested_n=len(uris), granted_n=len(granted),
                   denied_n=len(denied), denied_uris=denied)
            return out

        @tool
        def count_accessible(label: str, name_contains: str = None) -> dict:
            """Count nodes of a TYPE that YOU are granted to read (gate-then-
            aggregate). The count reflects ONLY your accessible set — never the
            full set — so it cannot reveal the size of data you lack access to.

            Args:
                label: the node type to count (e.g. "Procedure", "Part").
                name_contains: optional case-insensitive substring filter on the
                    node's name/label.
            Returns: a Python dict {"label": ..., "accessible_count": int}.
            """
            if not _valid_ident(label) or not _valid_ident(domain_label):
                _calib(op="count_accessible", label=label, error=True)
                return {"error": f"Invalid label {label!r}."}
            cypher = (
                f"MATCH (n:`{label}`:`{domain_label}`) "
                + ("WHERE toLower(coalesce(n.label,'')) CONTAINS toLower($name) " if name_contains else "")
                + "RETURN n.uri AS uri LIMIT 500"
            )
            try:
                rows = _run_read(cypher, {"name": name_contains} if name_contains else {})
            except Exception as e:  # noqa: BLE001
                _calib(op="count_accessible", label=label, error=True)
                return {"error": f"count_accessible error: {e}"}
            # GATE-THEN-AGGREGATE: count only the caller's granted uris.
            if ENABLE_AGENTIC_AUTH:
                n = sum(1 for r in rows if _can_read_document(caller_email, r.get("uri")))
            else:
                n = len(rows)
            _calib(op="count_accessible", label=label, accessible_count=n)
            return {"label": label, "accessible_count": n}

        @tool
        def search_manual_text(semantic_query: str, metadata_filters: dict = None) -> str:
            """
            Searches the actual text of the technical manuals for conceptual, symptom, or troubleshooting information.
            Use this when the user asks a "how-to", "why", or describes a symptom that isn't a simple part lookup.

            Args:
                semantic_query: The natural language search phrase (e.g., "troubleshoot whining noise on corroded rotor").
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

                # 🔗 STRICT DOMAIN SEGREGATION APPLIED TO VECTOR SEARCH.
                # return_metadata=ALL surfaces score/certainty so the
                # source-attribution accumulator can populate `relevance`
                # (Phase 3 of grounding panel).
                metadata_query = wvc.query.MetadataQuery(score=True, certainty=True, distance=True)
                # Compute the query vector via embed_query() (LiteLLM /embeddings)
                # instead of Weaviate's near_text vectorizer — code owns the
                # contract, NOT infra (same fix W made). E's near_text pointed at
                # an Ollama vectorizer (192.168.1.119:11434) UNREACHABLE from the
                # cluster ("no route to host"), so search_manual_text always
                # errored and retrieved nothing. Aligned to W's proven
                # embed_query + near_vector path with a BM25 fallback.
                try:
                    query_vector = embed_query(semantic_query)
                    response = collection.query.near_vector(
                        near_vector=query_vector,
                        limit=3,
                        filters=final_filter,
                        return_metadata=metadata_query,
                    )
                except Exception as embed_err:
                    print(f"embed_query failed in Engine E; BM25 fallback: {embed_err}")
                    response = collection.query.bm25(
                        query=semantic_query,
                        limit=3,
                        filters=final_filter,
                        return_metadata=metadata_query,
                    )

                if not response.objects:
                    return "No relevant manual text found for this query in the current domain."

                results = []
                dropped = 0
                for obj in response.objects:
                    # RESULT-FILTER (before synthesis) — tool 1 of E's 3 paths,
                    # the PORT of W's gate: this return string is the LLM's tool
                    # result, so gating each chunk on its source document's
                    # can_read here (and dropping ungated) means the smolagent
                    # never sees them. Unresolvable source fails CLOSED. The
                    # domain filter above is RELEVANCE, not enforcement.
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
                    results.append(obj.properties.get("text", ""))
                    # Accumulate the source for the engine's response.
                    _collect_weaviate_source(obj, semantic_query)

                if dropped:
                    print(
                        f"[Engine E] search_manual_text DROPPED {dropped} ungated/unresolvable "
                        f"chunk(s) BEFORE synthesis (caller={caller_email!r})"
                    )
                # CONTENT-FREE calibration: intent (the NL query) + kept/dropped
                # counts only — never the chunk text itself.
                _calib(op="search_manual_text", intent=semantic_query,
                       kept_n=len(results), dropped_n=dropped)
                if not results:
                    return (
                        "No accessible manual text found for this query in the current domain "
                        "— matching documents exist but you are not granted read access to them."
                    )
                return "\n\n---\n\n".join(results)
            except Exception as e:
                _calib(op="search_manual_text", intent=semantic_query, error=True)
                return f"Error executing semantic search: {str(e)}"

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            # ADR-0016 r2 Open Items: agent_id partition.
            # Mirrors restate_analyst/main.py; Engine A and Engine E
            # share the Mem0 collection so the partition is required
            # to isolate engine voices from each other.
            results = m.search(
                query=query,
                filters={
                    "user_id": user_id,
                    "agent_id": "engine_e_neo4j_expert",
                },
            )
            safe_update_observation(input_data=query, output_data=results)
            return results

        # --------------------------------------------------------------------------
        # Run 1: The Smolagents Graph Query Loop
        # --------------------------------------------------------------------------
        @safe_observe(name="smolagents_neo4j_execution")
        @safe_observe(name="smolagents_neo4j_execution")
        async def run_smolagent() -> tuple[str, str]:
            try:
                # Retrieve past successful memories to inject into the system prompt.
                # Bridge to a worker thread — m.search() is sync gRPC and must
                # not block the asyncio loop.
                if user_id:
                    past_memories_response = await asyncio.to_thread(
                        fetch_user_memory, user_query, user_id
                    )

                    if isinstance(past_memories_response, dict):
                        past_memories = past_memories_response.get("results", [])
                    else:
                        past_memories = past_memories_response
                        
                    if past_memories:
                        memory_strings = "\n".join([f"- {mem.get('memory', mem.get('text', ''))}" for mem in past_memories if isinstance(mem, dict)])
                        prompt_extension = f"\n\n### Relevant Past Experience\n{memory_strings}"
                        system_prompt_with_memory = system_prompt_with_segregation + prompt_extension
                    else:
                        system_prompt_with_memory = system_prompt_with_segregation
                else:
                    system_prompt_with_memory = system_prompt_with_segregation

                # Initialize the LLM (configurable via env var, defaults to lightweight model)
                model = get_smolagent_model()
                
                # Calibration STEP CALLBACK — the reliable struggle source.
                # step_callbacks fire DURING the run (once per ActionStep), so
                # counts survive even when the run later RAISES (max-steps / a
                # final parse failure) — the exact path that made a post-run
                # memory.steps read return 0. Content-free: counts + a bool only.
                def _on_action_step(memory_step, agent=None):
                    try:
                        run_stats["n_steps"] += 1
                        if getattr(memory_step, "error", None):
                            run_stats["step_errors"] += 1   # parse OR execution error
                        if getattr(memory_step, "is_final_answer", False):
                            run_stats["reached_final"] = True
                    except Exception:  # noqa: BLE001 — calibration must never break the run
                        pass

                # Instantiate the agent giving it ONLY the Neo4j tools and persona.
                # ToolCallingAgent (structured tool-calls) — NOT CodeAgent (free-form
                # Python in <code> tags). The calibration diagnostic proved gpt-oss
                # fumbles the CodeAgent ENVELOPE (parse errors, placeholder
                # final_answer), NOT the DSL (Cypher 12/12 + DSL 12/12 fluent
                # envelope-free); the fix is the lower-load structured format the
                # model drives cleanly — unblocked by the litellm ollama_chat/ route
                # (ollama/ silently dropped tool_calls). The DSL @tool defs are
                # unchanged; the agent now CALLS them as tools instead of writing
                # code that calls them (this also sidesteps the dict-shape fumble —
                # no code to misuse). step_callbacks still fire per ActionStep, so
                # the calibration instrument is unchanged.
                agent = ToolCallingAgent(
                    tools=[find_nodes, traverse, fetch_content, count_accessible, get_graph_schema, search_manual_text],
                    model=model,
                    add_base_tools=False,
                    step_callbacks=[_on_action_step],
                )

                # Tool-calling guidance (replaces the CodeAgent <code>-tag reminder,
                # which no longer applies — the agent emits structured tool-calls).
                tool_reminder = """
HOW TO ANSWER: call the provided tools in sequence, then call final_answer with
your answer. Typical flow: find_nodes/traverse to DISCOVER node identities →
fetch_content(uris=[...]) to READ the content you are permitted (ungated nodes
are omitted under 'denied_not_granted') → final_answer summarizing what you found.
Use only what the tools return; never invent data. If tool results contain image
references or file paths (e.g. image_path) plus figure titles, include those exact
paths and titles in your final_answer so the downstream formatter can render them.
"""

                final_prompt = f"{system_prompt_with_memory}\n\n{tool_reminder}\n\nUser Query: {user_query}"
                
                # Telemetry (ADR-0038): join Engine E's graph-reasoning generation(s) to the
                # caller's trace when a trace id reaches its body; a standalone enriched trace
                # otherwise. Fail-soft; no-op when disabled.
                with observed_trace(MAPPING, build_trace_values(
                    trace_id=request.get("trace_id"),
                    engine="neo4j_expert",
                    authz_id=request.get("user_id") or request.get("authz_id"),
                    # Legibility of a KNOWN join gap: until a proxy threads the caller's trace
                    # id into Engine E's restate BODY, its trace is an ORPHAN by limitation, not
                    # by accident. Tag it so a reader sees the disconnect IN THE DATA, not only
                    # in a handoff doc. Drops to None (joined) the moment a trace id arrives.
                    join_status=("join:pending-proxy" if not request.get("trace_id") else None),
                ), name="engine-e graph reasoning"):
                    # Run the agent in a thread pool since smolagents is synchronous
                    result = await asyncio.to_thread(agent.run, final_prompt)
                
                # Build the UI trace from `agent.memory.steps` (smolagents 1.24;
                # the old `agent.logs` attribute is gone — the previous block
                # silently produced an EMPTY trace). Struggle STATS come from the
                # step callback above, NOT here, so they survive a run that raises
                # before this post-run read. Best-effort; wrapped.
                formatted_trace = "--- Agent Execution Trace ---\n"
                try:
                    steps = getattr(getattr(agent, "memory", None), "steps", []) or []
                    for st in steps:
                        # Only ActionSteps carry error/tool_calls; skip task/plan steps.
                        if not hasattr(st, "error"):
                            continue
                        # UI trace (shown to the authorized caller) — code + result.
                        code = getattr(st, "code_action", None)
                        if code:
                            formatted_trace += f"Action:\n{code}\n"
                        err = getattr(st, "error", None)
                        if err:
                            formatted_trace += f"Error: {err}\n"
                        obs = getattr(st, "observations", None)
                        if obs:
                            formatted_trace += f"Result: {obs}\n"
                        formatted_trace += "-" * 40 + "\n"
                except Exception as trace_err:  # noqa: BLE001 — trace is best-effort
                    formatted_trace += f"(trace capture skipped: {trace_err})\n"

                return str(result), formatted_trace
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"ERROR in run_smolagent: {error_trace}")
                raise e
        # ── EMIT DSL CALIBRATION RECORD (content-free; classified; need-to-know) ──
        # The op-sequence IS the realized intent (deny-by-construction leaves no
        # rejected-query stream). Coverage/fluency gaps show up as STRUGGLE:
        #   • tool_errors — DSL calls that returned an error (bad label/args)
        #   • step_errors — agent code steps that failed (parse/exec), from the
        #     step callback: the fluency signal (prose-glued code, bad tags, the
        #     zip()-over-a-dict shape-misuse) the instrument exists to surface.
        #   • not reaching a final answer is itself a struggle (+1).
        # Only integers + already-collected content-free events are emitted; step
        # observations (which carry tool RESULTS = content) never touch this.
        # Emitted from a FINALLY so a run that RAISES (max-steps / hard parse
        # failure) — exactly when the struggle data matters MOST — still records.
        def _emit_calib() -> None:
            try:
                tool_errors = sum(1 for e in calib_events if e.get("error"))
                step_errors = run_stats.get("step_errors", 0)
                n_steps = run_stats.get("n_steps", 0)
                reached_final = run_stats.get("reached_final", False)
                calib_record = {
                    "engine": "E",
                    "caller": caller_email,
                    "domain": domain_label,
                    "intent": user_query,      # caller's NL request (may be null → no user_query sent)
                    "auth_enabled": ENABLE_AGENTIC_AUTH,
                    "ops": calib_events,       # realized DSL op-sequence (content-free)
                    "n_ops": len(calib_events),
                    "n_steps": n_steps,
                    "reached_final": reached_final,
                    "tool_errors": tool_errors,
                    "step_errors": step_errors,
                    "struggle": tool_errors + step_errors + (0 if reached_final else 1),
                }
                # References intended queries → NEED-TO-KNOW, classified at the
                # level of what it references. Distinct tag routes it to a gated
                # calibration sink in a real deployment, not the app log.
                print("[Engine E CALIB] " + json.dumps(calib_record, default=str))
            except Exception as _calib_err:  # noqa: BLE001 — calibration must never break delivery
                print(f"[Engine E CALIB] emit skipped: {_calib_err}")

        # Standard 120s timeout from the orchestrator allows for extended searching
        try:
            raw_agent_response, execution_trace = await ctx.run("run-smolagent", run_smolagent)
        finally:
            _emit_calib()

        # --------------------------------------------------------------------------
        # Run 2: BAML Strict Formatting
        # --------------------------------------------------------------------------
        async def format_baml() -> Dict[str, Any]:
            # Instantiate the BAML log collector
            collector = baml_py.Collector()
            
            # Uses the Async BAML client to format the raw unstructured string
            # into the union GraphExpertResponse based on the requested persona
            baml_response = await b.FormatGraphResponse(
                raw_agent_response, 
                persona_str,
                baml_options={"collector": collector}
            )
            
            # Extract the BAML logs
            baml_trace = "\n\n--- BAML Formatting Trace ---\n"
            if collector.logs and collector.logs[0].calls:
                # Get the first LLM call attempt
                call = collector.logs[0].calls[0]
                
                # Extract the rendered prompt and raw response
                # Depending on BAML version, http_request/http_response might be dicts or strings
                prompt = getattr(call, 'http_request', 'N/A')
                raw_llm_response = getattr(call, 'http_response', 'N/A')
                
                baml_trace += f"Prompt Sent:\n{prompt}\n\n"
                baml_trace += f"Raw LLM Response:\n{raw_llm_response}\n"
            
            # Combine both the smolagents trace and the BAML trace
            combined_trace = execution_trace + baml_trace
            
            # Inject execution trace
            baml_response.execution_trace = combined_trace
            
            # Returns the Pydantic .model_dump() dict which Restate will serialize to JSON
            return baml_response.model_dump()
            
        final_structured_dict = await ctx.run("format-baml", format_baml)
        
        # --------------------------------------------------------------------------
        # Run 3: Save Successful Event to Memory
        # --------------------------------------------------------------------------
        async def save_memory() -> str:
            if not user_id:
                return "no-user-id"

            # Bridge to a worker thread — m.add() is sync gRPC and must
            # not block the asyncio loop.
            #
            # ADR-0016 (r2) Tier 0(b): infer=False disables the Mem0
            # extractor LLM. Mirrors Engine A's restate_analyst/main.py
            # save_memory site — Engine E shares the Mem0 collection
            # under user_id-only scoping, so the same poisoning path
            # exists here. Lands in lockstep with Engine A so Phase 3
            # re-enable doesn't reintroduce the failure mode from a
            # second entry point.
            #
            # Trailing-step semantics: final_structured_dict (line ~442) is
            # already built and ready to return. A failure here MUST NOT
            # propagate up to restate as a step error — restate would retry
            # then eventually mark the whole invocation failed, and the
            # gateway would surface "Timeout or failed to fetch UI payload"
            # to a user who in fact had a correct Engine E answer ready.
            # Mirrors the engine-a guard (commit ff968f4). Same standing
            # rule (memory: trailing-steps-nonfatal). Catch Exception (not
            # BaseException) so CancelledError still propagates and
            # cooperative cancellation is preserved.
            try:
                await asyncio.to_thread(
                    m.add,
                    messages=[
                        {"role": "user", "content": user_query},
                        {"role": "assistant", "content": raw_agent_response}
                    ],
                    user_id=user_id,
                    agent_id="engine_e_neo4j_expert",
                    infer=False,
                )
            except Exception as e:
                logger.warning(
                    "save-memory mem0.add failed for user_id=%s "
                    "(non-fatal, Engine E answer already generated): %s",
                    user_id,
                    e,
                    exc_info=True,
                )
                return "skipped-error"
            return "saved"

        await ctx.run("save-memory", save_memory)

        # Phase 3 source attribution: attach accumulated sources to the
        # engine's response. The supervisor materializes them as a
        # subtask_sources Dagster asset; the gateway projects into the
        # typed SSE event the cortex-ui SourcesTrail consumes.
        # Engine E currently only captures sources from search_manual_text
        # (Weaviate hits = document sources). Cypher-result graph_node
        # sources from execute_cypher are a separate follow-up.
        if "sources" not in final_structured_dict:
            final_structured_dict["sources"] = sources_collected

        return final_structured_dict
    finally:
        # NOTE: we intentionally do NOT close weaviate_client here. It is a
        # process-wide singleton from utils.weaviate_utils.get_weaviate_client
        # shared across all requests for the lifetime of the pod.
        pass
