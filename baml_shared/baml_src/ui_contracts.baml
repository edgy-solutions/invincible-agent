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

/// The exact React UI Component the frontend should render
enum UIComponentType {
  WARNING_CARD
  INTERACTIVE_CHECKLIST
  SUPPLY_TABLE
  XML_EDITOR
  BPMN_VIEWER
  MARKDOWN_CHAT
}

class FlowNode {
  id string
  type string @description("e.g., 'default', 'input', 'output'")
  label string
  position_x int
  position_y int
}

class FlowEdge {
  id string
  source string
  target string
  animated bool
}

class BpmnViewerProps {
  title string
  nodes FlowNode[]
  edges FlowEdge[]
  ontology_tags string[] @description("For the Live Context HUD")
}

/// Server-driven UI instruction payload
class PresentationInstruction {
  mood MoodType
    @description("The visual mood or tone for the UI.")
  selected_component UIComponentType
    @description("The exact target React component.")
  header_text string
    @description("Title or header text for the rendered view.")
  ui_props string
    @description("This must be a stringified JSON object containing the exact data the frontend component needs (e.g., node mapping references or hazard arrays for Warning Cards).")
  bpmn_data BpmnViewerProps?
    @description("Structured React Flow data, specifically populated when selected_component is BPMN_VIEWER.")
}

/// Router function mapping raw data and persona to a UI layout
function DesignUI(raw_data: string, persona: PersonaTarget) -> PresentationInstruction {
  client "openai/gpt-4o"
  prompt #"
    Act as an expert UX Designer. Analyze the raw data and the persona.

    If the persona is MECHANIC and there are hazards, choose WARNING_CARD.
    If the persona is MECHANIC and there are no critical hazards, choose INTERACTIVE_CHECKLIST.
    If the persona is PROCESS_ENGINEER, you MUST select the BPMN_VIEWER component. Parse the raw steps into FlowNode objects (calculating basic x/y coordinates to lay them out top-to-bottom) and link them with FlowEdge objects.
    For LOGISTICS, choose SUPPLY_TABLE.
    For TECH_WRITER, choose XML_EDITOR.
    Otherwise, fall back to MARKDOWN_CHAT.

    --- RAW DATA ---
    {{ raw_data }}

    --- TARGET PERSONA ---
    {{ persona }}

    Instructions:
    1. Determine the appropriate mood.
    2. Select the correct UIComponentType.
    3. Generate a concise header text.
    4. Output the exact JSON props required for that component as a stringified JSON object in ui_props.
    5. If the persona is PROCESS_ENGINEER, ensure bpmn_data is fully populated with nodes and edges.

    {{ ctx.output_format }}
  "#
}
