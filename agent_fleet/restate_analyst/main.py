"""
Engine A — Restate + Smolagents Durable Analyst Microservice

A FastAPI server backed by the Restate SDK for durable execution.
Before running the smolagents CodeAgent, the handler calls Engine O
(the ontology reasoner) to resolve the user's intent into a canonical
IOF/MIMOSA URI and suggested dbt models. This semantic context is then
passed into the agent so it knows which database tables to query.

Also contains the BPMNWorkflowRunner — a Restate Workflow that processes
BPMN tasks sequentially.  ServiceTasks execute via ``ctx.run()``;
UserTasks pause durably via ``ctx.promise().value()`` until a human
resolves them through the ``POST /workflow/{wf}/task/{tid}/approve``
endpoint.  Zero-cost waiting, crash-proof, no polling loops.

Run: uvicorn agent_fleet.restate_analyst.main:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import os

import httpx
import requests
import restate

import asyncio

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
    from telemetry import safe_observe, safe_update_observation
except ImportError:
    def safe_observe(**kwargs):
        def decorator(func):
            return func
        return decorator
    def safe_update_observation(input_data=None, output_data=None):
        pass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from restate import Context, ObjectContext, Service, VirtualObject, Workflow, WorkflowContext, WorkflowSharedContext

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path for the generated BAML types.
# In CNB containers, baml_client is copied locally — this is only for dev.
# ---------------------------------------------------------------------------
try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
    if str(_BAML_CLIENT_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_CLIENT_PATH))
except IndexError:
    pass  # Running in CNB container — baml_client is already in /workspace/

from baml_client.types import AgentResponse, AgentStatus, AgentTask, BPMNInterviewState, TopologyUI  # noqa: E402
from baml_client import b  # noqa: E402

# Initialize runtime BAML configuration logic
try:
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    # Fallback for local development
    try:
        from agent_fleet.llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

# Smolagents imports — only used inside the Restate handler.
# ---------------------------------------------------------------------------
from smolagents import CodeAgent
try:
    from llm_utils import get_smolagent_model
except ImportError:
    from agent_fleet.llm_utils import get_smolagent_model

# ---------------------------------------------------------------------------
# Fleet-standard utilities — memoized Weaviate client + shared mem0 singleton.
# The Memory object and its Weaviate-backed adapter are built once per pod,
# lazily, on a worker thread (see utils.mem0_utils). Previously this whole
# stack was rebuilt inside the async analyze() handler on every request,
# which blocked the event loop with sync gRPC and tripped the k8s readiness
# probe.
# ---------------------------------------------------------------------------
try:
    from utils.weaviate_utils import get_weaviate_client
    from utils.mem0_utils import get_mem0_memory
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import get_weaviate_client
        from agent_fleet.utils.mem0_utils import get_mem0_memory
    except ImportError:
        # Fallback for flat layout in container
        from weaviate_utils import get_weaviate_client
        from mem0_utils import get_mem0_memory


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ONTOLOGY_RESOLVE_URL = os.getenv(
    "ONTOLOGY_RESOLVE_URL",
    "http://ontology-agent-svc.default.svc.cluster.local:8084/resolve",
)
ONTOLOGY_TIMEOUT = 30  # seconds — ontology resolution is fast
AGENT_HTTP_TIMEOUT = int(os.getenv("AGENT_HTTP_TIMEOUT", "120"))
RESTATE_INGRESS_URL = os.getenv(
    "RESTATE_INGRESS_URL",
    "http://localhost:8081/restate",
)

# ---------------------------------------------------------------------------
# Restate Service — AnalystService
# ---------------------------------------------------------------------------
analyst_service = Service("AnalystService")


def _resolve_ontology(task_description: str) -> dict:
    """Call Engine O to resolve the task description into semantic context.

    This function is executed inside ``ctx.run()`` for durable execution —
    if the pod crashes mid-flight, Restate will replay and skip this step
    if it already completed successfully.
    """
    resp = requests.post(
        ONTOLOGY_RESOLVE_URL,
        json={"query": task_description},
        timeout=ONTOLOGY_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


from orchestrator.auth import current_user_token, current_trace_id

@analyst_service.handler()
async def analyze(ctx: Context, request: dict) -> dict:
    """Durable handler: resolve ontology → run smolagent → return AgentResponse.

    Every side-effectful operation is wrapped in ``ctx.run()`` so Restate
    can guarantee exactly-once execution even across pod restarts.
    """
    task = AgentTask(**request)
    dynamic_schema_map = request.get("dynamic_schema_map", "")
    user_id = request.get("user_id")

    # ADR-0008 fallback context (when the supervisor escalates to Engine A
    # because no specialist predicate matched or the top hit's confidence
    # was below threshold). All three fields are optional; absence means
    # this is a normal request, not a fallback.
    fallback_reason = request.get("fallback_reason") or ""
    fallback_score = request.get("fallback_score")
    rejected_verb_iri = request.get("rejected_verb_iri") or ""

    # Extract the injected token from the proxy and set it into ContextVar
    auth_header = request.get("user_jwt")
    if auth_header:
        current_user_token.set(auth_header)

    trace_id = request.get("trace_id")
    if trace_id:
        current_trace_id.set(trace_id)

    # Step 1: Resolve semantic context via Engine O (durable HTTP call)
    semantic_ctx = await ctx.run(
        "resolve_ontology",
        lambda: _resolve_ontology(task.task_description),
    )

    # --------------------------------------------------------------------------
    # Acquire the shared mem0 Memory singleton (built once per pod, off-loop).
    # The Mem0CompatibleWeaviate adapter, the embedder selection, and the
    # Memory.from_config() call all live at module scope now — see
    # get_mem0_memory() / _build_mem0_memory() above. The first request pays
    # a ~5-30s cold-start cost on a worker thread; the event loop stays free
    # so /health remains responsive and readiness stays green.
    try:
        m = await get_mem0_memory()

        from smolagents import tool

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            # Wrap user_id in the filters dictionary per the new mem0 API
            results = m.search(query=query, filters={"user_id": user_id})
            safe_update_observation(input_data=query, output_data=results)
            return results

        task_domain = request.get("domain", "ALL")

        @tool
        def search_datahub(query: str, entity_type: str = None) -> str:
            """
            Searches the DataHub metadata catalog.
            
            Args:
                query: CRITICAL - You MUST extract 1-3 concise keywords (e.g. 'RSO Superset'). DO NOT pass full sentences.
                entity_type: The specific entity to search. You MUST choose a value from the 'Valid DataHub Entity Types' list provided in your system prompt. Do NOT use '*'.
            """
            import requests
            import os
            DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://datahub-wrapper-svc.default.svc.cluster.local:8085")
            try:
                payload = {"user_query": query, "persona": "DATA_STEWARD", "domain": task_domain}
                if entity_type:
                    payload["entity_type"] = entity_type
                resp = requests.post(
                    f"{DATAHUB_WRAPPER_URL}/query_metadata",
                    json=payload,
                    timeout=15.0
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", {}).get("short_answer", "No results found.")
            except Exception as e:
                return f"Error executing DataHub search via Engine D: {str(e)}"

        @tool
        def superset_analytics_manager(
            action: str,
            sql_query: str,
            chart_title: str = "AI Generated Insights",
            viz_type: str = "dist_bar",
            database_id: int = 1
        ) -> str:
            """
            Manages headless analytics via Apache Superset. 
            Use 'preview' to run SQL and get data for a UI chart. 
            Use 'publish' to save the query as a permanent Superset Dashboard Chart.

            Args:
                action: 'preview' to get raw data, or 'publish' to save to Superset.
                sql_query: The validated SQL query to execute.
                chart_title: The name for the published chart.
                viz_type: Superset viz type (e.g., 'dist_bar', 'line', 'pie', 'area').
                database_id: The ID of the Superset database connection.
            """
            import os
            import json
            import requests
            import time

            SUPERSET_URL = os.getenv("SUPERSET_URL", "http://superset:8088")
            # In your environment, the Agent uses a pre-configured JWT or Admin creds
            headers = {
                "Authorization": f"Bearer {os.getenv('SUPERSET_ACCESS_TOKEN')}",
                "Content-Type": "application/json"
            }

            if action == "preview":
                # 1. Execute via SQL Lab API to get raw data for the Cortex UI preview
                payload = {
                    "database_id": database_id,
                    "sql": sql_query,
                    "run_async": False
                }
                resp = requests.post(f"{SUPERSET_URL}/api/v1/sqllab/execute/", json=payload, headers=headers)
                if resp.status_code != 200:
                    return f"Preview failed: {resp.text}"
                
                data = resp.json().get("data", [])
                return json.dumps(data)

            elif action == "publish":
                # 2. Register the Virtual Dataset
                ds_payload = {"database": database_id, "table_name": f"tmp_{int(time.time())}", "sql": sql_query}
                ds_resp = requests.post(f"{SUPERSET_URL}/api/v1/dataset/", json=ds_payload, headers=headers)
                if ds_resp.status_code != 201:
                    return f"Dataset creation failed: {ds_resp.text}"
                dataset_id = ds_resp.json().get("id")

                # 3. Create the Chart (Slice)
                chart_payload = {
                    "slice_name": chart_title,
                    "viz_type": viz_type,
                    "datasource_id": dataset_id,
                    "datasource_type": "table",
                    "params": json.dumps({"metrics": ["count"], "groupby": []})
                }
                chart_resp = requests.post(f"{SUPERSET_URL}/api/v1/chart/", json=chart_payload, headers=headers)
                if chart_resp.status_code != 201:
                    return f"Chart publication failed: {chart_resp.text}"
                
                chart_id = chart_resp.json().get("id")
                return f"PUBLISHED: Chart ID {chart_id}. URL: {SUPERSET_URL}/explore/?slice_id={chart_id}"

            return "Invalid action. Use 'preview' or 'publish'."

        @safe_observe(name="smolagents_restate_execution")
        @safe_observe(name="smolagents_analyst_execution")
        async def run_smolagent() -> tuple[str, str, float]:
            try:
                resolved_uri = semantic_ctx.get("resolved_uri", "unknown")
                confidence = semantic_ctx.get("confidence_score", 0.0)

                # 🚀 JIT TOOL INJECTION: Fetch tools from Engine D based on resolved_uri
                from orchestrator.discovery import fetch_tools_by_uri, DynamicMeshTool, bind_mcp_server
                raw_tools = await fetch_tools_by_uri(resolved_uri)
                
                jit_tools = []
                for t in raw_tools:
                    try:
                        if t.get("type") == "MCPServer":
                            mcp_proxies = await bind_mcp_server(t)
                            jit_tools.extend(mcp_proxies)
                        else:
                            jit_tools.append(DynamicMeshTool(t))
                    except Exception as te:
                        logger.warning(f"Failed to bind JIT tool {t.get('urn')}: {te}")

                # Base system tools
                base_tools = [search_datahub, superset_analytics_manager]
                all_tools = base_tools + jit_tools
                
                logger.info(f"JIT Execution: Bound {len(jit_tools)} dynamic tools for URI {resolved_uri}")

                # ADR-0008 fallback preamble: when this engine is acting as
                # the generalist fallback (registry coverage gap or
                # low-confidence specialist match), tell the agent that
                # explicitly so its tone calibrates to uncertainty rather
                # than presenting as authoritative.
                fallback_preamble = ""
                if fallback_reason == "no_predicate_matched":
                    fallback_preamble = (
                        "ROUTING CONTEXT: You are operating as the GENERALIST "
                        "FALLBACK. The mesh's predicate registry has no "
                        "specialized engine for this request. Do your best "
                        "with the general-purpose tools below, and where the "
                        "answer is uncertain say so explicitly. Do not "
                        "present generalist judgment as specialist authority.\n\n"
                    )
                elif fallback_reason == "low_confidence":
                    fallback_preamble = (
                        f"ROUTING CONTEXT: You are operating as the GENERALIST "
                        f"FALLBACK. A specialist predicate did match this "
                        f"request ({rejected_verb_iri or 'unknown'}) but its "
                        f"confidence score ({fallback_score}) was below the "
                        f"threshold for confident routing. Do your best with "
                        f"the general-purpose tools below; where the answer "
                        f"is uncertain say so. Do not present generalist "
                        f"judgment as specialist authority.\n\n"
                    )

                agent_prompt = (
                    f"{fallback_preamble}"
                    f"You are an enterprise data analyst operating across all domains (Maintenance, Manufacturing, Sustainment, etc.). Your ONLY source of truth is the output of the `search_datahub` tool.\n\n"
                    f"Task: {task.task_description}\n"
                    f"Dataset ID: {task.dataset_id}\n\n"
                    f"Semantic Context (from IOF/MIMOSA ontology):\n"
                    f"  Resolved URI: {resolved_uri}\n"
                    f"  Confidence: {confidence}\n\n"
                    f"CRITICAL GROUNDING RULE: You must NEVER invent, guess, or extrapolate descriptions, business purposes, or metrics. If the tool returns an empty description or UNAVAILABLE_IN_CATALOG, you must state 'Not provided in DataHub'. Any hallucination of metadata is a critical failure.\n\n"
                )

                if dynamic_schema_map:
                    agent_prompt += f"{dynamic_schema_map}\n\n"

                agent_prompt += (
                    f"If you see a request for a 'chart' or 'visualization', you should:\n"
                    f"First, call superset_analytics_manager with action='preview'.\n"
                    f"Include the returned JSON in your final response so the UI Router can build the ChartUI object.\n\n"
                    f"You MUST return your final answer as a Python dictionary matching this Pydantic schema:\n"
                    f"class AgentFinalResponse(BaseModel):\n"
                    f"    status: str\n"
                    f"    summary_text: str = Field(description=\"A conversational summary. STRICT RULE: You must ONLY state facts returned by the DataHub tool. DO NOT guess business purposes.\")\n"
                    f"    structured_data: Optional[Dict[str, Any]] = Field(description=\"MUST be a raw JSON object. STRICT RULE: If a dashboard description is missing, UNAVAILABLE_IN_CATALOG, or empty, you MUST write 'No description available'. Do not infer or invent descriptions. DO NOT stringify this.\")\n\n"
                    f"Pass this dictionary to the final_answer() tool."
                )

                if user_id:
                    # Bridge to a worker thread — m.search() is sync gRPC and
                    # must not block the asyncio loop.
                    past_memories_response = await asyncio.to_thread(
                        fetch_user_memory, task.task_description, user_id
                    )

                    if isinstance(past_memories_response, dict):
                        past_memories = past_memories_response.get("results", [])
                    else:
                        past_memories = past_memories_response
                        
                    if past_memories:
                        memory_strings = "\n".join([f"- {mem.get('memory', mem.get('text', ''))}" for mem in past_memories if isinstance(mem, dict)])
                        prompt_extension = f"\n\n### Relevant Past Experience\n{memory_strings}"
                        agent_prompt += prompt_extension

                syntax_reminder = """
