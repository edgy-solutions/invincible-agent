"""A Contract D rejection is TWO facts, and the registrar is the only party that can tell
them apart.

WHY THIS EXISTS. `missing: [...]` is returned in two situations whose repairs are opposites:

  * the class graph is not populated YET — an engine booted ahead of the ontology ingest.
    Becomes true on its own. The caller should RETRY.
  * these classes will NEVER exist — no TTL declares them. A human must fix the ontology.
    Retrying is an infinite loop against a real defect.

The ENGINE cannot distinguish them: from inside one rejection they are the same payload. So
ADR-0006's addendum ruled 422 PERMANENT — right for the second case, and the reason a work
cluster sat unrouted on 2026-08-14 until someone restarted a pod by hand. Both live instances
existed that day: nine catalog verbs that a restart fixed, and `mesh#DispositionReview`, whose
class no source declared at all.

The registrar sees both the requested URIs AND the state of the graph, so it decides, and says
which it means in the status code. These pins hold that discrimination in place — in BOTH
directions, because a discriminant that only ever answers one way is not a discriminant.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


SENTINEL = "http://invincible-agent/idp#Dataset"
WANTED = "http://invincible-agent/mesh#DispositionReview"


def _load_registrar(monkeypatch, *, present: set[str], sentinel: str = SENTINEL):
    """Import the registrar with Neo4j stubbed to a known class-graph state.

    `present` is the set of :OntologyClass uris the graph contains. No database, no
    network — the discriminant is pure logic over two queries and that is what we pin.
    """
    # Stub `neo4j` before import so module-level `from neo4j import GraphDatabase` binds.
    fake_neo4j = types.ModuleType("neo4j")

    class _Result:
        def __init__(self, record):
            self._record = record

        def single(self):
            return self._record

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, cypher, **params):
            if "uris" in params:  # the missing-URI probe
                return _Result({"missing": [u for u in params["uris"] if u not in present]})
            # the sentinel probe
            return _Result({"present": params["uri"] in present})

    class _Driver:
        def session(self):
            return _Session()

    fake_neo4j.GraphDatabase = types.SimpleNamespace(driver=lambda *a, **k: _Driver())
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)
    monkeypatch.setenv("MESH_REGISTRAR_SUBSTRATE_SENTINEL", sentinel)

    sys.modules.pop("agent_fleet.mesh_registrar.main", None)
    mod = importlib.import_module("agent_fleet.mesh_registrar.main")
    monkeypatch.setattr(mod, "_get_neo4j_driver", lambda: _Driver())
    return mod


# ---------------------------------------------------------------------------
# The two facts
# ---------------------------------------------------------------------------
def test_empty_graph_is_NOT_ready__the_boot_race(monkeypatch):
    """Nothing ingested yet. The sentinel is absent, so `missing` means 'not yet'."""
    mod = _load_registrar(monkeypatch, present=set())
    cd = mod._contract_d_check(WANTED, WANTED)
    assert cd["ok"] is False
    assert cd["substrate_ready"] is False, (
        "an empty class graph was reported READY — every boot-race registration would "
        "get a permanent 422 for a class that is seconds from existing"
    )


def test_populated_graph_IS_ready__the_declaration_gap(monkeypatch):
    """The ingest finished (sentinel present) and the class still is not there. That is
    mesh#DispositionReview: no TTL declared it, and no restart ever will."""
    mod = _load_registrar(monkeypatch, present={SENTINEL})
    cd = mod._contract_d_check(WANTED, WANTED)
    assert cd["ok"] is False
    assert cd["substrate_ready"] is True, (
        "a populated graph was reported NOT ready — a real declaration gap would be "
        "retried forever instead of raising its permanent alarm"
    )


def test_the_happy_path_is_unchanged(monkeypatch):
    mod = _load_registrar(monkeypatch, present={SENTINEL, WANTED})
    cd = mod._contract_d_check(WANTED, WANTED)
    assert cd["ok"] is True and cd["missing"] == []


# ---------------------------------------------------------------------------
# Why a SENTINEL and not a count — the definition that looks obvious and is wrong
# ---------------------------------------------------------------------------
def test_a_PARTIALLY_ingested_graph_is_not_ready(monkeypatch):
    """THE PIN THAT RULES OUT count(:OntologyClass) > 0.

    A count check is satisfied by the FIRST class to land, so it reports READY throughout
    the rest of the ingest — narrowing the race window instead of closing it, and handing
    a permanent 422 to anything registering mid-load. Presence of a SENTINEL means the
    ingest reached its TERMINAL state. Here the graph is non-empty and still not ready.
    """
    mod = _load_registrar(
        monkeypatch,
        present={"http://invincible-agent/mesh#Request",
                 "http://invincible-agent/mesh#Response"},  # ingest in flight; no sentinel
    )
    cd = mod._contract_d_check(WANTED, WANTED)
    assert cd["substrate_ready"] is False, (
        "a non-empty but incompletely-ingested graph was called ready — this is exactly "
        "the count>0 definition the sentinel exists to avoid"
    )


