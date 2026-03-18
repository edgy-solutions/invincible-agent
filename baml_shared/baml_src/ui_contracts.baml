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

class SemanticUIContainer {
  archetype SemanticArchetype
  subject_concept string      // e.g., 'iof-mro:AuxiliaryFuelPump'
  severity SeverityLevel?
  entities string             
  relationships string?       
}

/// Router function mapping raw data and persona to a semantic UI intent
function DesignUI(raw_data: string, persona: PersonaTarget) -> SemanticUIContainer {
  client "openai/gpt-4o"
  prompt #"
    Act as a Semantic UI Translator. Do NOT output frontend code. 
    Analyze the raw data and the Persona. 
    Output the correct SemanticArchetype. 
    
    For example:
    - If the Persona is PROCESS_ENGINEER and the data contains steps, use PROCESS_TOPOLOGY. 
      Dump the exact step data into entities, and the topological connections into relationships as native JSON arrays.
    - If it is a safety warning, use HAZARD_DECLARATION and set the severity.
    - If it's a manual or code, use KNOWLEDGE_DOCUMENT.
    - If it's telemetry or inventory, use ASSET_STATE_METRIC.

    Identify the core subject concept (e.g., an IOF URI if available).

    --- RAW DATA ---
    {{ raw_data }}

    --- TARGET PERSONA ---
    {{ persona }}

    {{ ctx.output_format }}
  "#
}

