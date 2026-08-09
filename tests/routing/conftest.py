"""ONE precondition probe for the routing suite — absent service SKIPS, present service still FAILS.

WHY THIS FILE EXISTS. `AGENTS.md` ruled on this on 2026-08-05 ("A guard that FAILS instead of
SKIPPING when its precondition is absent is anesthesia") and diagnosed this exact suite: the modules
DOCUMENT themselves as "Skips if Engine O isn't reachable", and the skip never fires, so with no
port-forward to `localhost:8084` they emit ~32 `ConnectionError` failures per run. Every one is an
environmental fact wearing a defect's clothes. The diagnosis was filed and the guard was never
built; this builds it.

**The cost was never the failures — it is the TRAINING EFFECT.** A suite that cries wolf teaches
every reader to wave through red, and that acquired immunity is what makes the one real red
invisible. It also levied an adjudication tax that was actually paid, repeatedly: every before/after
comparison in the telemetry arc had to carry a 32-red baseline exclusion BY NAME, re-established by
stashing and re-running to prove the failures predated the change.

THE RULE, applied literally:

    precondition ABSENT   -> SKIP, naming what is missing and how to supply it
    precondition PRESENT  -> RUN, and FAIL normally if the behaviour is wrong

The second half is what keeps this from becoming a different lie. A guard that skips whenever
anything goes wrong would convert every real regression into a silent pass — trading noise for
blindness, which is the worse trade. So the probe asks exactly one question (is the service
answering?) and never widens: a service that answers and then misbehaves produces a red, as it must.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

# The SAME env knob the routing modules already read, so the probe and the tests cannot disagree
# about which service they mean.
BASE_URL = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")

_PROBE_TIMEOUT = float(os.getenv("ROUTING_TEST_PROBE_TIMEOUT", "1.5"))
_cache: dict = {}


def engine_o_reachable() -> bool:
    """TCP-connectable, cached once per session.

    Deliberately a CONNECT check and not an HTTP health call: the question is "is there a service
    here at all", which is the environmental fact. Anything richer starts overlapping with what the
    tests themselves assert, and a probe that duplicates the assertion can mask it.
    """
    if "ok" in _cache:
        return _cache["ok"]
    parsed = urlparse(BASE_URL)
    host, port = parsed.hostname or "localhost", parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT):
            _cache["ok"] = True
    except OSError:
        _cache["ok"] = False
    return _cache["ok"]


SKIP_REASON = (
    f"Engine O is not reachable at {BASE_URL} — this is an ENVIRONMENT fact, not a defect. "
    f"These are integration tests and they need the service:\n"
    f"    kubectl -n sandbox port-forward svc/iagent-engine-o 8084:8084 &\n"
    f"or point them elsewhere with ROUTING_TEST_BASE_URL=http://host:port\n"
    f"(They SKIP rather than FAIL on purpose: a red that only means 'no port-forward' teaches "
    f"readers to wave through red, and that immunity is what hides the one real failure.)"
)


@pytest.fixture(autouse=True)
def _engine_o_precondition(request):
    """Skip ONLY the tests that declared they need the service.

    Opt-in by marker rather than blanket-autouse, because this package also holds pure SOURCE-SCAN
    tests (`test_embed_contract`, `test_no_legacy_dns_references`) that need no service at all.
    Skipping those on an unrelated environmental fact would hide genuine defects — and at least one
    of them is currently red for a REAL reason.
    """
    if request.node.get_closest_marker("requires_engine_o") and not engine_o_reachable():
        pytest.skip(SKIP_REASON)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_engine_o: integration test needing a live Engine O; SKIPS when unreachable, "
        "runs and FAILS normally when it is up.",
    )