def test_the_DEFAULT_sentinel_agrees_with_the_deploy_hooks_sentinel():
    """THE PIN ON THE CHOICE, not the mechanism.

    Every other test here supplies the sentinel explicitly, so they verify the LOGIC given
    a sentinel and cannot catch a bad one. A mutation proved it: repointing the default at
    `mesh#Request` — a class that lands EARLY in the ingest, which is precisely the defect
    `count(:OntologyClass) > 0` has — left all of them green.

    What makes a sentinel terminal is not provable from source. What IS enforceable is that
    the two components asking the same question answer it the same way: helm's re-register
    hook waits on `primeSubstrate.reregisterEngines.sentinelUri` before restarting engines,
    and the registrar decides ready/not-ready here. If those drift, the hook releases the
    engines at one moment and the registrar calls the substrate ready at another — the race
    reopens in the gap between them, and nothing else in the suite would notice.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    values = (root / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8")
    m = re.search(r"^\s*sentinelUri:\s*[\"']([^\"']+)[\"']", values, re.M)
    assert m, "helm's reregisterEngines.sentinelUri not found — this pin is measuring nothing"
    helm_sentinel = m.group(1)

    # Read the registrar's DEFAULT from source, not from the imported module. The tests
    # above set MESH_REGISTRAR_SUBSTRATE_SENTINEL and the constant binds at import time, so
    # an already-imported module reports whichever env a previous test happened to leave —
    # which silently turns this pin into a tautology. (It did: a mutation repointing the
    # default at mesh#Request survived the module-attribute version of this assertion.)
    src = (root / "agent_fleet" / "mesh_registrar" / "main.py").read_text(encoding="utf-8")
    d = re.search(
        r"_SUBSTRATE_SENTINEL_URI\s*=\s*os\.getenv\(\s*[\"'][^\"']+[\"']\s*,\s*[\"']([^\"']+)[\"']",
        src,
    )
    assert d, "registrar's _SUBSTRATE_SENTINEL_URI default not found — pin is measuring nothing"
    registrar_sentinel = d.group(1)

    assert registrar_sentinel == helm_sentinel, (
        f"registrar sentinel {registrar_sentinel!r} != helm sentinel {helm_sentinel!r}. "
        "These answer the SAME question — 'has the ontology ingest reached its terminal "
        "state' — and a disagreement reopens the boot race in the window between them."
    )


def test_the_escape_hatch_is_explicit_and_restores_the_old_behaviour(monkeypatch):
    """An empty sentinel setting disables the discrimination (always-permanent, the
    pre-2026-08-14 behaviour) for a deployment whose ontology has no idp layer. It must be
    something an operator TURNS ON, never a silent default."""
    mod = _load_registrar(monkeypatch, present=set(), sentinel="")
    cd = mod._contract_d_check(WANTED, WANTED)
    assert cd["substrate_ready"] is True
    assert cd["sentinel"] == ""


# ---------------------------------------------------------------------------
# The status codes — the discrimination is only real if it reaches the caller
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "present, expected_status, why",
    [
        (set(), 503, "not-ready must be RETRYABLE — the SDK retries >=500 with backoff"),
        ({SENTINEL}, 422, "a real declaration gap must stay PERMANENT and loud"),
    ],
)
def test_the_status_code_carries_the_distinction(monkeypatch, present, expected_status, why):
    """A discriminant the caller cannot read is a comment. The SDK branches on the status
    code alone (registration_transport.py: 422 -> permanent, 5xx -> retry), so the code IS
    the interface."""
    from fastapi import HTTPException

    mod = _load_registrar(monkeypatch, present=present)
    manifest = mod.RegistrationManifest(
        name="engine_a_propose_disposition",
        description="d",
        verb_iri="mesh:proposeDisposition",
        input_uri=WANTED,
        output_uri=WANTED,
        endpoint_url="http://example.invalid/x",
        owner_persona="SUSTAINMENT_ENGINEER",
    )
    with pytest.raises(HTTPException) as exc:
        mod.register(manifest)
    assert exc.value.status_code == expected_status, why
