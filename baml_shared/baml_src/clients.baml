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
// Sandbox ai1 host (192.168.1.119) exposes these models via Ollama:
//   gpt-oss:120b, gpt-oss-128k:120b, gpt-oss:20b, gemma4:31b, nomic-embed-text.
// The model name on the wire uses a COLON (Ollama tag convention), not a
// hyphen — the earlier "gpt-oss-120b" entry was a 404 on every request,
// which is why VerifyVerbChoice was failing with 'model not found' until
// commit b636615 surfaced it. See the post-mortem in dynamic_supervisor's
// _verify_verb_choice_with_baml graceful-degradation comments.
client<llm> Ollama {
  provider openai
  options {
    base_url env.OLLAMA_BASE_URL // Configurable via environment variable
    api_key "ollama"
    model "gpt-oss:120b"
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
