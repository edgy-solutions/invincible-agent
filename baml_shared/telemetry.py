import os
import functools
from typing import Callable, Any

# Check for Langfuse Environment Variables
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))

# 1. Safe Decorator for smolagents, Swarms, and standard Python functions
def safe_observe(**kwargs) -> Callable:
    """Optional @observe decorator. Passes through if Langfuse is disabled."""
    if LANGFUSE_ENABLED:
        try:
            from langfuse.decorators import observe
            return observe(**kwargs)
        except ImportError:
            pass
            
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kw_args):
            return func(*args, **kw_args)
        return wrapper
    return decorator

# 2. Safe Context Updater for mem0
def safe_update_observation(input_data: Any = None, output_data: Any = None):
    if LANGFUSE_ENABLED:
        try:
            from langfuse.decorators import langfuse_context
            langfuse_context.update_current_observation(input=input_data, output=output_data)
        except ImportError:
            pass

# 3. Safe Handler for LangGraph
def get_langgraph_callbacks() -> list:
    if LANGFUSE_ENABLED:
        try:
            from langfuse.callback import CallbackHandler
            return [CallbackHandler()]
        except ImportError:
            pass
    return []

# 4. Safe Configuration for LiteLLM
def configure_litellm():
    """Configures LiteLLM to use Langfuse callbacks if enabled."""
    if LANGFUSE_ENABLED:
        os.environ["LITELLM_SUCCESS_CALLBACKS"] = "langfuse"
        os.environ["LITELLM_FAILURE_CALLBACKS"] = "langfuse"

# Auto-configure LiteLLM on import
configure_litellm()
