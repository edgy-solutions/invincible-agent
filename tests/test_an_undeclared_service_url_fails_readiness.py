"""RULED 2026-09-11 — a missing service-URL ConfigMap entry is a DEPLOY fault and fails readiness.

It must NOT fall back to an in-cluster address that happens to work. That is the fail-open
default in its quietest form, and the census is what makes it expensive:
`gateway._fleet_version_targets()` DERIVES the fleet by scanning these variables, so with a
fallback an undeclared service still gets asked at the hardcoded address, still answers, and
still reports a REAL sha. **The census prints a green row for an address that exists nowhere in
the chart**, and the day the service moves the map is fiction with a green check beside it.

THREE VARIABLES CARRIED DEFAULTS — `ONTOLOGY_SERVICE_URL` (engine-o), `PRESENTATION_AGENT_SVC_URL`
(engine-f), `DATAHUB_WRAPPER_URL` (engine-d). They are the three the aggregator reads by name
rather than by the `ENGINE_*_PUBLIC_URL` convention, which is why seal 13 could not see them and
why they needed the check more than the eight that follow the convention.

AND `/health` COULD NOT EXPRESS THE FAILURE. It returned `{"status": "ok"}` unconditionally — a
probe whose only reachable value is the healthy one is not a probe. Same defect engine-lg
shipped; see docs/principles/a-host-with-nothing-admitted-is-not-ready.md.

Run: uv run --frozen pytest tests/test_an_undeclared_service_url_fails_readiness.py -v
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

#: The three, with the engine each one reaches.
_REQUIRED = {
    "ONTOLOGY_SERVICE_URL": "engine-o",
    "PRESENTATION_AGENT_SVC_URL": "engine-f",
    "DATAHUB_WRAPPER_URL": "engine-d",
}


def _reimport(monkeypatch, **env):
    """Re-import the gateway with a controlled environment.

    Module-level constants are read at import, so the env has to be set BEFORE the import or
    the test measures whatever the developer's shell happened to hold — which is the
    green-belongs-to-a-SHA-not-a-directory failure wearing an env var.
    """
    for k in _REQUIRED:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import iagent.gateway as gw

    return importlib.reload(gw)


def test_a_declared_url_is_used_verbatim(monkeypatch):
    """The working path. Declaring it must still work, or the fix is just breakage."""
    gw = _reimport(monkeypatch, ONTOLOGY_SERVICE_URL="http://declared-o:9999")
    assert gw._DAGSONTOLOGY_SVC_URL == "http://declared-o:9999"
    assert "ONTOLOGY_SERVICE_URL" not in gw._UNDECLARED_SERVICE_URLS


def test_an_undeclared_url_yields_EMPTY_not_a_fallback_address(monkeypatch):
    """THE RULING. No hardcoded in-cluster address may stand in for a missing declaration.

    Asserted on the VALUE rather than only on readiness, because a fallback that also recorded
    itself as undeclared would pass a readiness-only check while still reaching the service.
    """
    gw = _reimport(monkeypatch)
    assert gw._DAGSONTOLOGY_SVC_URL == "", (
        f"undeclared ONTOLOGY_SERVICE_URL fell back to {gw._DAGSONTOLOGY_SVC_URL!r} — the "
        f"census would then report a real sha from an address the chart never declared"
    )
    assert gw._PRESENTATION_AGENT_SVC_URL == ""


@pytest.mark.asyncio
async def test_readiness_REFUSES_and_names_the_variable(monkeypatch):
    """A 503 that does not say which variable is a crash with better manners."""
    gw = _reimport(monkeypatch)
    resp = await gw.health()
    assert getattr(resp, "status_code", 200) == 503, "readiness did not refuse"
    body = resp.body.decode()
    assert "ONTOLOGY_SERVICE_URL" in body and "PRESENTATION_AGENT_SVC_URL" in body
    assert "deploy fault" in body, "the refusal does not say whose fault it is"


@pytest.mark.asyncio
async def test_readiness_PASSES_when_all_three_are_declared(monkeypatch):
    """THE CONTROL, and without it 'refuses when undeclared' is indistinguishable from
    'always refuses' — a readiness probe that never passes takes the gateway down and still
    satisfies the test above."""
    gw = _reimport(
        monkeypatch,
        ONTOLOGY_SERVICE_URL="http://o:1",
        PRESENTATION_AGENT_SVC_URL="http://f:2",
        DATAHUB_WRAPPER_URL="http://d:3",
    )
    resp = await gw.health()
    assert getattr(resp, "status_code", 200) == 200, f"readiness refuses even fully declared: {resp}"
    assert resp["status"] == "ok"


@pytest.mark.asyncio
async def test_ONE_missing_variable_is_enough(monkeypatch):
    """The boundary. Two of three declared must still refuse — a partial deploy is a deploy
    fault, and 'mostly declared' is the state that would otherwise slip through."""
    gw = _reimport(
        monkeypatch,
        ONTOLOGY_SERVICE_URL="http://o:1",
        PRESENTATION_AGENT_SVC_URL="http://f:2",
    )
    resp = await gw.health()
    assert getattr(resp, "status_code", 200) == 503
    assert "DATAHUB_WRAPPER_URL" in resp.body.decode()


def test_a_whitespace_only_value_counts_as_UNDECLARED(monkeypatch):
    """`VAR: ""` in a ConfigMap is the shape a half-finished template produces, and it is not
    a declaration. Treating it as one would reintroduce the fallback through the back door."""
    gw = _reimport(monkeypatch, ONTOLOGY_SERVICE_URL="   ")
    assert gw._DAGSONTOLOGY_SVC_URL == ""
    assert "ONTOLOGY_SERVICE_URL" in gw._UNDECLARED_SERVICE_URLS


def test_no_fallback_ADDRESS_survives_anywhere_in_the_module():
    """THE FLOOR ON THE FIX ITSELF.

    The three defaults were literal in-cluster addresses. The tests above exercise the module
    constants; a fallback re-added inside a REQUEST handler — which is where DATAHUB_WRAPPER_URL
    had one — would not be caught by any of them. So the source is checked directly for the
    pattern: `os.getenv("<one of the three>", "<anything non-empty>")`.
    """
    import re

    src = (_SRC / "iagent" / "gateway.py").read_text(encoding="utf-8")
    offenders = []
    for var in _REQUIRED:
        # getenv with ANY second argument that is not an empty string
        for m in re.finditer(rf'os\.getenv\(\s*["\']{re.escape(var)}["\']\s*,\s*(.+?)\)', src):
            default = m.group(1).strip()
            if default not in ('""', "''"):
                offenders.append(f"{var} -> default {default}")
    assert not offenders, (
        f"a fallback default was re-added: {offenders}. A service URL the chart did not declare "
        f"must not resolve to a hardcoded address — readiness is the place that answer belongs."
    )
