"""`tests/_responder_identity.py` must tell absent, foreign and expected apart.

Pure: the only network traffic is to a throwaway `http.server` this file starts itself on an
ephemeral loopback port, plus one optional positive-control arm against the real Engine O app
(imported in-process via a short-lived subprocess, never over a socket).

Each case matches a state the measured incident actually produced:
  - absent:   nothing listening (closed port) — the ordinary "no port-forward" case.
  - foreign:  something listens but its response does not match the real producer's shape —
              this is the port-collision case (`localhost:8084` answered by an unrelated
              container's Prometheus `/health`, and by a 405 for POST routes).
  - expected: the real producer's own response shape, in both its documented postures
              (Engine O's 200-ready and 503-not-ready).

The `{"status": "ok"}` case is the control that matters most: it is valid JSON, same as the
real producer's body, so it proves the predicate discriminates on CONTENT (the `jena_configured`
/ `missing`+`detail` keys), not merely on "is this JSON at all".
"""
from __future__ import annotations

import http.server
import json
import re
import socket
import subprocess
import sys
import threading
import contextlib
from pathlib import Path

import pytest

from tests._responder_identity import is_engine_o, is_weaviate, probe

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _ScriptedHandler(http.server.BaseHTTPRequestHandler):
    """Serves one fixed (status, content_type, body) response to any GET or POST."""

    response: tuple[int, str, bytes] = (200, "text/plain", b"")

    def _respond(self) -> None:
        status, content_type, body = self.response
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming convention)
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def log_message(self, *args) -> None:  # silence — the test output doesn't need access logs
        pass


@contextlib.contextmanager
def _scripted_server(status: int, content_type: str, body: bytes):
    """Start a throwaway HTTP server on an ephemeral loopback port, serving one scripted response."""
    handler_cls = type("_Handler", (_ScriptedHandler,), {"response": (status, content_type, body)})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _closed_port_url() -> str:
    """Bind a socket to get an unused ephemeral port, then close it — nothing is listening there."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------------------------
# is_engine_o
# --------------------------------------------------------------------------------------------

def test_prometheus_text_plain_200_is_foreign():
    body = b"# HELP up 1\n# TYPE up gauge\nup 1\n"
    with _scripted_server(200, "text/plain", body) as url:
        identity = probe(url, "/health", is_engine_o, timeout=2.0)
    assert identity.state == "foreign"


def test_405_is_foreign():
    with _scripted_server(405, "text/plain", b"Method Not Allowed") as url:
        identity = probe(url, "/health", is_engine_o, timeout=2.0)
    assert identity.state == "foreign"


def test_json_ok_without_jena_configured_is_foreign():
    """The control: valid JSON, same shape class as the real body, but missing the
    discriminating key — proves the predicate reads CONTENT, not just "is this JSON"."""
    body = json.dumps({"status": "ok"}).encode()
    with _scripted_server(200, "application/json", body) as url:
        identity = probe(url, "/health", is_engine_o, timeout=2.0)
    assert identity.state == "foreign"


def test_engine_o_200_shape_is_expected():
    body = json.dumps({"status": "ok", "jena_configured": True, "neo4j_configured": True}).encode()
    with _scripted_server(200, "application/json", body) as url:
        identity = probe(url, "/health", is_engine_o, timeout=2.0)
    assert identity.state == "expected"


def test_engine_o_503_shape_is_expected():
    body = json.dumps({
        "status": "not-ready",
        "detail": "deploy fault: JENA_ENDPOINT is not declared — engine-o will not substitute "
                   "a default for it. Declare it, or declare it EMPTY.",
        "missing": ["JENA_ENDPOINT"],
    }).encode()
    with _scripted_server(503, "application/json", body) as url:
        identity = probe(url, "/health", is_engine_o, timeout=2.0)
    assert identity.state == "expected"


def test_closed_port_is_absent():
    url = _closed_port_url()
    identity = probe(url, "/health", is_engine_o, timeout=1.0)
    assert identity.state == "absent"


# --------------------------------------------------------------------------------------------
# is_weaviate
# --------------------------------------------------------------------------------------------

def test_weaviate_foreign_json_without_version_and_modules():
    body = json.dumps({"status": "ok"}).encode()
    with _scripted_server(200, "application/json", body) as url:
        identity = probe(url, "/v1/meta", is_weaviate, timeout=2.0)
    assert identity.state == "foreign"


def test_weaviate_expected_shape():
    body = json.dumps({"version": "1.19.0", "modules": {}, "hostname": "http://[::]:8080"}).encode()
    with _scripted_server(200, "application/json", body) as url:
        identity = probe(url, "/v1/meta", is_weaviate, timeout=2.0)
    assert identity.state == "expected"


# --------------------------------------------------------------------------------------------
# Positive control against the real producer — Engine O's own /health handler, imported
# in-process (via a short-lived subprocess, so a slow or failing import cannot stall or crash
# this test file) with no network beyond that in-process call.
# --------------------------------------------------------------------------------------------

_PRODUCER_PROBE_SCRIPT = """
import json, sys
try:
    from fastapi.testclient import TestClient
    from agent_fleet.ontology_service.main import app
    client = TestClient(app)
    r = client.get("/health")
    print(json.dumps({
        "status": r.status_code,
        "content_type": r.headers.get("content-type", ""),
        "body": r.text,
    }))
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
    sys.exit(1)
