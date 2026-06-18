import os
from dotenv import load_dotenv
# Load environment variables from .env file if it exists
load_dotenv()

def get_smolagent_model():
    """
    Factory to create a smolagents model based on environment variables.
    Supports OpenRouter (default if API key present), Ollama, and Hugging Face.
    """
    from smolagents import InferenceClientModel
    try:
        from smolagents import LiteLLMModel
        USE_LITELLM = True
    except ImportError:
        from smolagents import OpenAIServerModel
        USE_LITELLM = False

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    # Default to openrouter if key is present, otherwise 'hf'
    default_provider = "openrouter" if openrouter_key else "hf"
    provider = os.getenv("SMOLAGENTS_PROVIDER", default_provider).lower()
    
    model_id = os.getenv("SMOLAGENTS_MODEL")
    
    if provider == "openrouter":
        if USE_LITELLM:
            return LiteLLMModel(
                model_id=f"openrouter/{model_id or 'anthropic/claude-3.5-sonnet'}",
                api_base="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
                temperature=0.0
            )
        return OpenAIServerModel(
            model_id=model_id or "anthropic/claude-3.5-sonnet", # High performance default
            api_base="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            temperature=0.0
        )
    elif provider == "ollama":
        # Note: In Docker, host.docker.internal reaches the host machine
        base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
        if USE_LITELLM:
            return LiteLLMModel(
                model_id=f"openai/{model_id or 'gpt-oss-120b'}",
                api_base=base_url,
                api_key="ollama", # Generic key for Ollama
                temperature=0.0
            )
        return OpenAIServerModel(
            model_id=model_id or "gpt-oss-120b",
            api_base=base_url,
            api_key="ollama", # Generic key for Ollama
            temperature=0.0
        )
    elif provider == "openai":
        # Generic OpenAI-compatible endpoint. Covers real OpenAI (no
        # base_url override needed), LiteLLM proxies (point at the
        # LiteLLM /v1 URL), vLLM (point at /v1), and any other
        # OpenAI-compat server. The protocol matters; the implementation
        # label is incidental.
        #
        # When OPENAI_BASE_URL is unset, the underlying client uses
        # OpenAI's default endpoint (api.openai.com) — preserving
        # behavior for deployments already on real OpenAI.
        openai_base_url = os.getenv("OPENAI_BASE_URL")
        openai_api_key = os.getenv("OPENAI_API_KEY") or "any"
        if USE_LITELLM:
            kwargs = dict(
                model_id=model_id or "gpt-4o",
                api_key=openai_api_key,
                temperature=0.0,
            )
            if openai_base_url:
                kwargs["api_base"] = openai_base_url
            return LiteLLMModel(**kwargs)
        kwargs = dict(
            model_id=model_id or "gpt-4o",
            api_key=openai_api_key,
            temperature=0.0,
        )
        if openai_base_url:
            kwargs["api_base"] = openai_base_url
        return OpenAIServerModel(**kwargs)
    else:
        # Default to Hugging Face
        return InferenceClientModel(model_id=model_id or "Qwen/Qwen2.5-Coder-32B-Instruct", temperature=0.0)

def init_baml_client(baml_client_instance):
    """
    Configures the global BAML client dynamically based on SMOLAGENTS_PROVIDER.
    Returns the newly configured BAML client object.
    """
    import logging
    import os
    try:
        from baml_py import ClientRegistry
    except ImportError:
        logging.warning("baml_py not found; returning unconfigured BAML client.")
        return baml_client_instance

    provider = os.getenv("SMOLAGENTS_PROVIDER", "openrouter").lower()
    
    mapping = {
        "openrouter": "OpenRouter",
        "ollama": "Ollama",
        "openai": "OpenAI"
    }
    
    active_client = mapping.get(provider, "OpenRouter")
    logging.info(f"Configuring BAML client MainAgent to use: {active_client}")
    try:
        cr = ClientRegistry()
        cr.set_primary(active_client)

        # Redefine Ollama client with the correct base URL from environment.
        #
        # IMPORTANT: this registration OVERRIDES the Ollama client declared
        # in clients.baml. The original BAML config sets ``temperature 0``
        # (see baml_shared/baml_src/clients.baml, commit 7ffd294) because
        # every BAML call in this repo is a constrained-enum classification
        # or structured JSON extraction — argmax-over-enum, not creative
        # generation. Without ``temperature: 0`` here, that setting from
        # clients.baml is silently ignored: this ClientRegistry registration
        # wins at runtime, and the model defaults to whatever Ollama applies
        # (typically 0.8). Symptom observed: TEST-1234 boundary case in
        # tests/routing/test_classify_route.py flips accept ↔ UNKNOWN
        # across runs of the routing matrix on identical input. routing-
        # baseline-v1 was lucky-deterministic, not truly temperature-0.
        #
        # Also reads OLLAMA_MODEL first so engines that aren't smolagents
        # (engine-o uses BAML only) can be configured via the obvious env
        # var. Falls back to SMOLAGENTS_MODEL for backwards compatibility.
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
        ollama_model = os.getenv("OLLAMA_MODEL") or os.getenv("SMOLAGENTS_MODEL", "gpt-oss-120b")
        cr.add_llm_client(
            name="Ollama",
            provider="openai",
            options={
                "base_url": ollama_url,
                "api_key": "ollama",
                "model": ollama_model,
                "temperature": 0,
            }
        )

        # Generic OpenAI-compatible client — covers LiteLLM, vLLM,
        # OpenRouter (when used as a plain OpenAI-compat endpoint), and
        # real OpenAI. Same rationale as the Ollama re-registration above:
        # this overrides the clients.baml default so we can point at a
        # custom base_url + key + model from env without rebuilding the
        # BAML client.
        openai_base_url = os.getenv("OPENAI_BASE_URL")
        openai_api_key = os.getenv("OPENAI_API_KEY") or "any"
        openai_model = (
            os.getenv("OPENAI_MODEL")
            or os.getenv("SMOLAGENTS_MODEL", "gpt-4o")
        )
        openai_options = {
            "api_key": openai_api_key,
            "model": openai_model,
            "temperature": 0,
        }
        if openai_base_url:
            openai_options["base_url"] = openai_base_url
        cr.add_llm_client(
            name="OpenAI",
            provider="openai",
            options=openai_options,
        )

        # BAML functions explicitly request 'MainAgent', so we must overwrite it
        # to ensure it strictly respects the SMOLAGENTS_PROVIDER dynamic variable
        cr.add_llm_client(name="MainAgent", provider="fallback", options={"strategy": [active_client]})
        return baml_client_instance.with_options(client_registry=cr)
    except Exception as e:
        logging.error(f"Failed to configure BAML client: {e}")
        return baml_client_instance
