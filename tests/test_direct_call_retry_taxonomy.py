"""PERMANENT vs TRANSIENT on the direct_call step — a malformed URL is not weather.

THE LIVE MISS (2026-08-09). `{dispatch_endpoint}` reached `execute_direct_call` unbound, `requests`
raised `MissingSchema` BEFORE any response, nothing caught it, and Restate retried a PERMANENT error
**sixteen times and counting**. The taxonomy already existed in this module for `spo_operation`
(401/403 terminal · 5xx/network retryable); the direct_call path was simply a second consumer that
had never been given it.

WHY IT MATTERS BEYOND THE NOISE: a permanent error classified transient does not merely waste
retries, it **misreports the kind of problem**. An operator watching a backing-off invocation reads
"the downstream is flaky"; the truth was "this deployment can never work". Retry is a claim about
the world, and a wrong one sends people to the wrong system.

Run:  uv run --frozen python -m pytest tests/test_direct_call_retry_taxonomy.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

_ROOT = Path(__file__).resolve().parents[1]
_RA = _ROOT / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.spo_step_executor import (  # noqa: E402
    StepFailAndRelease, execute_direct_call,
)

_STEP = {"id": "dispatch_dispositions", "endpoint": "http://engine-o/write_item_state",
         "capability": "mesh:dispatchDispositions"}
_IDENT = {"authz_id": "svc:review-starter"}


@pytest.fixture(autouse=True)
def _granted(monkeypatch):
    """The gate is NOT what this file is about — grant it so every test exercises the transport
    classification rather than stopping at the capability check."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex, "check_can_invoke", lambda *a, **k: True)


class _Resp:
    def __init__(self, code, body=""):
        self.status_code, self.text = code, body

    def json(self):
        return {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")


# ===========================================================================
# PERMANENT — must be TERMINAL, never retried
# ===========================================================================
@pytest.mark.parametrize("exc", [
    requests.exceptions.MissingSchema("Invalid URL '{dispatch_endpoint}': No scheme supplied."),
    requests.exceptions.InvalidURL("Invalid URL"),
    requests.exceptions.InvalidSchema("No connection adapters were found"),
])
def test_an_unusable_URL_is_TERMINAL(monkeypatch, exc):
    """THE EXACT DEFECT. Before this, these propagated as plain exceptions and Restate retried
    forever — a URL that cannot be parsed will not parse on attempt seventeen."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: (_ for _ in ()).throw(exc))
    with pytest.raises(StepFailAndRelease) as ei:
        execute_direct_call(_STEP, _IDENT)
    assert "DEPLOYMENT defect" in str(ei.value), (
        "the refusal must name the KIND of problem — an operator reading 'transport' goes to the "
        "wrong system entirely")


def test_an_unbound_placeholder_in_the_URL_says_so_by_name(monkeypatch):
    """Defence in depth. `bind_placeholders` should refuse this at admission, but if a literal ever
    reaches here again the message must point at the placeholder rather than at the URL parser —
    the original error surfaced three layers from its cause."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    boom = requests.exceptions.MissingSchema("Invalid URL '{dispatch_endpoint}': No scheme supplied.")
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: (_ for _ in ()).throw(boom))
    with pytest.raises(StepFailAndRelease) as ei:
        execute_direct_call({**_STEP, "endpoint": "{dispatch_endpoint}"}, _IDENT)
    assert "UNBOUND PLACEHOLDER" in str(ei.value)
    assert "bind_placeholders" in str(ei.value), "point the reader at the fix, not just the symptom"


@pytest.mark.parametrize("code", [400, 404, 409, 422])
def test_a_4xx_is_TERMINAL(monkeypatch, code):
    """A 4xx is a statement about THIS REQUEST. Retrying re-sends the identical request and earns
    the identical answer, burning the journal while delaying the real signal."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: _Resp(code, "nope"))
    with pytest.raises(StepFailAndRelease) as ei:
        execute_direct_call(_STEP, _IDENT)
    assert ei.value.status_code == code


@pytest.mark.parametrize("code", [401, 403])
def test_a_denial_stays_TERMINAL_and_keeps_its_403(monkeypatch, code):
    """The pre-existing behaviour, pinned so the new 4xx branch cannot swallow the denial branch —
    a denial must keep reporting 403 regardless of which code the server used."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: _Resp(code))
    with pytest.raises(StepFailAndRelease) as ei:
        execute_direct_call(_STEP, _IDENT)
    assert ei.value.status_code == 403
    assert "access denied" in str(ei.value)


# ===========================================================================
# TRANSIENT — must stay RETRYABLE, or the fix would break durability
# ===========================================================================
@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_a_5xx_stays_RETRYABLE(monkeypatch, code):
    """The other half of the claim, and the one a careless fix breaks: turning everything terminal
    would trade a retry storm for a pipeline that gives up on a restarting downstream."""
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: _Resp(code, "boom"))
    with pytest.raises(requests.exceptions.HTTPError):
        execute_direct_call(_STEP, _IDENT)


def test_a_network_error_stays_RETRYABLE(monkeypatch):
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("refused")))
    with pytest.raises(requests.exceptions.ConnectionError):
        execute_direct_call(_STEP, _IDENT)


def test_the_happy_path_still_returns_the_body(monkeypatch):
    import agent_fleet.restate_analyst.spo_step_executor as ex  # noqa: PLC0415
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: _Resp(200))
    assert execute_direct_call(_STEP, _IDENT) == {"ok": True}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