CRITICAL SYNTAX REQUIREMENT:
You are a Code Agent. You MUST wrap ALL of your Python code strictly inside <code> and </code> tags.
DO NOT put your thoughts, explanations, or Markdown text inside the <code> tags. Only valid Python code belongs inside the tags.

Example of BAD formatting:
<code>
I will now search the database.
result = search("query")
</code>

Example of GOOD formatting:
I will now search the database.
<code>
result = search("query")
print(result)
</code>
"""
                agent_prompt += f"\n\n{syntax_reminder}"

                model = get_smolagent_model()
                
                trace_id = current_trace_id.get()
                if trace_id:
                    os.environ["LANGFUSE_TRACE_ID"] = trace_id
                    try:
                        from langfuse.decorators import langfuse_context
                        langfuse_context.update_current_trace(id=trace_id)
                    except Exception:
                        pass
                
                agent = CodeAgent(tools=all_tools, model=model)
                
                result = await asyncio.to_thread(agent.run, agent_prompt)

                formatted_trace = "--- Agent Execution Trace ---\n"
                if hasattr(agent, 'logs'):
                    for log_entry in agent.logs:
                        if isinstance(log_entry, dict):
                            formatted_trace += f"Step: {log_entry.get('step', 'N/A')}\n"
                            if 'thought' in log_entry:
                                formatted_trace += f"Thought: {log_entry['thought']}\n"
                            if 'tool_call' in log_entry:
                                formatted_trace += f"Action: {log_entry['tool_call']}\n"
                            if 'tool_result' in log_entry:
                                formatted_trace += f"Result: {log_entry['tool_result']}\n"
                        else:
                            formatted_trace += f"Step: {getattr(log_entry, 'step', 'N/A')}\n"
                            if hasattr(log_entry, 'thought') and getattr(log_entry, 'thought'):
                                formatted_trace += f"Thought: {getattr(log_entry, 'thought')}\n"
                            if hasattr(log_entry, 'tool_call') and getattr(log_entry, 'tool_call'):
                                formatted_trace += f"Action: {getattr(log_entry, 'tool_call')}\n"
                            if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                                formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                        formatted_trace += "-" * 40 + "\n"

                return result, formatted_trace, confidence
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"ERROR in run_smolagent: {error_trace}")
                raise e

        raw_agent_response, execution_trace, conf = await ctx.run("run-smolagent", run_smolagent)

        summary_text = str(raw_agent_response)
        structured_data_str = None
        
        if isinstance(raw_agent_response, dict):
            summary_text = raw_agent_response.get("summary_text", str(raw_agent_response))
            structured_data = raw_agent_response.get("structured_data")
            if structured_data is not None:
                structured_data_str = json.dumps(structured_data)

        async def save_memory() -> str:
            if user_id:
                # Bridge to a worker thread — m.add() is sync gRPC and must
                # not block the asyncio loop.
                await asyncio.to_thread(
                    m.add,
                    messages=[
                        {"role": "user", "content": task.task_description},
                        {"role": "assistant", "content": summary_text}
                    ],
                    user_id=user_id
                )
            return "saved"
        
        await ctx.run("save-memory", save_memory)

        agent_result = {
            "status": AgentStatus.SUCCESS.value,
            "summary": summary_text,
            "structured_data": structured_data_str,
            "extracted_metrics": {
                "ontology_confidence": conf,
            },
            "execution_trace": execution_trace,
        }

        response = AgentResponse(**agent_result)
        return response.model_dump()
    except Exception as e:
        print(f"[restate-analyst] Fatal error during agent execution: {e}")
        raise e
    # Note: We do NOT close the global client here


# ---------------------------------------------------------------------------
# Restate Workflow — BPMNWorkflowRunner
# ---------------------------------------------------------------------------
bpmn_workflow = Workflow("BPMNWorkflowRunner")


def _execute_service_task(task: dict) -> dict:
    """Execute a BPMN ServiceTask by POSTing to the agent endpoint.

    This function runs inside ``ctx.run()`` for durable execution — if the
    pod crashes mid-flight, Restate replays and skips this step if it
    already completed.
    """
    agent_endpoint = task["agent_endpoint"]
    payload = {
        "task_description": task.get("name", task["id"]),
        "task_id": task["id"],
        "task_type": "service_task",
    }
    resp = requests.post(agent_endpoint, json=payload, timeout=AGENT_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


@bpmn_workflow.main()
async def run(ctx: WorkflowContext, request: dict) -> dict:
    """Process a list of BPMN tasks sequentially with durable execution.

    For each task in the workflow:

    - **ServiceTask**: Executes immediately via ``ctx.run()`` — the HTTP
      POST to the agent endpoint is replay-safe.
    - **UserTask**: Pauses durably via ``ctx.promise().value()``.  The
      workflow suspends at zero infrastructure cost until a human calls
      the ``approve`` handler to resolve the promise.  Crash-proof:
      if the cluster loses power, Restate reads the journal on restart
      and goes right back to waiting.

    Args:
        ctx: Restate workflow context (provides run, promise, etc.).
        request: Dict with keys:
            - ``workflow_id`` (str)
            - ``tasks`` (list[dict]): Each dict has id, name, type,
              agent_endpoint.

    Returns:
        A dict with the workflow_id, overall status, and per-task results.
    """
    workflow_id = request["workflow_id"]
    tasks = request.get("tasks", [])
    results: list[dict] = []

    for task in tasks:
        task_id = task["id"]
        task_type = task.get("type", "service_task")
        task_name = task.get("name", task_id)

        if task_type == "service_task":
            # ---- Durable HTTP call — replay-safe ----
            result = await ctx.run(
                f"exec_{task_id}",
                lambda t=task: _execute_service_task(t),
            )
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": result.get("status", "SUCCESS"),
                "result": result,
            })

        elif task_type == "user_task":
            # ---- Durable promise — zero-cost waiting ----
            # The workflow suspends here indefinitely.  No polling, no
            # CPU, no memory.  Restate holds a few bytes of journal
            # state until a human resolves the promise.
            promise_name = f"approval_{task_id}"
            approval = await ctx.promise(promise_name, type_hint=dict).value()
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": approval.get("status", "APPROVED"),
                "approval": approval,
            })

        else:
            # Unknown task type — skip with warning
            results.append({
                "task_id": task_id,
                "task_name": task_name,
                "task_type": task_type,
                "status": "SKIPPED",
                "reason": f"Unknown task type: {task_type}",
            })

    return {
        "workflow_id": workflow_id,
        "status": "COMPLETED",
        "task_results": results,
    }


@bpmn_workflow.handler()
async def approve(ctx: WorkflowSharedContext, request: dict) -> dict:
    """Resolve a durable promise to wake up a paused UserTask.

    Called by the FastAPI ``/workflow/{wf}/task/{tid}/approve`` endpoint.
    This resolves the promise that the ``run`` handler is awaiting,
    causing the workflow to resume execution from exactly where it
    left off.

    Args:
        ctx: Restate shared workflow context.
        request: Dict with keys:
            - ``task_id`` (str): The BPMN task to approve.
            - ``status`` (str): e.g. "APPROVED" or "REJECTED".
            - ``comments`` (str): Optional human comments.

    Returns:
        Confirmation dict.
    """
    task_id = request["task_id"]
    promise_name = f"approval_{task_id}"

    approval_payload = {
        "status": request.get("status", "APPROVED"),
        "comments": request.get("comments", ""),
        "task_id": task_id,
    }

    await ctx.promise(promise_name, type_hint=dict).resolve(approval_payload)

    return {
        "message": f"Promise '{promise_name}' resolved — workflow will resume",
        "task_id": task_id,
        "status": approval_payload["status"],
    }


# ---------------------------------------------------------------------------
# Restate Service — ProcessInterviewer (VirtualObject for durable local state)
# ---------------------------------------------------------------------------
process_interviewer_service = VirtualObject("ProcessInterviewer")

@process_interviewer_service.handler()
async def process_message(ctx: ObjectContext, request: dict) -> dict:
    thread_id = ctx.key()  # Use the key as the thread_id since it is a VirtualObject
    user_msg = request.get("user_query", "")
    bootstrap_context = request.get("bootstrap_context", "")
    
    history_key = f"history_{thread_id}"
    graph_key = f"graph_{thread_id}"
    
    chat_history = await ctx.get(history_key) or ""
    current_graph_dict = await ctx.get(graph_key) or {"nodes": [], "edges": []}
    current_graph_json = json.dumps(current_graph_dict) if isinstance(current_graph_dict, dict) else current_graph_dict

    # 1. Initialize Bootstrap Context on the first turn
    if not chat_history and bootstrap_context:
        chat_history = f"SYSTEM: Use the following baseline data extracted from the Graph Database to help draft the initial process:\n{bootstrap_context}\n\n"
    # 2. Fetch Live Ontologies and Data Catalogs
    async def fetch_catalogs():
        import httpx
        ontologies = "- (No live ontology data available)"
        data_sources = "- (No live data sources available)"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Engine O: Ontology Service
            try:
                _ONTOLOGY_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://ontology-service:8084")
                resp = await client.get(f"{_ONTOLOGY_URL}/classes")
                if resp.status_code == 200:
                    classes = resp.json().get("classes", [])
                    ont_lines = [f"- {c.get('uri')}  ({c.get('label')})" for c in classes]
                    if ont_lines:
                        ontologies = "\n".join(ont_lines)
            except Exception:
                pass # Fallback to default
                
            # Engine D: DataHub Wrapper (Dynamic search enabled)
            data_sources = "- dbt_model: (Metadata discovered dynamically during execution via /query_metadata)"
                
        return {
            "ontologies": ontologies, 
            "data_sources": data_sources
        }
        
    catalog_data = await ctx.run("fetch_catalogs", fetch_catalogs)
    ontologies = catalog_data["ontologies"]
    data_sources = catalog_data["data_sources"]
    
    # 3. Call the Socratic BAML Compiler (Must return model_dump)
    async def call_baml_interview():
        state = await b.IterateBPMNGraph(
            chat_history=chat_history,
            user_message=user_msg,
            current_graph_json=current_graph_json,
            available_ontology_classes=ontologies,
            available_data_sources=data_sources
        )
        return state.model_dump() # 🟢 CRITICAL: Serialize Pydantic to Dict for Restate

    state_dict = await ctx.run("baml_interview", call_baml_interview)
    
    # 4. Extract variables from the dictionary safely
    is_complete = state_dict.get("is_ready_to_compile", False)
    agent_reply = state_dict.get("agent_reply", "")
    
    new_history = chat_history + f"\nUser: {user_msg}\nAgent: {agent_reply}"
    ctx.set(history_key, new_history)
    
    # 5. Format the UI Payload securely
    ui_nodes = []
    for n in state_dict.get("nodes", []):
        n_type = n["node_type"] if isinstance(n["node_type"], str) else str(n["node_type"])
        ui_nodes.append({
            "id": n["id"], 
            "name": n["name"], 
            "type": n_type, 
            "description": f"Ontology: {n.get('ontology_class')} | Data: {n.get('data_source')}"
        })
        
    ui_edges = [{"source": e["source_id"], "target": e["target_id"], "label": e.get("condition_expression", "")} for e in state_dict.get("edges", [])]
    
    new_graph_dict = {"nodes": ui_nodes, "edges": ui_edges}
    ctx.set(graph_key, new_graph_dict)
    
    return {
        "is_complete": is_complete,
        "chat_reply": agent_reply,
        "raw_bpmn_payload": {"tasks": ui_nodes, "gateways": [], "sequence_flows": ui_edges}, # Passed back for the compiler
        "ui_payload": {
            "components": [
                {
                    "archetype": "PROCESS_TOPOLOGY",
                    "subject_concept": "Live BPMN Draft",
                    "nodes": ui_nodes,
                    "edges": ui_edges
                }
            ]
        }
    }

@process_interviewer_service.handler()
async def get_status(ctx: ObjectContext, request: dict) -> dict:
    thread_id = ctx.key()
    history_key = f"history_{thread_id}"
    chat_history = await ctx.get(history_key) or []
    # An interview is active if there are messages and it hasn't concluded with the Graph payload
    is_active = len(chat_history) > 0 and chat_history[-1] != "[Process Graph Generated]"
    return {"is_active": is_active}


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger("RestateAnalyst")

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP; the helper
# logs a clear "skipping" message when disabled or when DataHub creds are
# missing, and never crashes the engine. Engine A is the first hardcoded
# engine to register; the others (E, DA, W, etc.) follow the same call
# pattern when D.1 propagates.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Boot Sequence
    logger.info("Initializing Engine A: Late Binding enabled (JIT Tool Injection).")

    # Register as a typed predicate edge in the mesh routing graph.
    #
    # Engine A operates on a generic (mesh:AgentTask) and produces a generic
    # (mesh:AgentResponse). The verb mesh:analyzeWithCodeAgent names what
    # it does: run a smolagents CodeAgent loop. See docs/adr/minted-concepts.md
    # for the survey-before-mint record per ADR-0007.
    register_engine_to_mesh(
        name="engine_a_restate_analyst",
        description=(
            "Durable analyst engine. Runs a smolagents CodeAgent loop with "
            "Restate-backed exactly-once execution; calls Engine O for "
            "semantic resolution + DataHub / Superset tools as needed."
        ),
        verb="mesh:analyzeWithCodeAgent",
        input_uri="mesh:AgentTask",
        output_uri="mesh:AgentResponse",
        verb_synonyms=[
            "analyze", "investigate", "investigate data",
            "code agent analysis", "smolagents loop",
        ],
        endpoint_url=os.getenv(
            "ENGINE_A_PUBLIC_URL",
            "http://restate-agent-svc.default.svc.cluster.local:8081/analyze",
        ),
        owner_persona="DATA_STEWARD",
        # Per ADR-0009: Engine A is the default fallback analyst for
        # general-purpose work; it serves all non-specialized domains.
        domains=["MAINTENANCE", "MANUFACTURING", "SUSTAINMENT"],
        cost_class="slow",  # smolagents loops are not cheap
    )

    yield

    # Teardown Sequence
    logger.info("Shutting down Engine A...")

app = FastAPI(
    title="Engine A — Restate Analyst",
    description=(
        "Durable analyst agent powered by Restate + HuggingFace Smolagents. "
        "Resolves ontology context via Engine O before analysis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Restate Virtual Object — DagsterRunTracker
# ---------------------------------------------------------------------------
# Lives in a sibling module so its handler logic can be unit-tested without
# importing the rest of this file (which pulls in smolagents / baml_client).
# Try/except needed because the container Dockerfile flattens this directory
# into /app/ (so the sibling is at /app/dagster_run_tracker.py without the
# `agent_fleet.restate_analyst.` prefix), while dev runs import via the
# full package path.
try:
    from dagster_run_tracker import run_tracker  # noqa: E402  — container path
except ImportError:
    from agent_fleet.restate_analyst.dagster_run_tracker import (  # noqa: E402
        run_tracker,
    )

# Mount the Restate SDK so it handles /restate/* routes
app.mount("/restate", restate.app(services=[analyst_service, bpmn_workflow, process_interviewer_service, run_tracker]))


# ---------------------------------------------------------------------------
# Request model for the proxy endpoint
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    """Proxy request model — mirrors AgentTask."""
    task_description: str
    dataset_id: str
    semantic_context: dict | None = None


# ---------------------------------------------------------------------------
# POST /analyze — proxy route for Dagster
# ---------------------------------------------------------------------------
@app.post("/analyze")
async def analyze_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate AnalystService.

    Dagster (and other external callers) POST to ``/analyze`` with an
    ``AgentTask`` JSON body. This route forwards the payload to the Restate Ingress
    at /{ServiceName}/{MethodName} for durable execution.
    """
    try:
        payload = await request.json()
        
        # Inject the incoming request Authorization into the Restate payload
        auth_header = request.headers.get("Authorization")
        if auth_header:
            payload["user_jwt"] = auth_header
            
        import uuid
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        payload["trace_id"] = trace_id
            
        target_url = f"{RESTATE_INGRESS_URL}/AnalystService/analyze"

        # Match the supervisor's per-engine call timeout (900s). The Engine A
        # smolagent loop can take many minutes per multi-step reasoning task
        # on slow Ollama backends; 300s reliably timed out mid-loop and
        # surfaced as a 502 to the supervisor.
        async with httpx.AsyncClient(timeout=900.0) as client:
            resp = await client.post(
                target_url,
                json=payload,
            )
            # Bubble up the exact response and status code from Restate
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.text else {}
            )
    except Exception as exc:
        print(f"DEBUG: Restate proxy call failed for AnalystService: {exc}")
        return JSONResponse(
            content={
                "status": AgentStatus.FAILED.value,
                "summary": f"Restate proxy call failed: {exc}",
                "extracted_metrics": {},
            },
            status_code=502,
        )


