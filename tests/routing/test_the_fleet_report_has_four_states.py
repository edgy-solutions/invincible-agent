"""FOUR STATES, BECAUSE THERE ARE FOUR — and the first version of the aggregator had one.

`/fleet/version` asks every service what commit it is. Four things can come back, and they
have DIFFERENT REPAIRS:

    reporting     answered, reports its build              nothing to do
    no_endpoint   answered 404 — /version not in that image ROLL IT
    unstamped     answered, endpoint present, no GIT_SHA    rebuild it
    unreachable   nothing came back at all                  the service is DOWN

The first version caught every exception and wrote `unreachable`. cortex-ui-60 hit the
identical collapse in the UI header the same night — it read UNREACHABLE for a BFF that was
up and serving picks, because it had 404'd an endpoint that had simply not been rolled — and
warned that this aggregator had the same shape. It did. "The service is down" and "the
service has not been rolled" send a person to opposite places.

THE DISCRIMINATOR IS WHETHER THE SERVICE SPOKE, which is why a status code is not enough on
its own: a transport failure has no status at all, and a non-404 status is neither down nor
missing (401 and 500 are different problems, and neither is "no endpoint").

WHAT THIS FILE FAKES, AND WHY IT IS THE TRANSPORT. cortex-60's mutation survey found that
mocking their `fetchBffVersion` wholesale left FOUR mutations alive in the classification —
the test checked the LABELS and could not see the function with the defect in it. A mock is
a decision about where the subject ends, and theirs had silently moved the boundary to
exclude the only code that had failed. So this stubs `httpx.AsyncClient` and lets the real
classification run. The rule: THE MOCK BOUNDARY AND THE DEFECT BOUNDARY MUST BE ON THE SAME
SIDE OF EACH OTHER, and nothing tells you when they are not except a mutation that will not
die.

Run: uv run --frozen pytest tests/routing/test_the_fleet_report_has_four_states.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class _Resp:
    def __init__(self, status: int, body=None, boom=False):
        self.status_code, self._body, self._boom = status, body, boom

    def json(self):
        if self._boom:
            raise ValueError("not json")
        return self._body


class _Client:
    """Stands in for `httpx.AsyncClient` — the TRANSPORT, one layer below the decision."""

    def __init__(self, outcome):
        self._outcome = outcome

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


async def _report(outcome, monkeypatch):
    """Run the REAL /fleet/version handler with only the transport replaced."""
    import iagent.gateway as gw

    monkeypatch.setattr(gw, "_fleet_version_targets", lambda: {"engine-w": "http://ew:8093"})
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client(outcome))
    doc = await gw.fleet_version()
    return doc["services"]["engine-w"], doc


@pytest.mark.asyncio
async def test_a_service_that_ANSWERS_reports_its_sha(monkeypatch):
    r, doc = await _report(
        _Resp(200, {"component": "engine-w", "repo": "invincible-agent",
                    "git_sha": "f0c2aeb88b5a", "image_tag": "f0c2aeb88b5a"}),
        monkeypatch,
    )
    assert r["state"] == "reporting" and r["git_sha"] == "f0c2aeb88b5a"
    assert doc["by_state"]["reporting"] == ["engine-w"]


@pytest.mark.asyncio
async def test_a_404_is_NOT_ROLLED_and_not_down(monkeypatch):
    """THE ONE THAT MATTERED. A service that answers 404 is up, healthy, and running an
    image built before /version existed. Calling that "unreachable" sends someone to rescue
    a service that is fine, while the actual repair — roll it — goes unmentioned."""
    r, _ = await _report(_Resp(404), monkeypatch)
    assert r["state"] == "no_endpoint", r
    assert r["git_sha"] is None
    assert "roll" in r["detail"].lower()


@pytest.mark.asyncio
async def test_a_transport_failure_IS_down(monkeypatch):
    """The control on the one above: `unreachable` must still be reachable as an answer.
    A classifier that never says DOWN is as useless as one that always does — and its value
    is entirely in how rarely it is right."""
    r, _ = await _report(ConnectionError("connection refused"), monkeypatch)
    assert r["state"] == "unreachable"
    assert "ConnectionError" in r["detail"]


@pytest.mark.asyncio
async def test_an_answered_but_UNSTAMPED_build_says_so(monkeypatch):
    """Answered, endpoint present, `git_sha` null — an image built before the stamp existed.
    Not a failure and not a 404; the repair is a rebuild, not a roll and not a rescue."""
    r, _ = await _report(
        _Resp(200, {"component": "engine-w", "repo": "invincible-agent", "git_sha": None}),
        monkeypatch,
    )
    assert r["state"] == "unstamped"


@pytest.mark.asyncio
async def test_a_non_404_status_is_neither_down_nor_missing(monkeypatch):
    """401 and 500 are different problems and neither one is "no endpoint". The status
    travels so a reader is not left choosing between two wrong repairs."""
    r, _ = await _report(_Resp(500), monkeypatch)
    assert r["state"] == "error" and "500" in r["detail"]


@pytest.mark.asyncio
async def test_a_200_that_is_not_JSON_is_an_error_not_a_report(monkeypatch):
    """Something answered on that port and it was not this service. Reporting it as
    `unstamped` would claim we heard from a build we never heard from."""
    r, _ = await _report(_Resp(200, boom=True), monkeypatch)
    assert r["state"] == "error"


@pytest.mark.asyncio
async def test_the_FOUR_are_actually_distinguishable(monkeypatch):
    """THE FLOOR ON THE WHOLE FILE. Six assertions above could all pass against a classifier
    that returned a constant if each test happened to expect that constant. This requires
    the states to be DIFFERENT from each other, which is the property the collapse violated
    and which no single-case assertion can express."""
    seen = set()
    for outcome in (
        _Resp(200, {"git_sha": "abc123abc123"}),
        _Resp(404),
        _Resp(200, {"git_sha": None}),
        ConnectionError("down"),
    ):
        r, _ = await _report(outcome, monkeypatch)
        seen.add(r["state"])
    assert len(seen) == 4, f"the four outcomes collapsed to {sorted(seen)}"


@pytest.mark.asyncio
async def test_the_report_is_keyed_by_what_the_service_CALLS_ITSELF(monkeypatch):
    """FOUND BY THE FIRST LIVE CENSUS, 2026-09-09, and it read as six stale services.

    The aggregator used to key each report by the ENV VAR its URL came from —
    `ENGINE_A_PUBLIC_URL` became "a", `ONTOLOGY_SERVICE_URL` became "ontology". Those are
    accidents of a variable name, so a consumer had to GUESS which deployment "ontology" is,
    and the census's guess was a suffix match. It matched `iagent-engine-a` to "a" by luck
    and failed to match `iagent-engine-o` to "ontology" at all: six services showed no sha
    while every one of them was reporting correctly.

    The misses were the visible half. A suffix rule can also MATCH THE WRONG SERVICE and
    report one pod's sha under another's name, which reads as a successful census and is the
    failure nobody would have looked for.

    The payload carries the canonical `component`. Keyed by that, the join is exact, and a
    service whose name breaks the convention is missed VISIBLY rather than mismatched.
    """
    import iagent.gateway as gw

    monkeypatch.setattr(gw, "_fleet_version_targets",
                        lambda: {"ontology": "http://engine-o:8084"})
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client(
        _Resp(200, {"component": "engine-o", "repo": "invincible-agent",
                    "git_sha": "1a7ceeaa305c"})))
    doc = await gw.fleet_version()

    assert "engine-o" in doc["services"], (
        f"keyed by the env-derived name instead of the reported component: "
        f"{sorted(doc['services'])}"
    )
    assert "ontology" not in doc["services"]
    # The env name is KEPT, not discarded — it is how an operator finds which variable
    # pointed here when a service is unreachable and cannot name itself.
    assert doc["services"]["engine-o"]["asked_as"] == "ontology"


@pytest.mark.asyncio
async def test_a_service_that_CANNOT_name_itself_keeps_the_env_key(monkeypatch):
    """The control on the re-keying. A 404 or a dead socket carries no payload and therefore
    no component, so there is nothing canonical to key by — it stays under the name we asked
    it by, which is the only true thing available. Silently dropping it would remove exactly
    the service most worth reporting."""
    import iagent.gateway as gw

    monkeypatch.setattr(gw, "_fleet_version_targets", lambda: {"w": "http://engine-w:8093"})
    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client(_Resp(404)))
    doc = await gw.fleet_version()
    assert doc["services"]["w"]["state"] == "no_endpoint"
    assert doc["services"]["w"]["asked_as"] == "w"


def test_targets_are_named_as_the_component_will_name_ITSELF(monkeypatch):
    """FOUND BY THE SECOND LIVE CENSUS — the fix for the first join defect broke the control.

    A service that ANSWERS is re-keyed by the `component` in its payload. A service that 404s
    or is down carries no payload and cannot be re-keyed, and those are precisely the rows
    worth reading. The held-back `engine-w` fell out of its own join and read UNKNOWN instead
    of `not-rolled`: the repair only covered the case where the service could speak.

    So the canonical name is derived at TARGET time, before anyone has to answer.
    `ENGINE_W_PUBLIC_URL` -> `engine-w` is the convention every engine already follows; the
    three older variables are mapped explicitly to the component each announces itself as.

    This is `test the edge, not the nodes` twice over: the aggregator and the census were each
    correct, and the join between them was wrong in two different ways on two different runs.
    """
    import os
    import iagent.gateway as gw

    monkeypatch.setattr(os, "environ", {
        "ENGINE_W_PUBLIC_URL": "http://iagent-engine-w:8093/query_knowledge",
        "ENGINE_A_PUBLIC_URL": "http://iagent-engine-a:8081/analyze",
        "DATAHUB_WRAPPER_URL": "http://iagent-engine-d:8085",
    })
    monkeypatch.setattr(gw, "_DAGSONTOLOGY_SVC_URL", "http://iagent-engine-o:8084")
    monkeypatch.setattr(gw, "_PRESENTATION_AGENT_SVC_URL", "http://iagent-engine-f:8087")
    targets = gw._fleet_version_targets()

    assert set(targets) == {"engine-w", "engine-a", "engine-d", "engine-o", "engine-f"}, (
        f"targets are named after their env vars rather than their components: "
        f"{sorted(targets)} — a service that cannot speak lands under a key nothing joins on"
    )
    # THE PATH IS STILL STRIPPED: several of those variables point at a handler, and
    # /version lives at the root.
    assert targets["engine-w"] == "http://iagent-engine-w:8093"
    assert targets["engine-a"] == "http://iagent-engine-a:8081"
