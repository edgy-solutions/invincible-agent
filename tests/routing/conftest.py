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

A THIRD STATE, added later: "is something listening" is not the same question as "is the right
thing listening". A bare TCP connect passes just as happily for a FOREIGN service squatting on the
same port (measured: an unrelated container's `/health` endpoint answering Prometheus text/plain on
`localhost:8084`, where Engine O is expected) as it does for Engine O itself. That foreign service
then answers the real requests too, with whatever status it happens to return (405, in the measured
case), and the suite reports 36 reds that are actually a port collision — R-086's "a suite that
could not run is void, not red" applies exactly: these tests never reached Engine O at all. The fix
is not a richer liveness check; it is asking the one question a TCP connect cannot: does the body
at `/health` match what Engine O's own handler produces? `tests/_responder_identity.py` answers
that from the producer's actual response shape, so "absent" splits into "absent" and "foreign", and
only "expected" counts as present.
"""
from __future__ import annotations

import os

import pytest

from tests._responder_identity import Identity, is_engine_o, probe, routing_base_url, void_reason

# The SAME env knob the routing modules already read, so the probe and the tests cannot disagree
# about which service they mean. The default lives ONCE in `tests/_responder_identity.py`
# (ruled by Chris 2026-10-06: a non-colliding port, http://localhost:18084, so the suite stops
# depending on whatever else is bound to :8084 on this machine).
BASE_URL = routing_base_url()

_PROBE_TIMEOUT = float(os.getenv("ROUTING_TEST_PROBE_TIMEOUT", "1.5"))

#: Tests voided this session because nothing answered at BASE_URL, for the terminal summary.
_voided_absent: list[str] = []

#: Tests voided this session by a foreign responder, for the terminal summary.
_voided_foreign: list[str] = []


def _engine_o_identity() -> Identity:
    return probe(BASE_URL, "/health", is_engine_o, timeout=_PROBE_TIMEOUT)


def engine_o_reachable() -> bool:
    """True only when the service at BASE_URL answers like Engine O itself.

    Kept as a name (other modules may still import it) but its meaning narrowed: it used to mean
    "TCP-connectable"; it now means state == "expected", because a TCP-connectable FOREIGN service
    is not Engine O being reachable, it is a different thing holding the port.
    """
    return _engine_o_identity().state == "expected"


# Kept as a name (other modules may import it) in case anything still reads the plain
# "absent" message directly; the fixture below now uses `_void_absent_reason()` instead, since
# BOTH absent and foreign are VOID, not a quiet skip (see this module's header).
SKIP_REASON = (
    f"Engine O is not reachable at {BASE_URL} — this is an ENVIRONMENT fact, not a defect. "
    f"These are integration tests and they need the service:\n"
    f"    kubectl -n sandbox port-forward svc/iagent-engine-o 18084:8084 &\n"
    f"or point them elsewhere with ROUTING_TEST_BASE_URL=http://host:port\n"
    f"(They SKIP rather than FAIL on purpose: a red that only means 'no port-forward' teaches "
    f"readers to wave through red, and that immunity is what hides the one real failure.)"
)


def _void_absent_reason() -> str:
    return (
        f"VOID — nothing answers at {BASE_URL}. This is an ENVIRONMENT fact, not a defect:\n"
        f"    kubectl -n sandbox port-forward svc/iagent-engine-o 18084:8084 &\n"
        f"or point them elsewhere with ROUTING_TEST_BASE_URL=http://host:port\n"
        f"A void run is not a green — it must be reported as no information, not as a pass."
    )


def _void_foreign_reason(detail: str) -> str:
    return void_reason(BASE_URL, detail) + (
        " (Engine O specifically: point these at the real service with "
        "ROUTING_TEST_BASE_URL=http://host:port.)"
    )


@pytest.fixture(autouse=True)
def _engine_o_precondition(request):
    """Skip ONLY the tests that declared they need the service.

    Opt-in by marker rather than blanket-autouse, because this package also holds pure SOURCE-SCAN
    tests (`test_embed_contract`, `test_no_legacy_dns_references`) that need no service at all.
    Skipping those on an unrelated environmental fact would hide genuine defects — and at least one
    of them is currently red for a REAL reason.

    BOTH absent and foreign are VOID (ruled by Chris 2026-10-06): a suite that could not run is
    void, not red, regardless of WHICH way it could not run. Each gets its own skip reason and
    its own terminal-summary tally, so a reader sees which kind of void it was.
    """
    if not request.node.get_closest_marker("requires_engine_o"):
        return
    identity = _engine_o_identity()
    if identity.state == "foreign":
        _voided_foreign.append(request.node.nodeid)
        pytest.skip(_void_foreign_reason(identity.detail))
    if identity.state == "absent":
        _voided_absent.append(request.node.nodeid)
        pytest.skip(_void_absent_reason())


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print ONE loud line per VOID kind when the suite did not run against the real service.

    A void hidden among ordinary skips reads as a clean negative — the same shape as "nothing
    needed this service". These lines are what stop that: they say, unmissably, that tests did
    not run because nothing (or the wrong thing) answered, not because nothing needed to run.
    """
    if _voided_absent:
        terminalreporter.write_line(
            f"ROUTING SUITE VOID: {len(_voided_absent)} test(s) did not run — "
            f"nothing answers at {BASE_URL}",
            red=True,
            bold=True,
        )
    if _voided_foreign:
        identity = _engine_o_identity()
        terminalreporter.write_line(
            f"ROUTING SUITE VOID: {len(_voided_foreign)} test(s) did not run — "
            f"{BASE_URL} is answered by a foreign service ({identity.detail})",
            red=True,
            bold=True,
        )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_engine_o: integration test needing a live Engine O; SKIPS when unreachable, "
        "runs and FAILS normally when it is up.",
    )


