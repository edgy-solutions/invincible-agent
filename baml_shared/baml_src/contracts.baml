// =============================================================================
// Polyglot Agentic Data Mesh - Shared Data Contracts
// =============================================================================
// These BAML definitions serve as the single source of truth for ALL agent
// communication across the mesh. Every microservice (Engine A: Restate+Smolagents,
// Engine B: LangGraph) must serialize/deserialize to these schemas.
//
// IMPORTANT: Ontology classes are NOT hardcoded here. They are dynamically
// injected at runtime from the RDF graph via the active_ontology_classes
// parameter in ClassifySustainmentIntent.
// =============================================================================

// -----------------------------------------------------------------------------
// Enums
// -----------------------------------------------------------------------------

/// Status returned by any agent after processing a task.
enum AgentStatus {
  SUCCESS
    @description("The agent completed the task without errors.")
  FAILED
    @description("The agent encountered an unrecoverable error.")
  HUMAN_REQUIRED
    @description("The agent needs human-in-the-loop intervention to proceed.")
}

// -----------------------------------------------------------------------------
// Semantic Resolution
// -----------------------------------------------------------------------------

/// Result of mapping free-text input to a canonical sustainment concept.
/// The resolved_uri is a dynamic ontology URI (not a hardcoded enum) that
/// comes from the RDF graph at runtime.
class SemanticResolution {
  resolved_uri string
    @description("The ontology URI that best matches the input query. Must be one of the URIs provided in active_ontology_classes.")
  confidence_score float
    @description("Model confidence in the match, between 0.0 and 1.0.")
  suggested_dbt_models string[]
    @description("Ordered list of dbt model names relevant to the resolved concept.")
}

// -----------------------------------------------------------------------------
// Agent Input
// -----------------------------------------------------------------------------

/// The universal task payload sent from the Dagster orchestrator to any agent
/// pod via HTTP POST. Every agent endpoint must accept this schema.
class AgentTask {
  task_description string
    @description("Human-readable description of the work the agent should perform.")
  dataset_id string
    @description("Identifier for the target dataset or data asset in the mesh.")
  semantic_context SemanticResolution?
    @description("Optional pre-resolved semantic context. When present, agents can skip their own classification step.")
}

// -----------------------------------------------------------------------------
// Agent Output
// -----------------------------------------------------------------------------

/// The universal response payload returned by every agent pod.
/// The Dagster orchestrator inspects this to decide on next steps
/// (e.g., retry, escalate, or continue the pipeline).
class AgentResponse {
  status AgentStatus
    @description("Outcome of the agent's execution.")
  summary string
    @description("Brief human-readable summary of what the agent did.")
  extracted_metrics map<string, float>
    @description("Key-value pairs of domain metrics extracted during processing.")
}

// -----------------------------------------------------------------------------
// BAML Function — Semantic Intent Classification
// -----------------------------------------------------------------------------

