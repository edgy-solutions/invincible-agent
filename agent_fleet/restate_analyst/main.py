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

import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import os

import requests
import restate
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
    from ..llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        from llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Smolagents imports — only used inside the Restate handler.
# ---------------------------------------------------------------------------
from smolagents import CodeAgent
try:
    from ..llm_utils import get_smolagent_model
except ImportError:
    from llm_utils import get_smolagent_model

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


def _run_smolagent(task_description: str, dataset_id: str, semantic_ctx: dict, dynamic_schema_map: str = "") -> dict:
    """Execute the HuggingFace smolagents CodeAgent with semantic context.

    The agent receives the resolved ontology URI and suggested dbt models
    so it knows exactly which database tables to query.
    """
    suggested_models = semantic_ctx.get("suggested_dbt_models", [])
    resolved_uri = semantic_ctx.get("resolved_uri", "unknown")
    confidence = semantic_ctx.get("confidence_score", 0.0)

    # Build a context-rich prompt for the code agent
    agent_prompt = (
        f"You are a sustainment data analyst. Analyze the following task.\n\n"
        f"Task: {task_description}\n"
        f"Dataset ID: {dataset_id}\n\n"
        f"Semantic Context (from IOF/MIMOSA ontology):\n"
        f"  Resolved URI: {resolved_uri}\n"
        f"  Confidence: {confidence}\n"
        f"  Relevant dbt models / tables: {', '.join(suggested_models)}\n\n"
    )

    if dynamic_schema_map:
        agent_prompt += f"{dynamic_schema_map}\n\n"

    agent_prompt += (
        f"Use ONLY the tables listed above. Produce a brief summary of your "
        f"analysis and any key metrics you extract."
    )

    from smolagents import tool

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
            resp = requests.post(
                f"{DATAHUB_WRAPPER_URL}/query_metadata",
                json={"user_query": query, "persona": "DATA_STEWARD", "domain": "DATA_ENGINEERING"},
                timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("short_answer", "No results found.")
        except Exception as e:
            return f"Error executing DataHub search via Engine D: {str(e)}"

    model = get_smolagent_model()
    agent = CodeAgent(tools=[search_datahub], model=model)
    result = agent.run(agent_prompt)

    # Extract smolagents internal logs (trajectory)
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
                elif hasattr(log_entry, 'action') and getattr(log_entry, 'action'):
                    formatted_trace += f"Action: {getattr(log_entry, 'action')}\n"
                if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                    formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                elif hasattr(log_entry, 'observation') and getattr(log_entry, 'observation'):
                    formatted_trace += f"Result: {getattr(log_entry, 'observation')}\n"
            formatted_trace += "-" * 30 + "\n"

    return {
        "status": AgentStatus.SUCCESS.value,
        "summary": str(result),
        "extracted_metrics": {
            "ontology_confidence": confidence,
        },
        "execution_trace": formatted_trace,
    }


@analyst_service.handler()
async def analyze(ctx: Context, request: dict) -> dict:
    """Durable handler: resolve ontology → run smolagent → return AgentResponse.

    Every side-effectful operation is wrapped in ``ctx.run()`` so Restate
    can guarantee exactly-once execution even across pod restarts.
    """
    # Parse the incoming AgentTask
    task = AgentTask(**request)
    dynamic_schema_map = request.get("dynamic_schema_map", "")

    # Step 1: Resolve semantic context via Engine O (durable HTTP call)
    semantic_ctx = await ctx.run(
        "resolve_ontology",
        lambda: _resolve_ontology(task.task_description),
    )

    # Step 2: Run the smolagents CodeAgent (durable execution)
    agent_result = await ctx.run(
        "run_smolagent",
        lambda: _run_smolagent(
            task_description=task.task_description,
            dataset_id=task.dataset_id,
            semantic_ctx=semantic_ctx,
            dynamic_schema_map=dynamic_schema_map,
        ),
    )

    # Validate against our BAML schema before returning
    response = AgentResponse(**agent_result)
    return response.model_dump()


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
app = FastAPI(
    title="Engine A — Restate Analyst",
    description=(
        "Durable analyst agent powered by Restate + HuggingFace Smolagents. "
        "Resolves ontology context via Engine O before analysis."
    ),
    version="0.1.0",
)

# Mount the Restate SDK so it handles /restate/* routes
app.mount("/restate", restate.app(services=[analyst_service, bpmn_workflow, process_interviewer_service]))


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
import httpx
@app.post("/analyze")
async def analyze_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate AnalystService.

    Dagster (and other external callers) POST to ``/analyze`` with an
    ``AgentTask`` JSON body. This route forwards the payload to the Restate Ingress
    at /{ServiceName}/{MethodName} for durable execution.
    """
    try:
        payload = await request.json()
        target_url = f"{RESTATE_INGRESS_URL}/AnalystService/analyze"
        
        # Use httpx for consistency and better error handling
        async with httpx.AsyncClient(timeout=300.0) as client:
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