# ---------------------------------------------------------------------------------------
# A HANG OUTRANKS A RED. Added 2026-09-11.
#
# `pytest tests/routing/` was exiting 124 on a CLEAN master tree — confirmed by
# invincible-agent-81 with none of either lane's changes applied, so it is not lane-local.
# Individually the suspected files pass in under a second, which is what makes a hang worse
# than a failure: a RED SAYS SOMETHING and a HANG SAYS NOTHING. It also eats the whole CI
# budget and reports a number that names nothing.
#
# The probe above answers "is the service up?" and cannot answer "did a test that got a
# connection then wait forever for a body?" — a socket that ACCEPTS and never replies passes
# the precondition and stalls the run. That is the gap this closes.
#
# `faulthandler` rather than pytest-timeout, which is not a declared dependency (and adding
# one to diagnose a hang is how a diagnosis becomes a dependency). `dump_traceback_later`
# prints EVERY thread's stack, so the output NAMES the line that stalled instead of leaving
# a bisect for the next reader.
# ---------------------------------------------------------------------------------------
import faulthandler
import sys

#: Generous on purpose. This is not a performance budget — it is the boundary past which a
#: test is no longer running, it is stuck. Override for a deliberately slow probe with
#: `IAGENT_ROUTING_TEST_TIMEOUT_S`.
_STALL_SECONDS = float(os.environ.get("IAGENT_ROUTING_TEST_TIMEOUT_S", "120"))


@pytest.fixture(autouse=True)
def _name_the_test_that_stalls(request):
    """Dump every thread's stack if a single test runs past the stall boundary.

    Deliberately does NOT kill the run. `exit=True` would turn one stalled probe into a
    dead suite and lose every result after it — trading a hang for a truncation, which
    answers a different question than the one asked. The traceback names the stall; the
    remaining tests still report.
    """
    if _STALL_SECONDS <= 0:                      # explicitly disabled
        yield
        return
    sys.stderr.write("")                          # ensure the stream exists under capture
    faulthandler.dump_traceback_later(
        _STALL_SECONDS, repeat=False, exit=False,
        file=sys.__stderr__,                      # the REAL stderr — pytest's capture would
    )                                             # swallow the dump for the hanging test
    sys.__stderr__.flush()
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
