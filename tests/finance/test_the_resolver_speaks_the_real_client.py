"""The resolver against the REAL pinned `CortexDataClient`, not a double.

`test_fin_inputs_resolver.py` replaces the client at one seam; this file removes the seam. The
engine boots with the real client importable, the route builds it with exactly the kwargs
`mesh_ticketed_read` passes, and a local stdlib HTTP server plays the gateway. It pins the
outcome mapping the double only asserts: 403 -> NotEntitled, 404 -> MeshUnavailable, connection
refused -> MeshUnavailable, and what the gateway is shown (the bearer, the caller's email).

Skipped where dag-tools is not installed (the root venv). Run it in an engine-fin venv:
    PYTHONPATH=<repo> <venv>/python -m pytest -c <repo>/pyproject.toml --rootdir <repo> \
        tests/finance/test_the_resolver_speaks_the_real_client.py
"""
from __future__ import annotations

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("dag_tools.cortex_data.identity")
jwt = pytest.importorskip("jwt")
pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import seed  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
ALICE = "alice@example.com"
URN = "urn:li:dataset:(urn:li:dataPlatform:file,fin_real_client,TEST)"


class Gateway:
    def __init__(self, status: int):
        self.seen: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.seen.append({"path": self.path, "headers": dict(self.headers)})
                body = b'{"detail": "no"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def app(monkeypatch):
    for k in ("MESH_JWT_PUBLIC_KEY", "KEYCLOAK_PUBLIC_KEY", "REQUIRE_TRANSPORT_AUTH", "MESH_DEV_TOKEN",
              "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "FIN_ASSET_MAX_ROWS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    monkeypatch.setattr(engine, "DECLARED", engine._load_declared())
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller_id, **kw: True)
    monkeypatch.setenv("FIN_DATASET_URN", URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC")


def _call(gateway_url: str, monkeypatch):
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", gateway_url)
    tok = jwt.encode({"email": ALICE}, "k", algorithm="HS256")
    with TestClient(engine.app) as c:
        r = c.post("/measure/fin_tcpi", headers={"Authorization": f"Bearer {tok}"},
                   json={"params": {"program_id": seed.PROGRAM_ID}, "user_email": ALICE})
    return r, tok


@pytest.mark.parametrize("status,expect", [(403, 403), (401, 403), (404, 503), (500, 503)])
def test_the_gateways_answer_maps_to_the_resolvers_outcome(app, monkeypatch, status, expect):
    gw = Gateway(status)
    try:
        r, tok = _call(gw.url, monkeypatch)
    finally:
        gw.close()
    assert r.status_code == expect, r.text
    assert len(gw.seen) == 1
    seen = gw.seen[0]
    assert seen["path"].endswith("/authorize") and "fin_real_client" in seen["path"]
    h = {k.lower(): v for k, v in seen["headers"].items()}
    assert h["authorization"] == f"Bearer {tok}"
    assert h["x-originator-email"] == ALICE


def test_a_refused_connection_is_a_503(app, monkeypatch):
    r, _ = _call(_closed_port_url(), monkeypatch)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "asset_unavailable"
