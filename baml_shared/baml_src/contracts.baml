// =============================================================================
// Polyglot Agentic Data Mesh - Shared Data Contracts
// =============================================================================
// These BAML definitions serve as the single source of truth for ALL agent
// communication across the mesh. Every microservice (Engine A: Restate+Smolagents,
// Engine B: LangGraph) must serialize/deserialize to these schemas.
//
// IMPORTANT: Ontology classes are NOT hardcoded here. They are dynamically
// injected at runtime from the RDF graph via the active_ontology_classes
// parameter in ClassifyDomainIntent.
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

enum OntologyClass {
  @@dynamic
}

// -----------------------------------------------------------------------------
// Semantic Resolution
// -----------------------------------------------------------------------------

/// Result of mapping free-text input to a canonical sustainment concept.
/// The resolved_uri is a dynamic ontology URI (not a hardcoded enum) that
/// comes from the RDF graph at runtime.
class SemanticResolution {
  resolved_uri OntologyClass
    @description("The ontology URI that best matches the input query. Must be one of the URIs provided in active_ontology_classes.")
  confidence_score float
    @description("Model confidence in the match, between 0.0 and 1.0.")
  reasoning string?
    @description("1-2 sentence explanation of why this class was chosen.")
  instance_identifier string?
    @description("If the query refers to a SPECIFIC NAMED INDIVIDUAL — a catalog asset path like gold.sales.revenue_summary, a procedure or work-order code like TEST-1234 or AFP-2024-001, a data module code (DMC), a tail number, an equipment serial, or a quoted or titled name like 'Customer 360' — copy that exact token here verbatim. Otherwise leave null. This field gates the router's instance-resolution pre-step (Recipe v2): when set, the router fans the token out to registered providers and lets the authoritative phone-book class override resolved_uri. Still always resolve resolved_uri as your best guess either way — the phone book may miss.")
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
  user_id string?
    @description("The identity of the user requesting the task, used for memory partitioning.")
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
  structured_data string?
    @description("MUST be a raw JSON object/dictionary containing the actual data (e.g., lists of dashboards, chart metrics). DO NOT stringify this inside summary.")
  extracted_metrics map<string, float>
    @description("Key-value pairs of domain metrics extracted during processing.")
  execution_trace string?
    @description("The internal reasoning logs or trajectory of the agent.")
}

// -----------------------------------------------------------------------------
// BAML Function — Semantic Intent Classification
// -----------------------------------------------------------------------------

