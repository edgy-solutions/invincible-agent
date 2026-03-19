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
  generated_xml string
  missing_info_flags string[]
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
  reasoning string
}

function DecomposeQuery(raw_query: string) -> SupervisorTaskPlan {
  client MainAgent
  prompt #"
    Break this complex user query into discrete tasks.

    User Query:
    {{ raw_query }}

    Instructions:
    1. Assign each task to the correct specialized persona (MECHANIC, TECH_WRITER, LOGISTICS, AUDITOR, PROCESS_ENGINEER).
    2. If the query only needs one persona, return a list with just one task.
    3. Provide your reasoning for why the query was split this way.

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

// Add these new structured classes
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

// Update the SemanticUIContainer to use BAML Unions
class SemanticUIContainer {
  archetype SemanticArchetype
  subject_concept string      
  severity SeverityLevel?
  
  // Forces the LLM to output a markdown string OR a strict JSON array
  entities string | UIEntity[]              
  relationships UIRelation[]?        
}

/// Router function mapping raw data and persona to a semantic UI intent
function DesignUI(raw_data: string, persona: PersonaTarget) -> SemanticUIContainer {
  client MainAgent
  prompt #"
    Act as a Semantic UI Translator. Do NOT output frontend code. 
    Analyze the raw data and the Persona. Output the correct SemanticArchetype.
    
    CRITICAL GROUNDING RULES:
    1. STRICT ADHERENCE: You are in a strict military context. DO NOT invent or hallucinate data, procedures, or hazards.
    2. NO GENERIC ADVICE: Do not invent generic safety advice unless those exact words are in the raw data.
    3. NULL STATE TRIGGER: If the data is empty or missing, trigger the Null State.
    4. NULL STATE FORMAT: Set archetype to KNOWLEDGE_DOCUMENT and entities to exactly: # SYSTEM ALERT: No relevant records found. Do not proceed without manual verification.

    EXAMPLES:
    - PROCESS_ENGINEER: use PROCESS_TOPOLOGY. Dump steps into entities.
    - Safety warning: use HAZARD_DECLARATION.
    - Manual/Text: use KNOWLEDGE_DOCUMENT.
    
    Core subject concept: e.g., an IOF URI if available.
    
    --- RAW DATA ---
    {{ raw_data }}
    
    --- TARGET PERSONA ---
    {{ persona }}
    
    {{ ctx.output_format }}
  "#
}
