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
// commit b636615 / a65e92d surfaced it.
//
// Model name is now configmap-driven via env.OLLAMA_MODEL so switching
// between gpt-oss-128k:120b (extended-context default) and gpt-oss:120b
// (standard) is a rolling restart, not a rebuild + redeploy. Same
// pattern as base_url and api_key.
client<llm> Ollama {
  provider openai
  options {
    base_url env.OLLAMA_BASE_URL
    api_key "ollama"
    model env.OLLAMA_MODEL
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
//
// Strategy is OpenRouter → OpenAI → Ollama. Ollama is the explicit
// final fallback so the cluster behaves deterministically when the
// cloud clients fail validation (no OPENROUTER_API_KEY /
// OPENAI_API_KEY set, the sandbox state). Empirically BAML 0.219
// sometimes silently routes to Ollama anyway when its strategy
// validates empty (observed in Engine F's DesignUI run d29c2672)
// and sometimes raises (observed in the supervisor's VerifyVerbChoice
// run d29c2672 before commit b636615 pinned it). Explicit fallback
// kills the ambiguity: same behavior in every pod, every cluster.
//
// VerifyVerbChoice still pins directly to `client Ollama` for the
// supervisor's hot-path verifier — keeps the verifier model
// independent of operator-chosen production reasoning models.
client<llm> MainAgent {
  provider fallback
  options {
    strategy [OpenRouter, OpenAI, Ollama]
  }
}