/// Classifies a user query against dynamically-provided ontology classes.
/// The active_ontology_classes string is injected at runtime from the RDF
/// graph — it contains a newline-delimited list of valid ontology URIs.
function ClassifySustainmentIntent(query: string, active_ontology_classes: string) -> SemanticResolution {
  client MainAgent
  prompt #"
    You are a sustainment-domain semantic classifier.
    
    Your job is to map the user's query to exactly ONE ontology URI from the
    list below. Do NOT invent URIs — you must select strictly from this list.

    --- ACTIVE ONTOLOGY CLASSES ---
    {{ active_ontology_classes }}
    --- END ---

    User query: {{ query }}

    Instructions:
    1. Analyze the user's query for sustainment-domain intent.
    2. Select the single best-matching ontology URI from the list above.
    3. Assign a confidence score between 0.0 and 1.0.
    4. Suggest an ordered list of dbt model names that would be relevant
       to the matched concept.

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Engine E (Neo4j Graph Expert) Data Contracts
// =============================================================================

/// Target persona for the graph expert response
enum PersonaTarget {
  MECHANIC
  TECH_WRITER
  LOGISTICS
  AUDITOR
  PROCESS_ENGINEER
}

class MechanicResponse {
  tool_list string[]
  safety_warnings string[]
  short_answer string
}

class AuthoringResponse {
  draft_content string @description("A clear, formatted Markdown summary of the requested technical data. Do NOT use XML.")
  missing_info_flags string[] @description("List of any required technical data that was missing from the graph.")
}

class LogisticsResponse {
  impacted_platforms string[]
  blocked_procedures string[]
  risk_severity string
}

class AuditResponse {
  non_compliant_nodes string[]
  rule_violated string
  recommended_fix string
}

class GraphExpertResponse {
  confidence_score float
  referenced_uris string[]
  data MechanicResponse | AuthoringResponse | LogisticsResponse | AuditResponse
}

function FormatGraphResponse(raw_text: string, persona: PersonaTarget) -> GraphExpertResponse {
  client MainAgent
  prompt #"
    You are a technical data formatting expert.
    Turn the following raw data extracted from a Neo4j military graph database
    into a structured response tailored for a {{ persona }}.

    Raw Grapy Query Results:
    {{ raw_text }}

    CRITICAL GROUNDING RULES:
    1. STRICT ADHERENCE: You are in a strict military context. DO NOT invent or hallucinate data, procedures, or hazards.
    2. NO GENERIC ADVICE: Do not invent generic safety advice unless those exact words are in the raw data.
    3. NULL STATE TRIGGER: If the input raw data is empty or missing, you MUST return NULL_GRAPH_RESPONSE as the primary content of your response (e.g. in short_answer or equivalent).
    4. NO PANIC: Do not invent "red-flagged" areas or "unscheduled maintenance" if the query results are simply empty.

    Instructions:
    1. Parse the raw text carefully.
    2. Format it into the specific response structure required for a {{ persona }}.
    3. Include a confidence score and a list of any referenced URIs.

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Phase 2: Dynamic Supervisor Planning Contracts
// =============================================================================

class AgentTaskDefinition {
  target_persona PersonaTarget
  sub_query string
}

class SupervisorTaskPlan {
  tasks AgentTaskDefinition[]
  extracted_concepts string[] @description("List of main entities/components the user is asking about (e.g., 'Auxiliary Fuel Pump', 'C-130'). This populates the Ontology Map.")
  reasoning string
}

function DecomposeQuery(raw_query: string) -> SupervisorTaskPlan {
  client MainAgent
  prompt #"
    Break this complex user query into discrete tasks.

    User Query:
    {{ raw_query }}

    Instructions:
    1. Extract the core entities, components, or systems the user is asking about and list them in `extracted_concepts`.
    2. Assign each task to the correct specialized persona (MECHANIC, TECH_WRITER, LOGISTICS, AUDITOR, PROCESS_ENGINEER).
    3. TECH_WRITER GUARDRAIL: If assigning a task to the TECH_WRITER, explicitly instruct them in the `sub_query` to return their findings as standard Markdown text. Explicitly FORBID the use of string concatenation, f-strings, or Python code to generate XML.
    4. If the query only needs one persona, return a list with just one task.
    5. Provide your reasoning for why the query was split this way.

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Phase 3: Mesh Intent Routing
// =============================================================================

enum ExecutionIntent {
  ONE_SHOT_QUERY @description("User is asking for existing data, hazards, or procedures. Requires querying the Graph.")
  PROCESS_CREATION @description("User wants to build, design, write, or publish a NEW workflow, process, or data product.")
}

class MeshRoutingDecision {
  intent ExecutionIntent
  reasoning string @description("Why you routed it this way.")
  task_plan SupervisorTaskPlan? @description("Populate for both ONE_SHOT_QUERY and PROCESS_CREATION to seed the execution.")
}

function RouteAndPlan(user_query: string) -> MeshRoutingDecision {
  client MainAgent
  prompt #"
    Act as the Kernel Scheduler for an Agentic Mesh.
    Analyze the user's query and determine the execution intent.
    
    1. If they are asking for existing knowledge (e.g., "What are the hazards of..."), set intent to ONE_SHOT_QUERY and populate the `task_plan` with the required expert personas.
    2. If they are asking to build, create, or publish a NEW process (e.g., "Help me design a new pump removal process"), set intent to PROCESS_CREATION. STILL populate the `task_plan` with the required expert personas (e.g., MECHANIC for physical steps/hazards, PROCESS_ENGINEER for flow) to build an initial draft.
    
    User Query:
    {{ user_query }}
    
    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Recipe 1 (Path A): Stateless Dagster Synthesis
// =============================================================================

class FinalSynthesis {
  markdown_report string
}

function SynthesizeReports(original_query: string, raw_json_results: string) -> FinalSynthesis {
  client MainAgent
  prompt #"
    You are a Principal Technical Writer. Your job is to synthesize an array of JSON results 
    from our specialized Graph Expert agents into a single, cohesive, highly readable Markdown report.

    Original User Query:
    {{ original_query }}

    Raw JSON Results from Agents:
    {{ raw_json_results }}

    Instructions:
    1. Organize the findings logically based on the user's original query.
    2. Format the output with clear headers, bullet points, and emphasis where needed.
    3. Ensure the final report is beautiful, highly readable, and professional.

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Engine F (Presentation Agent) UI Routing Contracts
// =============================================================================

/// The visual tone or mood to pass to the frontend
enum MoodType {
  ROUTINE
  URGENT
  SUCCESS
  STRATEGIC
  EDUCATIONAL
}

enum SemanticArchetype {
  PROCESS_TOPOLOGY     // Maps to workflows, steps, BPMN
  HAZARD_DECLARATION   // Maps to safety, risk, warnings
  ASSET_STATE_METRIC   // Maps to inventory, telemetry, tables
  KNOWLEDGE_DOCUMENT   // Maps to manuals, standard text, code
}

enum SeverityLevel {
  INFO
  WARNING
  CRITICAL
}

// 1. Base building blocks
class UIEntity {
  id string
  name string?
  type string?
  description string?
}

class UIRelation {
  source string
  target string
  relation string?
  predicate string?
}

// 2. Strict UI Component Schemas
class TopologyUI {
  archetype SemanticArchetype @description("MUST be PROCESS_TOPOLOGY")
  source_persona string? @description("The persona that produced this data (e.g. MECHANIC, PROCESS_ENGINEER). Copy from the raw data 'persona' field.")
  subject_concept string
  nodes UIEntity[]
  edges UIRelation[]
}

class HazardUI {
  archetype SemanticArchetype @description("MUST be HAZARD_DECLARATION")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string
  severity SeverityLevel
  hazards UIEntity[]
}

class MetricUI {
  archetype SemanticArchetype @description("MUST be ASSET_STATE_METRIC")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string
  metrics UIEntity[]
}

class DocumentUI {
  archetype SemanticArchetype @description("MUST be KNOWLEDGE_DOCUMENT")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string
  markdown_content string
}

// 3. Composite Dashboard Container
class DashboardUI {
  components (TopologyUI | HazardUI | MetricUI | DocumentUI)[]
}

// 4. Update the router function to return the Composite Dashboard
function DesignUI(raw_data: string, persona: string) -> DashboardUI {
  client MainAgent
  prompt #"
    Act as a Semantic UI Translator. Do NOT output frontend code. 
    Analyze the raw data array (which contains outputs from multiple expert agents) and the Target Persona.
    
    CRITICAL INSTRUCTION:
    You are building a Composite Dashboard. You must output a `DashboardUI` object containing an array of components.
    Create a separate UI component in the `components` array for EACH distinct expert response in the raw data.
    ALWAYS copy the `persona` field from each raw data entry into the `source_persona` field of the corresponding component.
    
    CRITICAL GROUNDING RULES:
    1. STRICT ADHERENCE: You are in a strict military context. DO NOT invent or hallucinate data, procedures, or hazards.
    2. NO GENERIC ADVICE: Do not invent generic safety advice unless those exact words are in the raw data.
    3. NULL STATE TRIGGER: If the data is empty or missing, trigger the Null State.
    4. NULL STATE FORMAT: To trigger Null State, output a single DocumentUI in the components array. Set archetype to KNOWLEDGE_DOCUMENT and markdown_content to exactly: # SYSTEM ALERT\nNo relevant records found. Do not proceed without manual verification.
    
    EXAMPLES:
    - If the raw data has a Process Engineer's steps AND a Mechanic's safety warnings: 
      Output an array with 1 TopologyUI object AND 1 HazardUI object.
    - If the raw data has a Tech Writer's text: Output a single DocumentUI object.
    - PROCESS_ENGINEER: use TopologyUI. Map steps to nodes and connections to edges.
    - Safety warning: use HazardUI. Map hazards to the hazards array.
    - Manual/Text: use DocumentUI. Map text to markdown_content.
    
    --- RAW DATA ---
    {{ raw_data }}
    
    --- TARGET PERSONA ---
    {{ persona }}
    
    {{ ctx.output_format }}
  "#
}