/// Classifies a user query against dynamically-provided ontology classes.
/// The active_ontology_classes string is injected at runtime from the RDF
/// graph — it contains a newline-delimited list of valid ontology URIs.
function ClassifyDomainIntent(query: string, domain: string) -> SemanticResolution {
  client MainAgent
  prompt #"
    You are a semantic classifier for the {{ domain }} domain.

    You do two jobs in one pass:

    JOB A — Classify the KIND.
    Map the user's query to exactly ONE ontology URI from the permitted
    values defined in the output format. Pick the single best-matching
    URI and assign a confidence score between 0.0 and 1.0.

    JOB B — Extract any NAMED INDIVIDUAL.
    If the query refers to a specific named individual — a catalog asset
    path like gold.sales.revenue_summary, a code like TEST-1234 or
    AFP-2024-001, a data module code (DMC), a tail number, an equipment
    serial, or a quoted or titled name like 'Customer 360' — copy that
    EXACT token into the instance_identifier field. Otherwise leave it
    null.

    Be RECALL-BIASED on Job B: when in doubt about whether something is
    a name vs. a description, extract it. A miss costs more than a
    spurious extraction — the router can verify with the phone book,
    but it cannot recover from an extraction the model never made. Even
    in awkward conversational prose ("so yesterday someone mentioned
    customers_gold or something"), pull the name out.

    CRITICAL: The shape of an identifier (dots, dashes, capitalization)
    is NOT evidence about its kind. Resolve resolved_uri from the
    query's meaning, NOT from the identifier's shape. The phone book
    decides the kind for named individuals later; your resolved_uri is
    your best guess if the phone book has no answer.

    User query: {{ query }}

    {{ ctx.output_format }}
  "#
}

// -----------------------------------------------------------------------------
// BAML Function — Legacy Table Classification
// -----------------------------------------------------------------------------

class TableClassificationResult {
  resolved_uri OntologyClass? @description("The exact matching IOF Ontology URI, or null if uncertain/unrelated.")
  confidence_score float @description("Confidence level from 0.0 to 1.0.")
  reasoning string @description("A 1-2 sentence explanation of why this mapping was chosen based on the dossier.")
}

function ClassifyLegacyTable(
  table_name: string,
  columns_schema: string,
  dba_comments: string,
  orm_class_name: string,
  sample_data: string,
  domain: string
) -> TableClassificationResult {
  client MainAgent
  prompt #"
    You are a Principal Data Architect mapping legacy database tables to a strict Enterprise Knowledge Graph Ontology for the {{ domain }} domain.
    
    Review the following Rich Context Dossier for a specific database table:
    ---
    Table Name: {{ table_name }}
    DBA Comments: {{ dba_comments }}
    Developer ORM Class: {{ orm_class_name }}
    Columns & Data Types: 
    {{ columns_schema }}
    Sample Data:
    {{ sample_data }}
    ---

    Your Task: Map this table to exactly ONE IOF Ontology URI from the 
    permitted values defined in the output format.

    Instructions:
    1. Look for semantic overlap between table names/comments and the ontology class definitions.
    2. If the table is a join table or metadata (e.g. `flyway_schema_history`), return null.
    3. Select strictly from the permitted list.

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Engine E (Neo4j Graph Expert) Data Contracts
// =============================================================================

/// Target persona for the graph expert response
enum PersonaTarget {
  @@dynamic
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

class DataStewardResponse {
  tool_list string[]
  safety_warnings string[]
  short_answer string
}

class GraphExpertResponse {
  confidence_score float
  referenced_uris string[]
  data MechanicResponse | AuthoringResponse | LogisticsResponse | AuditResponse | DataStewardResponse
  execution_trace string?
    @description("The internal reasoning logs or trajectory of the agent.")
}

function FormatGraphResponse(raw_text: string, persona: string) -> GraphExpertResponse {
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
    5. STRICT MARKDOWN FORMATTING: You are writing for a React Markdown renderer. You MUST use strict Markdown hierarchy (e.g., ### Section Name). You MUST place a double newline (\n\n) before and after EVERY header, list, and paragraph. If you fail to use double newlines, the text will crush together into an unreadable block.
    6. EMBEDDING FIGURES: If the raw graph data contains Figure URLs and Titles, you MUST embed them directly into your short_answer or draft_content using standard Markdown image syntax: ![Image Title](Image URL). Place the image on a new line immediately following the step that references it.

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

function DecomposeQuery(raw_query: string, active_personas: string) -> SupervisorTaskPlan {
  client MainAgent
  prompt #"
    Break this complex user query into discrete tasks.

    User Query:
    {{ raw_query }}

    Instructions:
    1. Extract the core entities, components, or systems the user is asking about and list them in `extracted_concepts`.
    2. Assign each task to the correct specialized persona chosen STRICTLY from the Active Agent Roster below.
    3. Read the specific rules and domain constraints for each persona in the roster. Do not misassign tasks.
    4. If the query only needs one persona, return a list with just one task.
    5. Provide your reasoning for why the query was split this way.

    --- ACTIVE AGENT ROSTER ---
    {{ active_personas }}
    --- END ROSTER ---

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Phase 3: Mesh Intent Routing (Multi-Domain)
// =============================================================================

enum Intent {
  @@dynamic
}

enum Domain {
  @@dynamic
}

class MeshRoutingDecision {
  intent Intent
  domain Domain
  confidence float @description("Confidence in both intent and domain classification.")
  reasoning string @description("Why you routed it this way.")
  task_plan SupervisorTaskPlan? @description("Populate for all operational intents (queries, creation, retrieval, audits) to seed the multi-agent execution.")
}

function RouteAndPlan(user_query: string) -> MeshRoutingDecision {
  client MainAgent
  prompt #"
    Act as the Kernel Scheduler for a Multi-Domain Agentic Mesh.
    Analyze the user's query and determine the execution intent and domain.
    
    CRITICAL INSTRUCTIONS: 
    1. You must select the intent, domain, and personas strictly from the permitted values defined in the output format below.
    2. DO NOT populate a task plan if the intent is SYSTEM_META_AND_REJECTION.
    
    User Query:
    {{ user_query }}
    
    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Phase 4 (ADR-0009 Step F' / F'.6): Mesh Intent Extraction (mode + entities)
// =============================================================================
//
// RouteAndPlan above is the legacy 3-axis classifier — slated for deletion
// once gateway + supervisor migrate. ExtractIntent is its replacement.
//
// Step F'.6 simplification: candidate_verb was removed. Engine O's
// /search_predicates runs Weaviate hybrid search directly on the raw user
// query against the Predicate collection's `search_text` field (verb
// humanized + synonyms + description), so an LLM-extracted verb adds a
// lossy intermediate step. The remaining LLM jobs are:
//
//   * `mode` — the binary routing discriminator (conversational vs
//     one-shot). Genuinely needs LLM judgment about the user's intent
//     shape; no vector store can replace it.
//   * `entity_refs` — concrete nouns the supervisor feeds to /resolve
//     when grounding subjects/objects to ontology URIs is needed.

enum Mode {
  ONE_SHOT @description("User wants the mesh to execute work and return a deterministic result (find, diagnose, summarize, query, analyze).")
  CONVERSATIONAL @description("User wants a multi-turn dialog — BPMN interview, troubleshooting walkthrough, collaborative authoring, or any other interaction that requires back-and-forth before producing the artifact.")
}

class ExtractedIntent {
  mode Mode
  entity_refs string[] @description("Concrete entities, parts, systems, datasets the user mentioned (e.g., 'Auxiliary Fuel Pump', 'C-130 hydraulic system'). Empty if the query has no specific referents.")
  confidence float @description("Confidence in the mode choice.")
  reasoning string @description("Why this mode — for observability and debugging.")
}

function ExtractIntent(user_query: string) -> ExtractedIntent {
  client MainAgent
  prompt #"
    Analyze the user's query and extract routing-relevant facts.

    Decide MODE:
    - mode = CONVERSATIONAL when the user is starting or continuing a multi-turn
      interaction (e.g., "help me design a workflow", "walk me through the fix",
      "build a process that..."). These are dialogs, not one-shot lookups.
    - mode = ONE_SHOT for everything else: diagnose, find, look up, summarize,
      analyze, query, retrieve. The user wants a deterministic result, not a chat.

    Extract:
    - entity_refs: concrete nouns the query mentions — parts, systems,
      datasets, document names. Empty list if none. These feed the
      supervisor's /resolve call when subject grounding is needed.

    DO NOT try to pick a verb — verb matching is done by hybrid vector
    search downstream from your output. Your job is the binary mode and
    the entity list.

    User Query:
    {{ user_query }}

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Engine W (Weaviate Semantic Expert) Data Contracts
// =============================================================================

class KnowledgeResponse {
  summary string @description("A clear, professional summary answering the user's knowledge or policy question. Format in Markdown.")
  referenced_documents string[] @description("List of manual sections, policies, or documents cited in the summary.")
  confidence_score float
  execution_trace string? @description("The internal reasoning logs or trajectory of the agent.")
}

function FormatKnowledgeResponse(raw_text: string, domain: string) -> KnowledgeResponse {
  client MainAgent
  prompt #"
    You are a Technical Editor.
    Format the following raw text generated by our Semantic Agent into a clean, readable summary for the {{ domain }} domain.

    Raw Agent Output:
    {{ raw_text }}

    CRITICAL RULES:
    1. Do not invent information. If the agent says the information was not found, state that clearly in the summary.
    2. Extract any document references or policy names mentioned in the text into the referenced_documents array.
    3. Do NOT narrate figure rendering, availability, or where figures can be accessed.
       Do NOT write phrases like "available via structural panel links," "not rendered inline,"
       "accessed through the provided links in the source system," or any equivalent. Figure
       PLACEMENT is the renderer's responsibility, not yours. If the raw text references a
       figure by identifier or descriptive caption ("Figure MS098897A shows the boom assembly
       schematic"), echo that reference verbatim if relevant — but never editorialize about
       whether/how/where the figure renders. The renderer places figures (or honest in-place
       placeholders) based on structured data; you generate prose about the SUBJECT, not the
       presentation.
    4. Do NOT direct the user to "the source system," "structural panel," "external links,"
       or any other location to find figures. If a figure can't be shown, the renderer will
       show an honest placeholder where it belongs; you do not narrate that fact.

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
  CHART_WIDGET         // 🟢 NEW: Maps to Bar, Line, and Pie charts
  DIGITAL_TWIN_3D      // Maps to 3D Digital Twin models
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
  subject_concept string?
  nodes UIEntity[]
  edges UIRelation[]
}

class HazardUI {
  archetype SemanticArchetype @description("MUST be HAZARD_DECLARATION")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string?
  severity SeverityLevel
  hazards UIEntity[]
}

class MetricUI {
  archetype SemanticArchetype @description("MUST be ASSET_STATE_METRIC")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string?
  metrics UIEntity[]
}

class DocumentUI {
  archetype SemanticArchetype @description("MUST be KNOWLEDGE_DOCUMENT")
  source_persona string? @description("The persona that produced this data. Copy from the raw data 'persona' field.")
  subject_concept string?
  markdown_content string
}

enum ChartType {
  BAR
  LINE
  PIE
  SCATTER
}

class ChartUI {
  archetype SemanticArchetype @description("MUST be CHART_WIDGET")
  source_persona string?
  subject_concept string?
  chart_type ChartType
  chart_data string @description("JSON stringified array of data points for Recharts preview.")
  sql_query string @description("The raw SQL query used. Required for Superset publication.")
  superset_dataset_name string?
  is_published bool
}

class AnomalyNode {
  element_id string @description("e.g., TR-1042")
  temp float
  status string @description("DEGRADED or CRITICAL_FAILURE")
}

class DigitalTwinUI {
  archetype SemanticArchetype @description("MUST be DIGITAL_TWIN_3D")
  source_persona string?
  subject_concept string?
  device_id string @description("Name of the system, e.g., LTAMDS Gen-4")
  core_temp float @description("Overall core temperature of the system")
  uptime_hours int
  anomalies AnomalyNode[] @description("List of elements that are not nominal")
}

// 3. Composite Dashboard Container
class DashboardUI {
  components (TopologyUI | HazardUI | MetricUI | DocumentUI | ChartUI | DigitalTwinUI)[]
}

// 4a. ADR-0017 archetype-hardened renderers (per-archetype, no LLM choice).
//
// Each RenderAs* function returns a SPECIFIC archetype class — not the
// DashboardUI union — so the LLM cannot pick a different archetype, only
// populate the fields of the one chosen by the caller (Engine F's
// predicate-graph lookup). This is the hard-constraint replacement for
// the soft hint that lived in the persona string
// (f"{persona}::REQUIRED_ARCHETYPE={archetype}") between ADR-0017 ship
// and this cleanup. The grounding rules ported from DesignUI prevent
// invented identifiers and asset hallucination.

function RenderAsTopology(raw_data: string, persona: string) -> TopologyUI {
  client MainAgent
  prompt #"
    Populate a TopologyUI (PROCESS_TOPOLOGY archetype) from the raw_data.
    The caller has already chosen this archetype — your job is to fill
    in nodes and edges, not to pick a different shape.

    GROUNDING RULES (failures here are silently wrong):

    A. NEVER INVENT IDENTIFIERS. Every UIEntity.id, UIRelation.source,
       UIRelation.target MUST appear verbatim somewhere in raw_data.

    B. NEVER INVENT NODES. If raw_data names three datasets in a
       lineage chain, your nodes array contains those three. Not five.

    C. EDGES MUST REFERENCE NODES IN THE NODES ARRAY. No dangling edges.

    --- RAW DATA ---
    {{ raw_data }}

    --- PERSONA HINT (for tone, not archetype selection) ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}

function RenderAsHazard(raw_data: string, persona: string) -> HazardUI {
  client MainAgent
  prompt #"
    Populate a HazardUI (HAZARD_DECLARATION archetype) from the raw_data.
    The caller has already chosen this archetype — your job is to fill
    in severity and hazards, not to pick a different shape.

    GROUNDING RULES:

    A. NEVER INVENT IDENTIFIERS. Every UIEntity.id in the hazards array
       MUST appear verbatim in raw_data.

    B. NEVER INVENT HAZARDS. If raw_data describes one PII-exposed
       dataset, your hazards array has one entry. Not three.

    C. SEVERITY REFLECTS RAW_DATA. If raw_data describes a confirmed
       policy violation, severity is WARNING or CRITICAL. If raw_data
       describes the absence of a problem (e.g. "no PII datasets
       without an owner"), severity is INFO.

    --- RAW DATA ---
    {{ raw_data }}

    --- PERSONA HINT (for tone, not archetype selection) ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}

function RenderAsMetric(raw_data: string, persona: string) -> MetricUI {
  client MainAgent
  prompt #"
    Populate a MetricUI (ASSET_STATE_METRIC archetype) from the raw_data.
    The caller has already chosen this archetype — your job is to fill
    in metrics, not to pick a different shape.

    GROUNDING RULES:

    A. NEVER INVENT IDENTIFIERS. Every UIEntity.id MUST appear verbatim
       in raw_data.

    B. NEVER INVENT METRICS. If raw_data names three assets, your
       metrics array has exactly those three.

    C. ONE METRIC PER NAMED ASSET. Do not split a single asset into
       multiple metric rows or merge several into one.

    --- RAW DATA ---
    {{ raw_data }}

    --- PERSONA HINT (for tone, not archetype selection) ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}

function RenderAsChart(raw_data: string, persona: string) -> ChartUI {
  client MainAgent
  prompt #"
    Populate a ChartUI (CHART_WIDGET archetype) from the raw_data.
    The caller has already chosen this archetype — your job is to fill
    in chart_type, chart_data, and sql_query, not to pick a different
    shape.

    GROUNDING RULES:

    A. CHART_DATA IS VERBATIM. The chart_data field is a JSON-stringified
       array of data points. Use the rows present in raw_data; do not
       invent rows. The presentation_agent runs a deterministic
       key-normalization pass on this field after the BAML call —
       coerces whatever keys you pick into the widget's required
       ``{name, value}`` shape — so the field-name choice you make
       here is not load-bearing for rendering. Preserve the data
       faithfully and the normalizer handles shape conformance.

    B. SQL_QUERY IS PRESERVED. If raw_data contains a sql_query field
       or a sql query inline, copy it into ChartUI.sql_query verbatim.
       If absent, set sql_query to an empty string.

    C. CHART_TYPE INFERENCE. BAR for category comparisons, LINE for
       time series, PIE for parts-of-whole, SCATTER for two-axis
       distributions. Pick based on what the data shape supports, not
       what looks nicer.

    --- RAW DATA ---
    {{ raw_data }}

    --- PERSONA HINT (for tone, not archetype selection) ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}

// =============================================================================
// Predicate classification — symmetric of /resolve (ADR-0004 restored)
// =============================================================================
//
// Engine O's /resolve has done vector-recall + LLM-precision classification
// for OntologyClass SUBJECTS since the system was first wired:
//   weaviate_hybrid → top-10 candidates → TypeBuilder dynamic enum →
//     ClassifyDomainIntent → (subject_uri, confidence, reasoning)
//
// PREDICATES had no analogous machinery. ADR-0009 Step F'.6 added Weaviate
// hybrid over a Predicate collection, but stopped short of the LLM-precision
// step — verb routing became "BM25 picks the top score, supervisor uses it,
// VerifyVerbChoice second-guesses in a yellow zone." That asymmetry was the
// root cause of every "confidently wrong" routing failure we hit (mesh:
// describeAsset winning at 1.44 for procedure queries, etc.) because BM25
// over verb synonyms can't reason about subject context or semantic fit.
//
// ClassifyPredicate restores the symmetry. The supervisor calls Engine O's
// new /classify_predicate endpoint, which:
//   1. Runs predicate_hybrid_search (BM25) to get top-10 verb candidates
//      filtered by the caller's entitled_domains.
//   2. Builds a Predicate TypeBuilder dynamic enum from those 10 verb_iris,
//      each with its description as the enum value description.
//   3. Calls THIS function with the user query + resolved subject +
//      domain context. The LLM picks ONE verb (constrained by the enum)
//      with confidence + reasoning, or "UNKNOWN" if nothing fits.
//
// The PredicateClassification confidence score replaces the BM25 score
// for the supervisor's threshold decision (ADR-0008 fallback machinery
// keeps working — threshold on the LLM's confidence rather than BM25's).
// VerifyVerbChoice + the yellow-zone band are retired: the LLM is the
// primary classifier, not a second-guess gate over BM25.

enum Predicate {
  @@dynamic
}

class PredicateClassification {
  resolved_verb_iri Predicate
    @description("The verb IRI that best matches the user's intent given the resolved subject. Must be one of the IRIs provided in the dynamic enum.")
  confidence_score float
    @description("0.0 (no fit) to 1.0 (clear fit). The supervisor's PREDICATE_FALLBACK_SCORE_THRESHOLD env var thresholds against this.")
  reasoning string
    @description("One sentence on why this verb was picked given the query and subject. If subject_uri == 'UNKNOWN', explain the pick against query alone.")
}

function ClassifyPredicate(
  query: string,
  subject_uri: string,
  subject_reasoning: string,
  domain: string,
) -> PredicateClassification {
  // Same client rationale as /resolve's ClassifyDomainIntent: MainAgent has
  // Ollama as its terminal fallback, so this works on sandbox (no
  // OpenRouter / OpenAI key) and in production (cloud LLM via the
  // configured fallback chain). The constrained-enum return + UNKNOWN
  // value let BAML handle the "nothing fits" case cleanly.
  client MainAgent
  prompt #"
    You are the predicate classifier for an SPO routing layer. The
    upstream subject classifier already placed this query against a
    registered OntologyClass. Your job is to pick the ONE predicate (verb)
    from the permitted list below that best operates on a subject of that
    class, given the user's intent.

    The permitted predicate list is injected as a strict enum in the
    output format. You may NOT invent a verb IRI; select one of the
    given values or "UNKNOWN" if none fit.

    USER QUERY:
    "{{ query }}"

    RESOLVED SUBJECT:
    Class IRI:    {{ subject_uri }}
    Why:          {{ subject_reasoning }}

    DOMAIN:
    {{ domain }}

    GUIDANCE:
    - The subject is a STRONG signal. A verb whose description says it
      operates on catalog assets does NOT belong on a WorkInstruction,
      even if the verb name and the query share the word "describe".
      Lexical proximity is not correctness; substrate fit is.
    - **Inheritance counts as substrate fit.** A candidate's description
      may include a phrase like "compatible with subject via inheritance
      (idp:Table ⊆ idp:Dataset)". That phrase is a GUARANTEE from the
      ontology graph that the verb's typed input is an ancestor of the
      resolved subject in the subClassOf hierarchy. Treat such a
      candidate as a valid substrate fit — do NOT refuse it just because
      the verb's input_uri string differs from the subject_uri string.
      The graph already validated the relationship; you only need to
      validate intent (does the user's query actually match what this
      verb does).
    - When you do refuse with UNKNOWN, the reasoning must name the
      specific intent mismatch (e.g., "the user asked for cost data,
      not lineage"). Do not refuse on a substrate string mismatch when
      an inheritance phrase is present.
    - If subject_uri is "UNKNOWN", the upstream classifier could not
      place the query — pick the verb that best matches the raw query
      and lower confidence accordingly.
    - confidence_score is your own assessment of how well the verb fits.
      Below ~0.4 the supervisor will fall back to a generalist agent;
      above that, the specialist gets dispatched.
    - reasoning: one sentence. If you reject substrate mismatches, say
      so explicitly so the operator can act on the signal.

    {{ ctx.output_format }}
  "#
}

// 4b. The legacy union-returning router. Retained for backward
// compatibility with /render_ui's fallback path (output_uri missing or
// no capability matched). Engine F's deterministic + archetype-hardened
// paths bypass this entirely.
function DesignUI(raw_data: string, persona: string) -> DashboardUI {
  client MainAgent
  prompt #"
    Act as a Semantic UI Translator for an Advanced Analytics Mesh.
    Analyze the raw data array and the Target Persona.

    --- DATA IDENTIFICATION RULES ---
    1. SUPERSET DATA: If the data is a JSON array of objects (rows/columns) representing query results (EVEN IF IT IS WRAPPED IN A STRING OR SUMMARY FIELD):
       - USE ChartUI (CHART_WIDGET).
       - Select the best `chart_type` (BAR for comparisons, LINE for trends, PIE for parts-of-whole).
       - Ensure the `sql_query` used to generate the data is preserved in the object.

    2. METADATA LISTS: If the data describes a list of Dashboards, Charts, or Tables (like {'dashboards': [...]}):
       - USE MetricUI (ASSET_STATE_METRIC).
       - Map each dashboard/chart to an item in the `metrics` array.

    3. TEXT/KNOWLEDGE: Use this when the answer is a natural-language explanation,
       a single fact about an asset (ownership, freshness, source-of-truth),
       a lineage trace described in prose, or any response that does NOT contain
       a fresh list of catalog items the user explicitly asked to enumerate.
       Catalog Q&A queries (e.g. "who owns dashboard X", "when was Y last
       updated", "what is the source of truth for Z") belong here, NOT in
       ASSET_STATE_METRIC, because the answer is descriptive prose grounded
       in the agent's text, not a list of new assets to inventory.

    4. DIGITAL TWIN: If the data explicitly describes physical hardware states, phased array sensor diagnostics, or element-level thermal/voltage telemetry from an edge device:
       - USE DigitalTwinUI (DIGITAL_TWIN_3D).
       - Extract the overall core_temp and uptime_hours for the global stats.
       - Map the broken/overheating elements into the anomalies array.

    CRITICAL GROUNDING RULES (read carefully — failures here are silently
    incorrect, never visibly broken):

    A. NEVER INVENT IDENTIFIERS. Every `id` value you emit (UIEntity.id,
       UIRelation.source, UIRelation.target, AnomalyNode.element_id,
       device_id, etc.) MUST appear *verbatim* somewhere in the raw_data
       text. If raw_data does not contain a URN, dataset name, or asset
       identifier for an item you want to include, either:
         (a) omit the item entirely, or
         (b) emit only the human-readable name in `name` and use that same
             string as `id`.
       NEVER make up DataHub URNs, Snowflake table names, postgres
       schemas, or S3 paths you did not see in raw_data.

    B. NEVER INVENT ASSETS. Do not add entries to `metrics`, `nodes`,
       `edges`, `hazards`, or `anomalies` for assets the agent did not
       mention in raw_data. If the agent named three datasets, your
       metrics array has exactly those three datasets — not five.

    C. PREFER PROSE WHEN IN DOUBT. If raw_data is the agent's natural-
       language answer to a question (e.g. "the Sales Performance Q1
       dashboard is owned by Bob"), choose KNOWLEDGE_DOCUMENT and put
       the agent's text into markdown_content. KNOWLEDGE_DOCUMENT
       preserves grounded facts. ASSET_STATE_METRIC is only correct
       when the user explicitly asked to enumerate a list of catalog
       items AND the raw_data contains an explicit list with
       identifiable entries.

    D. NO PARSING-WITHOUT-EVIDENCE. If a summary mentions abstractly
       that "downstream datasets will be impacted" without naming
       them, do NOT manufacture downstream dataset names to populate
       a metrics array. Use KNOWLEDGE_DOCUMENT and let the user see
       the agent's reasoning verbatim.

    Produce a `DashboardUI` object. Map each expert response in the input
    to its corresponding component.

    --- RAW DATA ---
    {{ raw_data }}

    --- TARGET PERSONA ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}
