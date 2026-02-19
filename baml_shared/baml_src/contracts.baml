// =============================================================================
// Polyglot Agentic Data Mesh — Shared Data Contracts
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
  client "openai/gpt-4o"
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