# ---------------------------------------------------------------------------
# BPMN Workflow request models
# ---------------------------------------------------------------------------
class WorkflowStartRequest(BaseModel):
    """Request to start a BPMN workflow run."""
    workflow_id: str
    tasks: list[dict]


class ApprovalRequest(BaseModel):
    """Request to approve (or reject) a paused UserTask."""
    status: str = "APPROVED"
    comments: str = ""


# ---------------------------------------------------------------------------
# POST /workflow/start — kick off a BPMN workflow
# ---------------------------------------------------------------------------
@app.post("/workflow/start")
async def start_workflow(req: WorkflowStartRequest) -> JSONResponse:
    """Start a new BPMN workflow execution via Restate.

    Sends the task list to the BPMNWorkflowRunner's ``run`` handler.
    The workflow_id is used as the Restate workflow key.
    """
    try:
        resp = requests.post(
            f"{RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{req.workflow_id}/run",
            json={"workflow_id": req.workflow_id, "tasks": req.tasks},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return JSONResponse(
            content={"message": f"Workflow '{req.workflow_id}' started", "workflow_id": req.workflow_id},
            status_code=202,
        )
    except requests.RequestException as exc:
        return JSONResponse(
            content={"error": f"Failed to start workflow: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# POST /workflow/{workflow_id}/task/{task_id}/approve — resolve a UserTask
# ---------------------------------------------------------------------------
@app.post("/workflow/{workflow_id}/task/{task_id}/approve")
async def approve_task(
    workflow_id: str,
    task_id: str,
    req: ApprovalRequest,
) -> JSONResponse:
    """Approve (or reject) a paused BPMN UserTask.

    This endpoint calls the BPMNWorkflowRunner's ``approve`` handler
    via the Restate HTTP ingress.  The handler resolves the durable
    promise that the ``run`` handler is awaiting, causing the workflow
    to resume execution from exactly where it left off.

    Zero-cost waiting: the workflow consumes no compute while paused.
    Crash-proof: Restate replays from its journal on restart.
    """
    try:
        resp = requests.post(
            f"{RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{workflow_id}/approve",
            json={
                "task_id": task_id,
                "status": req.status,
                "comments": req.comments,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return JSONResponse(
            content={
                "message": f"Task '{task_id}' in workflow '{workflow_id}' approved",
                "workflow_id": workflow_id,
                "task_id": task_id,
                "status": req.status,
            },
            status_code=200,
        )
    except requests.RequestException as exc:
        return JSONResponse(
            content={"error": f"Failed to approve task: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok", "engine": "restate_analyst"}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
