class FollowUpQuestion {
  question string @description("The next conversational question to ask the user to clarify the process.")
  missing_data string[] @description("What specifically are you still trying to figure out? (e.g., 'Need exact tool names')")
}

function RunProcessInterview(chat_history: string[], latest_user_msg: string) -> (FollowUpQuestion | TopologyUI) {
  client MainAgent
  prompt #"
    Act as an elite Process Engineer. Your job is to extract a step-by-step BPMN-style workflow from the user through conversation.
    
    Review the chat history:
    {{ chat_history }}
    
    Latest user message:
    {{ latest_user_msg }}
    
    CRITICAL RULES:
    1. If you do not have enough information to map out a complete, safe, and logical process (including sequential steps and safety hazards), return a `FollowUpQuestion`. Keep questions highly specific and conversational.
    2. If you have all the information needed, return the final `TopologyUI` graph.
    
    {{ ctx.output_format }}
  "#
}
