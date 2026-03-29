import os
from dotenv import load_dotenv
from smolagents import InferenceClientModel, OpenAIServerModel

# Load environment variables from .env file if it exists
load_dotenv()

def get_smolagent_model():
    """
    Factory to create a smolagents model based on environment variables.
    Supports OpenRouter (default if API key present), Ollama, and Hugging Face.
    """
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    # Default to openrouter if key is present, otherwise 'hf'
    default_provider = "openrouter" if openrouter_key else "hf"
    provider = os.getenv("SMOLAGENTS_PROVIDER", default_provider).lower()
    
    model_id = os.getenv("SMOLAGENTS_MODEL")
    
    if provider == "openrouter":
        return OpenAIServerModel(
            model_id=model_id or "anthropic/claude-3.5-sonnet", # High performance default
            api_base="https://openrouter.ai/api/v1",
            api_key=openrouter_key
        )
    elif provider == "ollama":
        # Note: In Docker, host.docker.internal reaches the host machine
        base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
        return OpenAIServerModel(
            model_id=model_id or "gpt-oss-120b",
            api_base=base_url,
            api_key="ollama" # Generic key for Ollama
        )
    elif provider == "openai":
        return OpenAIServerModel(
            model_id=model_id or "gpt-4o",
            api_key=os.getenv("OPENAI_API_KEY")
        )
    else:
        # Default to Hugging Face
        return InferenceClientModel(model_id=model_id or "Qwen/Qwen2.5-Coder-32B-Instruct")

def init_baml_client():
    """
    Configures the global BAML client dynamically based on SMOLAGENTS_PROVIDER.
    Called automatically on first import of this module by fleet services.
    """
    import logging
    try:
        from baml_client import b
        from baml_py import ClientRegistry
    except ImportError:
        logging.warning("baml_client not found; skipping BAML configuration.")
        return

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
        # BAML functions explicitly request 'MainAgent', so we must overwrite it
        # to ensure it strictly respects the SMOLAGENTS_PROVIDER dynamic variable
        cr.add_llm_client(name="MainAgent", provider="fallback", options={"strategy": [active_client]})
        b.configure(client_registry=cr)
    except Exception as e:
        logging.error(f"Failed to configure BAML client: {e}")

# Execute on module load to guarantee BAML applies it globally
init_baml_client()
