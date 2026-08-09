import os
import sys
import pytest
from pathlib import Path

# Add agent_fleet to Python path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_AGENT_FLEET_PATH = _REPO_ROOT / "agent_fleet"
if str(_AGENT_FLEET_PATH) not in sys.path:
    sys.path.insert(0, str(_AGENT_FLEET_PATH))

from llm_utils import get_smolagent_model

def test_get_smolagent_model_openrouter(monkeypatch):
    """Test OpenRouter model initialization."""
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("SMOLAGENTS_MODEL", "anthropic/claude-3-haiku")
    
    model = get_smolagent_model()
    
    # Check that it's initialized correctly
    # Note: Depending on whether litellm is installed, it might be LiteLLMModel or OpenAIServerModel
    model_class_name = model.__class__.__name__
    assert model_class_name in ["LiteLLMModel", "OpenAIServerModel"]
    
    if model_class_name == "LiteLLMModel":
        assert getattr(model, "model_id", "") == "openrouter/anthropic/claude-3-haiku"
    else:
        assert getattr(model, "model_id", "") == "anthropic/claude-3-haiku"

def test_get_smolagent_model_ollama(monkeypatch):
    """Test Ollama model initialization."""
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "ollama")
    monkeypatch.setenv("SMOLAGENTS_MODEL", "llama3")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    
    model = get_smolagent_model()
    
    model_class_name = model.__class__.__name__
    assert model_class_name in ["LiteLLMModel", "OpenAIServerModel"]
    
    if model_class_name == "LiteLLMModel":
        assert getattr(model, "model_id", "") == "openai/llama3"
    else:
        assert getattr(model, "model_id", "") == "llama3"

def test_get_smolagent_model_openai(monkeypatch):
    """Test OpenAI model initialization."""
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SMOLAGENTS_MODEL", "gpt-4-turbo")
    
    model = get_smolagent_model()
    
    model_class_name = model.__class__.__name__
    assert model_class_name in ["LiteLLMModel", "OpenAIServerModel"]
    
    # PROVIDER-PREFIXED ON PURPOSE — this assertion was STALE, the code was not wrong.
    # `agent_fleet/llm_utils.py` states the reason: LiteLLM's SDK needs a provider prefix on
    # `model_id` to know which backend to route to; given a BARE name it tries to resolve the model
    # against its own registry and fails. Every OpenAI-compatible upstream this repo targets (the
    # LiteLLM proxy, vLLM, real OpenAI) is reached as "openai/<model>". The old assertion demanded
    # exactly the behaviour that fix removed, so it went red on every run and was waved through.
    # Do not "restore" it.
    assert getattr(model, "model_id", "") == "openai/gpt-4-turbo"

def test_get_smolagent_model_hf(monkeypatch):
    """Test Hugging Face fallback model initialization."""
    monkeypatch.setenv("SMOLAGENTS_PROVIDER", "hf")
    monkeypatch.setenv("SMOLAGENTS_MODEL", "HuggingFaceH4/zephyr-7b-beta")
    
    model = get_smolagent_model()
    
    assert model.__class__.__name__ == "InferenceClientModel"
    assert getattr(model, "model_id", "") == "HuggingFaceH4/zephyr-7b-beta"
