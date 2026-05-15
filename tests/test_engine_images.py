"""
Container-level validation for Engine A (restate-analyst) and Engine E
(neo4j-expert).

These tests exercise the *built images* — not the source tree — to prove the
two fixes from the "bake spaCy model + harden mem0" change actually made it
into the artifacts the cluster runs:

1. spaCy ``en_core_web_sm`` is embedded in the image and loads with
   networking fully disabled (``--network none``). This is the real
   air-gapped-cluster scenario: mem0ai[nlp] must NOT try to fetch the model
   from raw.githubusercontent.com at runtime.

2. The shared ``utils.mem0_utils`` module is present with the
   ``get_mem0_memory`` singleton and the ``Mem0CompatibleWeaviate`` adapter.

3. The container boots, Hypercorn binds its port, and ``/health`` responds —
   confirming the lifespan does no blocking network I/O at startup.

Requirements: Docker, plus the images pulled locally:
    docker pull ghcr.io/edgy-solutions/invincible-agent/restate-analyst:latest
    docker pull ghcr.io/edgy-solutions/invincible-agent/neo4j-expert:latest

Tests skip cleanly (not fail) when Docker or an image is unavailable, so a
normal ``pytest`` run on a dev box without the images is unaffected. Override
the tag under test with ENGINE_IMAGE_TAG (default: ``latest``).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest

# ---------------------------------------------------------------------------
# Image matrix
# ---------------------------------------------------------------------------
_REGISTRY = "ghcr.io/edgy-solutions/invincible-agent"
_TAG = os.getenv("ENGINE_IMAGE_TAG", "latest")

_ENGINES = {
    "engine-a": {
        "image": f"{_REGISTRY}/restate-analyst:{_TAG}",
        "container_port": 8081,
        "health_engine_field": "restate_analyst",
        "spacy_phrase": "rotor wear analysis",
    },
    "engine-e": {
        "image": f"{_REGISTRY}/neo4j-expert:{_TAG}",
        "container_port": 8086,
        "health_engine_field": "E",
        "spacy_phrase": "hydraulic pump failure",
    },
}

_PY = "/app/.venv/bin/python"
_DOCKER_RUN_TIMEOUT = 120
_HEALTH_BOOT_TIMEOUT = 45  # seconds to wait for /health to come up


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------
def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=15,
            check=True,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _image_present(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker not available — engine image validation skipped.",
)


def _require_image(image: str) -> None:
    if not _image_present(image):
        pytest.skip(
            f"Image {image} not present locally. Pull it first:\n"
            f"    docker pull {image}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_oneshot(image: str, py_code: str, network_none: bool = False) -> str:
    """Run a one-shot python snippet inside the image, return stdout.

    Raises AssertionError with captured stderr on non-zero exit.
    """
    cmd = ["docker", "run", "--rm"]
    if network_none:
        cmd += ["--network", "none"]
    cmd += ["--entrypoint", _PY, image, "-c", py_code]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_DOCKER_RUN_TIMEOUT
    )
    assert result.returncode == 0, (
        f"one-shot command failed (exit {result.returncode})\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _poll_health(url: str, timeout: int) -> dict:
    """Poll a /health URL until it returns 200 JSON or the timeout elapses."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, ValueError) as e:
            last_err = e
        time.sleep(1.0)
    raise AssertionError(f"/health never came up at {url} within {timeout}s "
                         f"(last error: {last_err})")


# ---------------------------------------------------------------------------
# Test 1 — spaCy model embedded and loads OFFLINE
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("engine", list(_ENGINES), ids=list(_ENGINES))
def test_spacy_model_embedded_offline(engine):
    """en_core_web_sm must load with networking fully disabled.

    This is the air-gapped-cluster scenario. Before the fix, mem0ai[nlp]
    tried to download the model from raw.githubusercontent.com on first use
    and crashed the request.
    """
    cfg = _ENGINES[engine]
    _require_image(cfg["image"])

    phrase = cfg["spacy_phrase"]
    code = (
        "import spacy; "
        "nlp = spacy.load('en_core_web_sm'); "
        f"doc = nlp({phrase!r}); "
        "print(','.join(t.lemma_ for t in doc))"
    )
    out = _run_oneshot(cfg["image"], code, network_none=True).strip()

    # Every token should have produced a lemma — proves the model is real,
    # not a stub, and that pipeline components loaded.
    lemmas = out.split(",")
    assert len(lemmas) == len(phrase.split()), (
        f"expected {len(phrase.split())} lemmas, got {lemmas!r}"
    )
    assert all(lemmas), f"empty lemma in output: {lemmas!r}"


# ---------------------------------------------------------------------------
# Test 2 — shared mem0_utils module is in the image
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("engine", list(_ENGINES), ids=list(_ENGINES))
def test_mem0_utils_present(engine):
    """utils.mem0_utils must import with the singleton + adapter symbols.

    Confirms the fleet-wide refactor (shared mem0/Weaviate plumbing) actually
    shipped in the artifact, not just in the source tree.
    """
    cfg = _ENGINES[engine]
    _require_image(cfg["image"])

    code = (
        "import sys; sys.path.insert(0, '/app'); "
        "import utils.mem0_utils as m; "
        "assert hasattr(m, 'get_mem0_memory'), 'missing get_mem0_memory'; "
        "assert hasattr(m, 'Mem0CompatibleWeaviate'), 'missing Mem0CompatibleWeaviate'; "
        "import inspect; "
        "assert inspect.iscoroutinefunction(m.get_mem0_memory), "
        "'get_mem0_memory must be async'; "
        "print('mem0_utils OK')"
    )
    out = _run_oneshot(cfg["image"], code, network_none=True).strip()
    assert out == "mem0_utils OK", f"unexpected output: {out!r}"


# ---------------------------------------------------------------------------
# Test 3 — container boots and /health responds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("engine", list(_ENGINES), ids=list(_ENGINES))
def test_container_boots_and_health(engine):
    """The image must boot, bind its port, and serve /health.

    The lifespan must not perform blocking network I/O — mem0 / Weaviate are
    lazily acquired on first request, so /health comes up even with no
    Weaviate, Restate, or LLM backend reachable.
    """
    cfg = _ENGINES[engine]
    _require_image(cfg["image"])

    name = f"{engine}-pytest-{uuid.uuid4().hex[:8]}"
    host_port = _free_port()
    container_port = cfg["container_port"]

    run = subprocess.run(
        [
            "docker", "run", "-d", "--name", name,
            "-p", f"{host_port}:{container_port}",
            cfg["image"],
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, f"docker run failed: {run.stderr}"

    try:
        health = _poll_health(
            f"http://localhost:{host_port}/health", _HEALTH_BOOT_TIMEOUT
        )
        assert health.get("status") == "ok", f"unexpected /health body: {health}"
        assert health.get("engine") == cfg["health_engine_field"], (
            f"unexpected engine field: {health}"
        )
    finally:
        subprocess.run(["docker", "rm", "-f", name],
                       capture_output=True, timeout=30)
