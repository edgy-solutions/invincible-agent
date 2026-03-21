// The Cortex — Stateful BPMN Socratic Interview Contract
// The LLM iteratively builds a BPMN graph on each chat turn.
// ServiceTasks are semantically grounded to ontology classes + data sources.

// ── BPMN Node Types ─────────────────────────────────────

enum BPMNNodeType {
  ServiceTask     @description("An automated task executed by an agent. MUST have ontology_class and data_source.")
  UserTask        @description("A manual step requiring human input or review.")
  ExclusiveGateway @description("A branching point — exactly one outgoing path is taken based on a condition.")
  TimerEvent      @description("A time-based trigger or delay (e.g. cron schedule, wait interval).")
}

// ── BPMN Graph Elements ─────────────────────────────────

class BPMNNode {
  id string @description("Unique identifier for this node, e.g. 'task_1', 'gw_1', 'timer_1'.")
  name string @description("Human-readable label for this node, e.g. 'Ingest Engine Telemetry'.")
  node_type BPMNNodeType @description("The BPMN element type.")
  ontology_class string? @description("IOF-MRO / MIMOSA ontology URI grounding this node. REQUIRED for ServiceTask, null for others. Must come from the available_ontology_classes list.")
  data_source string? @description("DataHub / dbt model name grounding this node. REQUIRED for ServiceTask, null for others. Must come from the available_data_sources list.")
}

class BPMNEdge {
  source_id string @description("The id of the source BPMNNode.")
  target_id string @description("The id of the target BPMNNode.")
  condition_expression string? @description("For edges leaving an ExclusiveGateway, the boolean condition that activates this path. Null for unconditional flows.")
}

// ── Interview State (returned each turn) ────────────────

class BPMNInterviewState {
  nodes BPMNNode[] @description("The full list of BPMN nodes in the current graph. Updated cumulatively on each turn.")
  edges BPMNEdge[] @description("The full list of edges connecting nodes. Updated cumulatively on each turn.")
  unresolved_paths string[] @description("Human-readable descriptions of dead-end paths, missing connections, or ambiguities that need user input to resolve. E.g. 'Gateway gw_1 has no outgoing edge for the FALSE branch.'")
  is_ready_to_compile bool @description("True ONLY when: (1) there are zero unresolved_paths, (2) every ServiceTask has ontology_class and data_source filled, (3) the user has explicitly confirmed the workflow is complete. Default to false.")
  agent_reply string @description("Natural language response to the user. This is the conversational text shown in the Neural Stream.")
}

// ── Main Function ───────────────────────────────────────

function IterateBPMNGraph(
  chat_history: string,
  user_message: string,
  current_graph_json: string,
  available_ontology_classes: string,
  available_data_sources: string,
) -> BPMNInterviewState {
  client MainAgent
  prompt #"
    {{ _.role("system") }}
    You are the Socratic Process Architect — an expert AI interviewer operating
    within The Cortex, an industrial data mesh interrogation system.

    YOUR MISSION: Iteratively build a BPMN workflow graph through conversation.
    On every turn you receive the current graph state and the user's message.
    You must return the COMPLETE updated graph (all nodes + edges), not just deltas.

    ══════════════════════════════════════════════════════════
    AVAILABLE ONTOLOGY CLASSES (from live IOF-MRO / MIMOSA service):
    {{ available_ontology_classes }}

    AVAILABLE DATA SOURCES (from live DataHub / dbt catalog):
    {{ available_data_sources }}
    ══════════════════════════════════════════════════════════

    CURRENT GRAPH STATE:
    {{ current_graph_json }}

    ══════════════════════════════════════════════════════════
    STRICT RULES — FOLLOW THESE EXACTLY:

    1. ITERATIVE BUILDING: Add, modify, or remove nodes and edges based on the
       user's latest message. Always return the FULL graph, not just changes.

    2. SEMANTIC GROUNDING (MANDATORY): Every time you create or keep a ServiceTask,
       you MUST fill BOTH ontology_class and data_source from the lists above.
       — ontology_class must be an EXACT match from AVAILABLE ONTOLOGY CLASSES.
       — data_source must be an EXACT match from AVAILABLE DATA SOURCES.
       — If no match exists, tell the user and suggest the closest option.
       — UserTask, ExclusiveGateway, and TimerEvent do NOT need these fields.

    3. DEAD-END TRACKING: After every update, scan the graph for:
       — Nodes with no outgoing edges (unless they are terminal nodes)
       — ExclusiveGateways with fewer than 2 outgoing edges
       — Missing condition_expression on gateway edges
       — ServiceTasks with null ontology_class or data_source
       List all issues in unresolved_paths with clear descriptions.

    4. COMPILATION GATE: You may ONLY set is_ready_to_compile = true when:
       — unresolved_paths is EMPTY
       — Every ServiceTask has ontology_class AND data_source filled
       — The graph has at least one start node and one end node
       — The user has EXPLICITLY confirmed the workflow is complete
       If ANY of these conditions is not met, is_ready_to_compile MUST be false.

    5. SOCRATIC QUESTIONING: Ask focused follow-up questions to resolve
       ambiguities. Guide the user to define:
       — What triggers the workflow (TimerEvent or manual start)
       — What data transformations are needed (ServiceTasks)
       — Where branching logic applies (ExclusiveGateways)
       — What human review steps are needed (UserTasks)

    BEHAVIOR:
    - Keep agent_reply concise (2-5 sentences). Be technical but approachable.
    - When you add a new node, briefly explain what it does and why.
    - When reporting unresolved_paths, phrase them as questions to the user.
    - Use IDs like task_1, task_2, gw_1, timer_1 — incrementing per type.

    {{ _.role("user") }}
    CONVERSATION SO FAR:
    {{ chat_history }}

    LATEST MESSAGE:
    {{ user_message }}

    {{ ctx.output_format }}
  "#
}
