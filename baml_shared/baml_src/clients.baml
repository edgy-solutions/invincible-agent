// =============================================================================
// Polyglot Agentic Data Mesh — BAML Client Definitions
// =============================================================================

// --- OpenRouter (Cloud-native Qwen/Thinker) ---
client<llm> OpenRouter {
  provider openai
  options {
    base_url "https://openrouter.ai/api/v1"
    api_key env.OPENROUTER_API_KEY
    model "google/gemini-3-flash-preview" // Updated per user request
  }
}

// --- Ollama (Local LLM Deployment) ---
client<llm> Ollama {
  provider openai
  options {
    base_url env.OLLAMA_BASE_URL // Configurable via environment variable
    api_key "ollama"
    model "gpt-oss-120b" // Updated to GPT-OSS-120B
  }
}

// --- OpenAI (Native Fallback) ---
client<llm> OpenAI {
  provider openai
  options {
    model "gpt-4o"
    api_key env.OPENAI_API_KEY
  }
}

// --- Main Mesh Brain ---
// This acts as the single point of configuration for all agents.
// Switch the fallback order or primary client here.
client<llm> MainAgent {
  provider fallback
  options {
    strategy [OpenRouter, OpenAI] // Primary OpenRouter, fallback to OpenAI
  }
}
