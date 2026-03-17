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

/// Server-driven UI instruction payload
class PresentationInstruction {
  mood MoodType
    @description("The visual mood or tone for the UI.")
  selected_component UIComponentType
    @description("The exact target React component.")
  header_text string
    @description("Title or header text for the rendered view.")
  ui_props string
    @description("This must be a stringified JSON object containing the exact data the frontend component needs (e.g., nodes/edges for BPMN, hazard arrays for Warning Cards).")
}

/// Router function mapping raw data and persona to a UI layout
function DesignUI(raw_data: string, persona: PersonaTarget) -> PresentationInstruction {
  client "openai/gpt-4o"
  prompt #"
    Act as an expert UX Designer. Analyze the raw data and the persona.

    If the persona is MECHANIC and there are hazards, choose WARNING_CARD.
    If the persona is MECHANIC and there are no critical hazards, choose INTERACTIVE_CHECKLIST.
    If the persona is PROCESS_ENGINEER, parse the data into steps and choose BPMN_VIEWER.
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

    {{ ctx.output_format }}
  "#
}
