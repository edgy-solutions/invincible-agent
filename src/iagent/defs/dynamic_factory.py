"""Dynamic BPMN Factory — reads BPMN payloads from Postgres and generates Dagster jobs/ops.

This module implements the Imperative-Declarative Hybrid Pattern:
- Ops handle BPMN control flow (imperative).
- Ops yield AssetMaterialization events to preserve data lineage (declarative).

Phase 1: Database fetcher — connects to Postgres and retrieves active BPMN models
from the ``bpmn_catalog`` table.

Phase 2: Dynamic Op Factory — ``create_agent_op(task_node)`` generates a Dagster
``@op`` at runtime for each BPMN task node.  The generated op POSTs to the
agent endpoint, yields an ``AssetMaterialization`` for lineage tracking, and
yields the HTTP response ``Output`` for downstream ops.

Phase 3: Graph Builder — ``build_dynamic_jobs()`` iterates over active BPMN
models, instantiates ops, resolves sequence flows (including through gateways),
and assembles them into Dagster ``@job`` definitions via ``GraphDefinition``.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import psycopg2
import requests
from dagster import (
    AssetMaterialization,
    DependencyDefinition,
    Definitions,
    GraphDefinition,
    In,
    JobDefinition,
    MetadataValue,
    OpExecutionContext,
    Out,
    Output,
    get_dagster_logger,
    op,
)


# ---------------------------------------------------------------------------
# Configuration — Postgres connection from environment variables
# ---------------------------------------------------------------------------
BPMN_POSTGRES_HOST = os.getenv("BPMN_POSTGRES_HOST", "localhost")
BPMN_POSTGRES_PORT = os.getenv("BPMN_POSTGRES_PORT", "5432")
BPMN_POSTGRES_DB = os.getenv("BPMN_POSTGRES_DB", "iagent")
BPMN_POSTGRES_USER = os.getenv("BPMN_POSTGRES_USER", "iagent")
BPMN_POSTGRES_PASSWORD = os.getenv("BPMN_POSTGRES_PASSWORD", "iagent")

# Default HTTP timeout for agent calls (seconds)
AGENT_HTTP_TIMEOUT = int(os.getenv("AGENT_HTTP_TIMEOUT", "300"))


def _get_connection() -> psycopg2.extensions.connection:
    """Create a Postgres connection using environment variables."""
    return psycopg2.connect(
        host=BPMN_POSTGRES_HOST,
        port=BPMN_POSTGRES_PORT,
        dbname=BPMN_POSTGRES_DB,
        user=BPMN_POSTGRES_USER,
        password=BPMN_POSTGRES_PASSWORD,
    )


# ---------------------------------------------------------------------------
# Phase 1: Database fetcher
# ---------------------------------------------------------------------------


def fetch_active_bpmn_models() -> list[dict[str, Any]]:
    """Query Postgres for all active BPMN workflow definitions.

    Returns:
        A list of dicts, each containing:
        - workflow_id (str): Unique identifier for the workflow.
        - name (str): Human-readable workflow name.
        - bpmn_payload (dict): The BPMN JSON payload describing the workflow.
    """
    logger = get_dagster_logger()

    try:
        conn = _get_connection()
    except psycopg2.Error as exc:
        logger.warning(f"BPMN catalog: Postgres unreachable — {exc}")
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workflow_id, name, bpmn_payload "
                "FROM bpmn_catalog "
                "WHERE is_active = TRUE;"
            )
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        logger.warning(f"BPMN catalog: query failed — {exc}")
        return []
    finally:
        conn.close()

    models = [dict(zip(columns, row)) for row in rows]
    logger.info(f"BPMN catalog: fetched {len(models)} active workflow(s)")
    return models


# ---------------------------------------------------------------------------
# Phase 2: Dynamic Op Factory
# ---------------------------------------------------------------------------


def _evaluate_condition(
    condition_expression: str | None,
    result: dict[str, Any],
) -> bool:
    """Safely evaluate a BPMN condition expression against an HTTP response.

    The ``condition_expression`` is a simple Python-like expression from the
    BPMN sequence flow (e.g. ``"status == 'approved'"``).  It is evaluated
    with the HTTP response dict's keys exposed as local variables.

    Args:
        condition_expression: The expression string, or ``None`` / empty
            string for an unconditional (default) branch.
        result: The parsed JSON response from the agent HTTP call.

    Returns:
        ``True`` if the condition matches (or is empty/None), ``False``
        otherwise.  Returns ``True`` on evaluation errors so the pipeline
        does not silently swallow branches.
    """
    if not condition_expression:
        return True  # Unconditional / default branch

    try:
        # Expose only the result keys — no builtins, no dunder access
        safe_ns: dict[str, Any] = {k: v for k, v in result.items()}
        return bool(eval(condition_expression, {"__builtins__": {}}, safe_ns))  # noqa: S307
    except Exception:
        # If evaluation fails, treat as matching so the branch is not
        # silently dropped.  The op will log this.
        return True


# ---- Gateway branch descriptor -----------------------------------------

class _GatewayBranch:
    """Describes a single outgoing branch from an exclusive gateway."""

    __slots__ = ("branch_name", "target_task_id", "condition_expression")

    def __init__(
        self,
        branch_name: str,
        target_task_id: str,
        condition_expression: str | None,
    ) -> None:
        self.branch_name = branch_name
        self.target_task_id = target_task_id
        self.condition_expression = condition_expression

    def __repr__(self) -> str:
        return (
            f"_GatewayBranch({self.branch_name!r}, "
            f"target={self.target_task_id!r}, "
            f"cond={self.condition_expression!r})"
        )


def build_gateway_routing(
    sequence_flows: list[dict[str, Any]],
    task_ids: set[str],
    gateway_map: dict[str, dict[str, Any]],
) -> dict[str, list[_GatewayBranch]]:
    """Analyze BPMN topology to identify tasks that precede exclusive gateways.

    For each task that feeds into an exclusive gateway, returns a list of
    ``_GatewayBranch`` objects describing the downstream branches.

    Args:
        sequence_flows: Raw ``sequence_flows`` from the BPMN payload.
        task_ids: Set of all task element IDs.
        gateway_map: Dict of ``{gateway_id: gateway_dict}`` for lookups.

    Returns:
        A dict keyed by the upstream task ID.  The value is a list of
        ``_GatewayBranch`` objects — one per outgoing branch from the
        exclusive gateway that the task feeds into.  Tasks that do NOT
        feed into gateways are absent from the returned dict.
    """
    # Build quick lookups ------------------------------------------------
    # flows_from[node_id] → list of flow dicts leaving that node
    flows_from: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for flow in sequence_flows:
        flows_from[flow["source_ref"]].append(flow)

    # tasks_feeding_gateways[gateway_id] → list of upstream task IDs
    tasks_feeding_gw: dict[str, list[str]] = defaultdict(list)
    for flow in sequence_flows:
        if flow["source_ref"] in task_ids and flow["target_ref"] in gateway_map:
            tasks_feeding_gw[flow["target_ref"]].append(flow["source_ref"])

    # Build branch descriptors ------------------------------------------
    routing: dict[str, list[_GatewayBranch]] = {}

    for gw_id, upstream_tasks in tasks_feeding_gw.items():
        gw = gateway_map[gw_id]
        if gw.get("type") != "exclusive":
            continue  # Only exclusive gateways need multi-output routing

        # Collect outgoing flows from this gateway
        branches: list[_GatewayBranch] = []
        for out_flow in flows_from.get(gw_id, []):
            target = out_flow["target_ref"]
            # Trace through chained gateways to find final task targets
            final_targets = _trace_to_final_tasks(
                target, task_ids, set(gateway_map.keys()), flows_from,
            )
            for final_task_id in final_targets:
                branches.append(
                    _GatewayBranch(
                        branch_name=f"branch_{final_task_id}",
                        target_task_id=final_task_id,
                        condition_expression=out_flow.get("condition_expression"),
                    )
                )

        # Assign the same branches to every task that feeds this gateway
        for task_id in upstream_tasks:
            if task_id in routing:
                routing[task_id].extend(branches)
            else:
                routing[task_id] = list(branches)

    return routing


def _trace_to_final_tasks(
    current: str,
    task_ids: set[str],
    gateway_ids: set[str],
    flows_from: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """DFS from a node until we hit task nodes (skipping gateways)."""
    if current in task_ids:
        return [current]
    if current not in gateway_ids:
        return []
    results: list[str] = []
    for flow in flows_from.get(current, []):
        results.extend(
            _trace_to_final_tasks(flow["target_ref"], task_ids, gateway_ids, flows_from)
        )
    return results


# ---- Op factory --------------------------------------------------------


def create_agent_op(
    task_node: dict[str, Any],
    input_names: list[str] | None = None,
    gateway_branches: list[_GatewayBranch] | None = None,
):
    """Dynamically generate a Dagster ``@op`` for a BPMN task node.

    The generated op:

    1. POSTs the task payload to the agent endpoint defined in
       ``task_node["agent_endpoint"]``.
    2. Yields an ``AssetMaterialization`` event so Dagster's lineage
       graph reflects the work done by this task.
    3. Yields the parsed HTTP response as ``Output`` — either to a single
       ``"result"`` output (direct edges) or to the first matching
       gateway branch output (exclusive gateway edges).

    Args:
        task_node: A dict from the BPMN payload's ``tasks`` list.
            Expected keys:
            - ``id`` (str): Unique task identifier (becomes the op name).
            - ``name`` (str): Human-readable task name.
            - ``type`` (str): ``"service_task"`` or ``"user_task"``.
            - ``agent_endpoint`` (str): HTTP URL of the backing agent.
        input_names: Optional list of input slot names.  Each name
            corresponds to an upstream op whose output will be wired
            into this op via ``DependencyDefinition``.
        gateway_branches: Optional list of ``_GatewayBranch`` objects.
            When provided, the op uses **multiple optional outputs**
            (``Out(is_required=False)``) and evaluates each branch's
            ``condition_expression`` at runtime to decide which single
            output to yield.  When ``None``, the op has a single
            required ``"result"`` output.

    Returns:
        A Dagster ``@op``-decorated function.
    """
    task_id: str = task_node["id"]
    task_name: str = task_node["name"]
    task_type: str = task_node.get("type", "service_task")
    agent_endpoint: str = task_node["agent_endpoint"]

    # Build input slots
    ins_config: dict[str, In] = {}
    for in_name in (input_names or []):
        ins_config[in_name] = In(dagster_type=dict)

    # Build output slots — branching vs. simple
    if gateway_branches:
        out_config: dict[str, Out] = {}
        for branch in gateway_branches:
            out_config[branch.branch_name] = Out(
                dict,
                is_required=False,
                description=(
                    f"Branch to {branch.target_task_id} "
                    f"(condition: {branch.condition_expression or 'default'})"
                ),
            )
    else:
        out_config = {
            "result": Out(dict, description="Parsed JSON response from agent"),
        }

    # Capture for closure
    _branches = list(gateway_branches) if gateway_branches else None

    @op(
        name=task_id,
        description=(
            f"BPMN {task_type}: {task_name}\n\n"
            f"Dynamically generated op that POSTs to ``{agent_endpoint}``."
        ),
        ins=ins_config,
        out=out_config,
    )
    def _dynamic_agent_op(context, **kwargs) -> Any:
        """Execute an HTTP POST to the agent endpoint and yield lineage."""
        context.log.info(
            f"[BPMN] Executing task '{task_name}' ({task_id}) "
            f"→ POST {agent_endpoint}"
        )

        if kwargs:
            context.log.info(
                f"[BPMN] Received upstream results from: "
                f"{', '.join(kwargs.keys())}"
            )

        # ----- HTTP call to the agent pod -----
        payload = {
            "task_description": task_name,
            "task_id": task_id,
            "task_type": task_type,
        }

        try:
            resp = requests.post(
                agent_endpoint,
                json=payload,
                timeout=AGENT_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as exc:
            context.log.error(
                f"[BPMN] Task '{task_name}' failed: {exc}"
            )
            result = {
                "status": "FAILED",
                "summary": f"Agent call failed: {exc}",
                "task_id": task_id,
            }

        context.log.info(
            f"[BPMN] Task '{task_name}' completed — "
            f"status: {result.get('status', 'unknown')}"
        )

        # ----- AssetMaterialization for data lineage -----
        yield AssetMaterialization(
            asset_key=task_name,
            description=f"BPMN task '{task_name}' executed via {agent_endpoint}",
            metadata={
                "task_id": MetadataValue.text(task_id),
                "task_type": MetadataValue.text(task_type),
                "agent_endpoint": MetadataValue.url(agent_endpoint),
                "response": MetadataValue.json(result),
            },
        )

        # ----- Route to the correct output -----
        if _branches:
            # Exclusive gateway: evaluate conditions, yield first match
            matched = False
            for branch in _branches:
                if _evaluate_condition(branch.condition_expression, result):
                    context.log.info(
                        f"[BPMN] Gateway routing: '{task_name}' → "
                        f"{branch.branch_name} "
                        f"(condition: {branch.condition_expression or 'default'})"
                    )
                    yield Output(
                        value=result,
                        output_name=branch.branch_name,
                    )
                    matched = True
                    break  # Exclusive = first match wins

            if not matched:
                # Fallback: yield to the first branch so the pipeline
                # doesn't hang.  This handles the "default" case.
                fallback = _branches[0]
                context.log.warning(
                    f"[BPMN] Gateway routing: no condition matched for "
                    f"'{task_name}' — falling back to {fallback.branch_name}"
                )
                yield Output(
                    value=result,
                    output_name=fallback.branch_name,
                )
        else:
            # Direct edge: single required output
            yield Output(value=result, output_name="result")

    return _dynamic_agent_op


# ---------------------------------------------------------------------------
# Phase 3: Graph Builder
# ---------------------------------------------------------------------------


def _resolve_direct_flows(
    sequence_flows: list[dict[str, Any]],
    task_ids: set[str],
    gateway_ids: set[str],
) -> list[tuple[str, str]]:
    """Resolve non-gateway sequence flows into direct task-to-task edges.

    Only returns edges where both source and target are tasks with NO
    gateway in between.  Gateway-routed edges are handled separately
    by ``build_gateway_routing()``.

    Args:
        sequence_flows: Raw ``sequence_flows`` from the BPMN payload.
        task_ids: Set of all task element IDs.
        gateway_ids: Set of all gateway element IDs.

    Returns:
        A list of ``(source_task_id, target_task_id)`` tuples for direct
        (non-gateway) edges only.
    """
    direct: list[tuple[str, str]] = []
    for flow in sequence_flows:
        src = flow["source_ref"]
        tgt = flow["target_ref"]
        if src in task_ids and tgt in task_ids:
            direct.append((src, tgt))
    return direct


def build_dynamic_jobs() -> list[JobDefinition]:
    """Read active BPMN models and build a Dagster job for each one.

    For every active workflow in the ``bpmn_catalog`` table:

    1. Analyze exclusive gateway topology via ``build_gateway_routing()``.
    2. Instantiate dynamic ``@op`` for each BPMN task — tasks preceding
       exclusive gateways get ``Out(is_required=False)`` for each branch.
    3. Resolve direct (non-gateway) flows for simple wiring.
    4. Assemble the ops into a ``GraphDefinition`` with both direct and
       gateway-routed ``DependencyDefinition`` edges.
    5. Convert the graph into a ``JobDefinition`` named after the
       ``workflow_id``.

    Returns:
        A list of ``JobDefinition`` objects ready to be passed to
        ``Definitions(jobs=...)``.
    """
    logger = get_dagster_logger()
    models = fetch_active_bpmn_models()
    jobs: list[JobDefinition] = []

    for model in models:
        workflow_id: str = model["workflow_id"]
        workflow_name: str = model.get("name", workflow_id)
        payload: dict[str, Any] = model["bpmn_payload"]

        tasks = payload.get("tasks", [])
        flows = payload.get("sequence_flows", [])
        gateways = payload.get("gateways", [])

        if not tasks:
            logger.warning(
                f"BPMN '{workflow_name}' ({workflow_id}): "
                f"no tasks found — skipping"
            )
            continue

        task_ids = {t["id"] for t in tasks}
        gateway_map = {gw["id"]: gw for gw in gateways}

        # --- 1. Analyze gateway routing topology ---
        gw_routing = build_gateway_routing(flows, task_ids, gateway_map)

        # --- 2. Resolve direct (non-gateway) task-to-task flows ---
        direct_edges = _resolve_direct_flows(flows, task_ids, set(gateway_map.keys()))

        # --- 3. Build combined input map per task ---
        # For direct edges:  input = in_{source_id}, output = "result"
        # For gateway edges: input = in_{source_id}, output = "branch_{target_id}"
        inputs_per_task: dict[str, list[tuple[str, str]]] = defaultdict(list)
        #   value tuples: (input_slot_name, upstream_task_id, output_name)

        # Direct edges
        for src_id, tgt_id in direct_edges:
            inputs_per_task[tgt_id].append((f"in_{src_id}", src_id, "result"))

        # Gateway-routed edges
        for src_id, branches in gw_routing.items():
            for branch in branches:
                tgt_id = branch.target_task_id
                inputs_per_task[tgt_id].append(
                    (f"in_{src_id}", src_id, branch.branch_name)
                )

        # --- 4. Create ops with correct input slots + gateway branches ---
        ops_dict: dict[str, Any] = {}
        for task in tasks:
            tid = task["id"]
            # Collect unique input slot names for this task
            input_slot_names = [
                entry[0] for entry in inputs_per_task.get(tid, [])
            ]
            ops_dict[tid] = create_agent_op(
                task,
                input_names=input_slot_names,
                gateway_branches=gw_routing.get(tid),
            )

        # --- 5. Wire DependencyDefinition edges ---
        dependencies: dict[str, dict[str, DependencyDefinition]] = {}
        for tgt_id, entries in inputs_per_task.items():
            dep_map: dict[str, DependencyDefinition] = {}
            for input_slot, src_id, output_name in entries:
                dep_map[input_slot] = DependencyDefinition(src_id, output_name)
            dependencies[tgt_id] = dep_map

        # --- 6. Assemble GraphDefinition → JobDefinition ---
        try:
            graph = GraphDefinition(
                name=f"{workflow_id}_graph",
                node_defs=list(ops_dict.values()),
                dependencies=dependencies,
            )
            job = graph.to_job(
                name=workflow_id,
                description=(
                    f"BPMN workflow: {workflow_name}\n\n"
                    f"Dynamically generated from bpmn_catalog. "
                    f"Tasks: {len(tasks)}, Flows: {len(flows)}, "
                    f"Gateways: {len(gateways)}."
                ),
            )
            jobs.append(job)
            logger.info(
                f"BPMN '{workflow_name}': built job '{workflow_id}' "
                f"with {len(tasks)} ops, "
                f"{len(direct_edges)} direct edges, "
                f"{sum(len(b) for b in gw_routing.values())} gateway branches"
            )
        except Exception as exc:
            logger.error(
                f"BPMN '{workflow_name}' ({workflow_id}): "
                f"failed to build job — {exc}"
            )

    logger.info(f"BPMN factory: built {len(jobs)} dynamic job(s)")
    return jobs


# ---------------------------------------------------------------------------
# Dagster Definitions entry point
# ---------------------------------------------------------------------------

dynamic_jobs = build_dynamic_jobs()
defs = Definitions(jobs=dynamic_jobs)



