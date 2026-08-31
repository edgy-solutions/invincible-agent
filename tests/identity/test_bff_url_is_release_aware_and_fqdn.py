"""THE URL BAKED AT REGISTRATION IS A FACT IN THE SUBSTRATE, not a config value.

`endpoint_url` is written into the verb edge when cortex-bff registers, and the dispatcher
reads it FROM THE GRAPH. So a wrong value is not something the next restart corrects — it
persists until a re-registration overwrites it, which is why chart 0.3.22 had to ship an
operator note saying exactly that.

WHAT WENT WRONG (2026-08-31, live at work):

    ProxyError: HTTPConnectionPool(host='proxygov...', port=80): Max retries exceeded with
    url: http://iagent-cortex-bff:8090/canvas/seed

An in-cluster call handed to a corporate proxy, because the registration read an INVENTED
env name (`CORTEX_BFF_PUBLIC_URL`, which no chart sets) and fell back to a BARE,
SANDBOX-PREFIXED literal. A bare host has no dots, so it cannot suffix-match a NO_PROXY
entry of `.svc.cluster.local` — chart 0.3.22's defect, reintroduced by a hardcoded default.

Run:  uv run --frozen python -m pytest tests/identity/test_bff_url_is_release_aware_and_fqdn.py -q
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.service_urls import cortex_bff_base_url, host_is_bare  # noqa: E402

FQDN = "http://invincible-agent-cortex-bff.prod.svc.cluster.local:8090"


def _hardcoded_bff_hosts(text: str) -> list:
    """String literals naming a cortex-bff HOST — a scheme is REQUIRED.

    Not a substring sweep for "cortex-bff". The service's name appears legitimately in log
    messages and comments; only a value carrying `://` is a URL somebody could dispatch to.
    Docstrings are excluded for the same reason comments are: prose about the defect is not
    the defect, and both this file and gateway.py explain it at length.
    """
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings
        and "://" in n.value and "cortex-bff" in n.value
    ]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("CORTEX_BFF_URL", raising=False)
    monkeypatch.delenv("CORTEX_BFF_PUBLIC_URL", raising=False)


def test_the_CHART_variable_wins(monkeypatch):
    """CORTEX_BFF_URL is what the chart computes — release-aware, FQDN, and an operator's
    override lands there. Always prefer the value a chart calculated over one code guessed."""
    monkeypatch.setenv("CORTEX_BFF_URL", FQDN + "/")
    assert cortex_bff_base_url() == FQDN, "trailing slash not trimmed, or wrong source"


def test_the_invented_name_is_accepted_only_as_a_DEPRECATED_alias(monkeypatch):
    """Accepted so a cluster where somebody set it while chasing this bug keeps working —
    and warned about, because no chart sets it and this code should not have invented it."""
    monkeypatch.setenv("CORTEX_BFF_PUBLIC_URL", FQDN)
    assert cortex_bff_base_url() == FQDN


def test_the_chart_variable_beats_the_alias(monkeypatch):
    monkeypatch.setenv("CORTEX_BFF_PUBLIC_URL", "http://wrong-cortex-bff:8090")
    monkeypatch.setenv("CORTEX_BFF_URL", FQDN)
    assert cortex_bff_base_url() == FQDN


@pytest.mark.parametrize("url,bare", [
    ("http://iagent-cortex-bff:8090", True),                                   # the defect
    ("http://invincible-agent-cortex-bff:8090", True),                         # right release, still bare
    ("http://invincible-agent-cortex-bff.ns.svc.cluster.local:8090", False),
    ("http://cortex.example.com", False),
    ("http://localhost:8090", True),
])
def test_a_bare_host_is_RECOGNISED_because_that_is_the_whole_tell(url, bare):
    """A bare host cannot suffix-match `.svc.cluster.local`, so behind a proxy the call is
    proxied and fails three layers from its cause. One check at resolution time is the
    cheapest place in the system to notice it — and `invincible-agent-cortex-bff` bare is in
    this list on purpose: the RIGHT release prefix is not enough."""
    assert host_is_bare(url) is bare


def test_a_bare_host_WARNS_even_when_an_operator_supplied_it(monkeypatch, caplog):
    """The warning is about the SHAPE, not the source. An operator override is exactly where
    a bare value is most likely to be typed by hand and least likely to be noticed."""
    monkeypatch.setenv("CORTEX_BFF_URL", "http://invincible-agent-cortex-bff:8090")
    with caplog.at_level(logging.WARNING):
        cortex_bff_base_url()
    assert "BARE" in caplog.text and "NO_PROXY" in caplog.text


def test_the_fallback_warns_that_the_charts_value_did_not_arrive(caplog):
    """Reaching the literal inside a cluster means the chart's value never landed. Silence
    there is what let a sandbox-prefixed host be dispatched to at a different release."""
    with caplog.at_level(logging.WARNING):
        got = cortex_bff_base_url()
    assert host_is_bare(got)
    assert "CORTEX_BFF_URL" in caplog.text


# ── the registration must not reintroduce a literal ────────────────────────────────

def test_the_registration_does_not_hardcode_a_bff_HOST():
    """ANCHORED ON AST STRING CONSTANTS, not a text search — this file and gateway.py both
    discuss the bad URL in prose, and a substring sweep would match the explanation.

    The claim: no string literal anywhere in gateway.py names a cortex-bff host. The
    resolver is the only way to learn it.
    """
    src = (_ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    offenders = _hardcoded_bff_hosts(src)
    assert offenders == [], (
        f"gateway.py hardcodes a cortex-bff host: {offenders} — the registered endpoint_url "
        "is baked into the verb edge, so a literal here becomes a wrong fact in the graph"
    )


def test_the_offender_guard_is_PROVEN_RED():
    """Fires on the literal that caused the outage; silent on things that merely NAME it.

    The third case is not hypothetical — it is what this guard matched on its own first run.
    A log line reading `"cortex-bff: registration failed (%s)"` contains the service name and
    is not a host at all. Requiring a SCHEME is what makes the assertion about the claim
    (a URL somebody could dispatch to) rather than its neighbour (any string mentioning the
    service). That is this repo's most-repeated instrument defect, caught inside the very
    guard written to prevent a different one.
    """
    assert _hardcoded_bff_hosts('x = "http://iagent-cortex-bff:8090"') == [
        "http://iagent-cortex-bff:8090"
    ]
    assert _hardcoded_bff_hosts('# comment: http://iagent-cortex-bff:8090\nx = 1') == []
    assert _hardcoded_bff_hosts('x = "cortex-bff: registration failed (%s)"') == []
    assert _hardcoded_bff_hosts('"""Doc naming http://iagent-cortex-bff:8090."""') == [], (
        "a docstring explaining the defect is not the defect"
    )
