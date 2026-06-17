"""
Live LLM connectivity smoke test for Engine A (restate-analyst) and Engine E
(neo4j-expert).

Unlike test_engine_images.py — which is hermetic and offline — this suite
proves the *built image* can reach and drive a real Ollama endpoint through
the stack's own abstraction:

    llm_utils.get_smolagent_model()  ->  LiteLLMModel  ->  Ollama /v1

It does NOT mock anything. It runs a one-shot inside each container that
builds the model object exactly as the engines do, sends a trivial prompt,
and asserts a real completion comes back. This is the smallest e2e slice
that exercises the LLM path without needing Restate / Weaviate / Engine O.

Configuration (env vars, with defaults for the dev LAN):
    OLLAMA_TEST_BASE_URL   default: http://ai1:11434/v1
    OLLAMA_TEST_HOST_IP    default: 192.168.1.119   (for --add-host; the
                           container can't resolve a bare LAN hostname)
    OLLAMA_TEST_MODEL      default: gpt-oss:120b
    ENGINE_IMAGE_TAG       default: latest

Skips cleanly (not fails) when Docker is unavailable, an image isn't pulled,
or the Ollama endpoint isn't reachable from this host — so CI and dev boxes
without LAN access to the endpoint are unaffected.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_REGISTRY = "ghcr.io/edgy-solutions/invincible-agent"
_TAG = os.getenv("ENGINE_IMAGE_TAG", "latest")

_OLLAMA_BASE_URL = os.getenv("OLLAMA_TEST_BASE_URL", "http://ai1:11434/v1")
_OLLAMA_HOST_IP = os.getenv("OLLAMA_TEST_HOST_IP", "192.168.1.119")
_OLLAMA_MODEL = os.getenv("OLLAMA_TEST_MODEL", "gpt-oss:120b")

_ENGINES = {
    "engine-a": f"{_REGISTRY}/restate-analyst:{_TAG}",
    "engine-e": f"{_REGISTRY}/neo4j-expert:{_TAG}",
}

_PY = "/app/.venv/bin/python"
# gpt-oss is a reasoning model on a 120B param APU — a trivial reply still
# takes ~30s. Give the docker run generous headroom.
_RUN_TIMEOUT = 240


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------
def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=15, check=True,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _image_present(image: str) -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, timeout=15,
        ).returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _ollama_reachable() -> bool:
    """Pre-flight: can THIS host reach the Ollama endpoint? If not, the
    container can't either — skip rather than fail."""
    try:
        with urllib.request.urlopen(f"{_OLLAMA_BASE_URL}/models", timeout=8) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


pytestmark = [
    pytest.mark.skipif(
        not _docker_available(),
        reason="Docker not available — LLM connectivity smoke test skipped.",
    ),
    pytest.mark.skipif(
        not _ollama_reachable(),
        reason=f"Ollama endpoint {_OLLAMA_BASE_URL} not reachable from this "
               f"host — LLM connectivity smoke test skipped.",
    ),
]


def _require_image(image: str) -> None:
    if not _image_present(image):
        pytest.skip(f"Image {image} not present locally. Pull it first:\n"
                    f"    docker pull {image}")


# ---------------------------------------------------------------------------
# Smoke test — get_smolagent_model() drives a real completion
# ---------------------------------------------------------------------------
_SMOKE_CODE = f"""
import os
os.environ['SMOLAGENTS_PROVIDER'] = 'ollama'
os.environ['SMOLAGENTS_MODEL']    = {_OLLAMA_MODEL!r}
os.environ['OLLAMA_BASE_URL']     = {_OLLAMA_BASE_URL!r}

import llm_utils
model = llm_utils.get_smolagent_model()
print('MODEL_TYPE=' + type(model).__name__)

# Invoke exactly as the engines' CodeAgent would, through the stack's own
# model object. Generous max_tokens — gpt-oss is a reasoning model and will
# return empty content if the token budget is consumed by internal reasoning.
resp = model(
    [{{'role': 'user', 'content': 'Reply with exactly one word: PONG'}}],
    max_tokens=2048,
)
content = getattr(resp, 'content', resp)
assert content, f'empty completion content: {{content!r}}'
assert 'PONG' in str(content).upper(), f'unexpected completion: {{content!r}}'
print('LLM_SMOKE_OK')
"""


@pytest.mark.parametrize("engine", list(_ENGINES), ids=list(_ENGINES))
def test_engine_can_drive_live_llm(engine):
    """The built image must reach the Ollama endpoint and get a real
    completion back through llm_utils.get_smolagent_model()."""
    image = _ENGINES[engine]
    _require_image(image)

    # --add-host: the container has no resolver for a bare LAN hostname like
    # "ai1". In the real k8s cluster this is a Service with cluster DNS;
    # here we inject the mapping so the test mirrors the stack's code path
    # (env var stays a hostname, not a raw IP).
    parsed = urlparse(_OLLAMA_BASE_URL)
    add_host_args = []
    if parsed.hostname and _OLLAMA_HOST_IP:
        add_host_args = ["--add-host", f"{parsed.hostname}:{_OLLAMA_HOST_IP}"]

    cmd = (
        ["docker", "run", "--rm"]
        + add_host_args
        + ["--entrypoint", _PY, image, "-c", _SMOKE_CODE]
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_RUN_TIMEOUT
    )

    assert result.returncode == 0, (
        f"{engine} LLM smoke failed (exit {result.returncode})\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "LLM_SMOKE_OK" in result.stdout, (
        f"{engine}: smoke marker missing.\nSTDOUT:\n{result.stdout}"
    )
    # Sanity: confirm it really went through the stack's LiteLLM path.
    assert "MODEL_TYPE=LiteLLMModel" in result.stdout, (
        f"{engine}: expected LiteLLMModel, got:\n{result.stdout}"
    )
