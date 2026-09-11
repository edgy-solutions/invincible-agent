"""engine-lg registers EVERY ratified row, proven by the wire body it actually POSTs.

WHY A CAPTURED PAYLOAD AND NOT A CALL THAT DID NOT THROW. `register_engine_to_mesh` logging a
warning and returning without raising is CORRECT — a registrar being unreachable must not stop
an engine booting. Which means its silence carries no information whatsoever. A claim resting
on "the helper did not complain" is green-by-absence, and this repo has a runbook section on
that exact line because an engine once logged fourteen `Registered` ticks with zero
registrations and booted healthy. **A payload you can read is evidence; a call that did not
throw is not.**

WHY THE POPULATION AND NOT ONE GOOD ROW. One row proves the path works. Only the count proves
nothing was SKIPPED — and skipping is the failure mode with no symptom here, because a host
missing exactly one verb is indistinguishable from a healthy one at every probe. This is the
same distinction the mesh-verb seal makes by listing the MESH's verbs rather than the host's
files: a file-derived population answers "what did we intend", and the question is "what is
reachable".

The stub mint is deliberate: Keycloak is not running in CI, and a mint failure would prove
nothing about the payload either way. What is asserted is the body — the thing a registrar
would act on.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "policy" / "graphs"


@pytest.fixture()
def stub_registrar():
    captured: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length", 0))
            captured.append({
                "path": self.path,
                "authorized": bool(self.headers.get("Authorization")),
                "body": json.loads(self.rfile.read(n) or b"{}"),
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *a):  # keep pytest output readable
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", captured
    finally:
        srv.shutdown()


@pytest.fixture()
def booted(stub_registrar, monkeypatch):
    """Boot the host through its real lifespan and return (manifests, captured POSTs)."""
    url, captured = stub_registrar
    sys.path.insert(0, str(_ROOT))
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("MESH_REGISTRAR_URL", url)
    monkeypatch.setenv("GRAPH_POLICY_DIR", str(_POLICY))
    monkeypatch.setenv("GRAPH_HOST_URL", "http://iagent-engine-lg:8098")

    from iagent_mesh.graph_manifest import load_manifests

    from agent_fleet.graph_host import main as host

    monkeypatch.setattr(host, "engine_mint", lambda **kw: (lambda: "stub-token"))

    async def go():
        async with host.lifespan(host.app):
            return sorted(host._LOADED)

    loaded = asyncio.run(go())
    return load_manifests(_POLICY), loaded, captured


def test_there_is_something_to_register():
    """POSITIVE CONTROL, first. With an empty ratified directory every assertion below is
    satisfied by a host that registers nothing at all."""
    rows = list(_POLICY.glob("*.yaml"))
    assert rows, (
        f"no ratified rows in {_POLICY} — either the seed moved or the population is empty, "
        f"and both make the coverage assertions below pass vacuously"
    )


def test_every_ratified_row_produces_a_registration(booted):
    manifests, loaded, captured = booted

    assert loaded == sorted(m.graph_id for m in manifests), (
        "the host loaded a different set of graphs than the ratified directory declares"
    )

    posted = sorted(c["body"].get("name", "<unnamed>") for c in captured)
    expected = sorted(m.name for m in manifests)
    assert posted == expected, (
        "one POST per ratified row is the claim; a row that registers nothing is a verb the "
        "mesh will never route to, on a pod that passes every probe.\n"
        f"  expected: {expected}\n  posted:   {posted}"
    )


def test_each_registration_carries_the_whole_contract(booted):
    """Named fields, not a count. A count passes when one field is swapped for another, and
    these are the ones Contract D and the eligibility gate actually read."""
    manifests, _loaded, captured = booted
    by_name = {c["body"].get("name"): c for c in captured}

    for m in manifests:
        c = by_name.get(m.name)
        assert c is not None, f"{m.graph_id} produced no registration"
        b = c["body"]
        assert c["authorized"], f"{m.graph_id} registered with NO Authorization header"
        assert b["verb_iri"] == m.verb
        assert b["input_uri"] == m.input_uri
        assert b["output_uri"] == m.output_uri
        assert b["endpoint_url"].endswith(f"/graphs/{m.graph_id}")
        assert b["arity"] == m.arity
        assert b["required_args"] == [s.name for s in m.slots if s.required]
        assert [s["name"] for s in b["slots"]] == [s.name for s in m.slots]
        # The referent is what makes the ask card and the one-option menu apply to this verb
        # unchanged; dropped, the filler renders an id-SHAPE from the slot name and the
        # resolver scores it 0.0 against its own label.
        for declared, wire in zip(m.slots, b["slots"]):
            assert wire.get("referent") == declared.referent


def test_a_host_with_no_ratified_rows_REFUSES_TO_START(tmp_path, monkeypatch):
    """The floor whose absence SHIPPED, sealed so it cannot come back.

    rev 106 rolled engine-lg with `policy/graphs/` absent from the image. `load_graphs` failed
    loud on a row it could not honour — that part was right — but not on NO ROWS, so the host
    admitted zero graphs, registered zero verbs, and answered `status: ok` to every probe. It
    took a live mesh query to notice. A graph host with no graphs is not a healthy graph host;
    it is an unroutable pod with a green light.

    The error must NAME THE DIRECTORY, because the cause is nearly always that the path is
    wrong or the content never shipped, and "no graphs" without a path sends the reader to the
    manifest instead of the image.
    """
    import sys
    sys.path.insert(0, str(_ROOT))
    empty = tmp_path / "graphs"
    empty.mkdir()
    monkeypatch.setenv("GRAPH_POLICY_DIR", str(empty))

    import importlib
    from agent_fleet.graph_host import main as host
    importlib.reload(host)

    with pytest.raises(RuntimeError) as exc:
        host.load_graphs()
    assert str(empty) in str(exc.value), "the refusal must name the directory it looked in"
    assert "ratified" in str(exc.value).lower()