"""


def test_is_engine_o_accepts_the_real_producers_health_response():
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PRODUCER_PROBE_SCRIPT],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("importing agent_fleet.ontology_service.main took >20s in this venv — skipped")
        return

    if proc.returncode != 0:
        detail = (proc.stdout or proc.stderr or "").strip()[-300:]
        pytest.skip(
            f"could not import/run agent_fleet.ontology_service.main in this venv: {detail}"
        )
        return

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload["error"]
    assert is_engine_o(payload["status"], payload["content_type"], payload["body"].encode()), (
        f"the real Engine O /health response (status={payload['status']}, "
        f"body={payload['body']!r}) was not recognized by is_engine_o — the predicate has "
        f"drifted from its producer"
    )


# --------------------------------------------------------------------------------------------
# ONE source for the default — a seal, derived not listed.
#
# Chris ruled 2026-10-06: the routing suite's default target is a non-colliding port
# (http://localhost:18084) and it lives in EXACTLY ONE place, `tests/_responder_identity.py`'s
# `ENGINE_O_TEST_DEFAULT` / `routing_base_url()`. Before this, five modules plus this suite's
# conftest each restated `os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")`
# independently, which is exactly how the port drifted out of sync with what the port-forward
# instructions said. This scans tests/**/*.py CODE (not comments or docstrings) and fails if
# any file OTHER than `tests/_responder_identity.py` spells a default for the env var itself.
#
# The guard is CODE, not a sentence about the guard — same shape as
# `tests/test_the_stub_harness_puts_sys_modules_back.py`'s `_DEFERRAL` pattern, and for the
# same reason: a matcher that reads prose as code (or vice versa) reports a population that
# never existed.
# --------------------------------------------------------------------------------------------
_SPELLS_ROUTING_DEFAULT = re.compile(
    r'^[^#\n]*os\.(?:getenv|environ\.get)\(\s*["\']ROUTING_TEST_BASE_URL["\']',
    re.M,
)

#: The one file allowed to spell the default — it IS the default's home.
_ALLOWED_DEFAULT_HOME = "tests/_responder_identity.py"


def test_THE_ROUTING_DEFAULT_MATCHER_READS_CODE_AND_NOT_PROSE():
    """⚠ POSITIVE CONTROL FOR THE SEAL'S MATCHER, in both directions — see
    `test_THE_DEFERRAL_MATCHER_READS_CODE_AND_NOT_PROSE` in the stub-harness module for why this
    is a required arm and not a comment: a matcher that silently stops matching reports a
    population that shrank, not a population that never changed."""
    assert _SPELLS_ROUTING_DEFAULT.search(
        '_BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")\n'
    )
    assert _SPELLS_ROUTING_DEFAULT.search(
        "BASE_URL = os.environ.get('ROUTING_TEST_BASE_URL', 'http://localhost:18084')\n"
    ), "the os.environ.get spelling did not match"
    assert not _SPELLS_ROUTING_DEFAULT.search(
        '# _BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")\n'
    ), "a comment matched"
    assert not _SPELLS_ROUTING_DEFAULT.search(
        "    ROUTING_TEST_BASE_URL=http://engine-o.staging.local:8084 \\\n"
    ), "a shell-style docstring example (no os.getenv call) matched"
    assert not _SPELLS_ROUTING_DEFAULT.search(
        'os.getenv("ROUTING_TEST_PROBE_TIMEOUT", "1.5")\n'
    ), "a DIFFERENT env var matched"


def test_ONLY_RESPONDER_IDENTITY_SPELLS_THE_ROUTING_DEFAULT():
    """A MEASURED SEAL. `tests/_responder_identity.py` is the one source for
    ROUTING_TEST_BASE_URL's default; every other file reads it via `routing_base_url()`
    (or the module's `ENGINE_O_TEST_DEFAULT` constant) instead of restating the URL."""
    repo = _REPO_ROOT
    offenders = {
        p.relative_to(repo).as_posix(): m.group(0).strip()
        for p in (repo / "tests").rglob("*.py")
        if p.relative_to(repo).as_posix() != _ALLOWED_DEFAULT_HOME
        # THIS FILE IS EXCLUDED FROM ITS OWN SCAN, stated rather than quietly arranged: its
        # positive-control strings spell the call on purpose (same as the stub-harness ratchet).
        if p.resolve() != Path(__file__).resolve()
        for m in [_SPELLS_ROUTING_DEFAULT.search(p.read_text(encoding="utf-8", errors="replace"))]
        if m
    }
    assert not offenders, (
        f"a default for ROUTING_TEST_BASE_URL is spelled outside "
        f"{_ALLOWED_DEFAULT_HOME}:\n" + "\n".join(f"  {f}: {line}" for f, line in offenders.items())
    )
