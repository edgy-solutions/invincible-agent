"""AN ENGINE THAT CANNOT REGISTER IS NOT READY — and it must keep trying.

MEASURED 2026-09-08: seven engines served UNREGISTERED for four hours. A helm upgrade
restarted the release; every engine came up inside an eleven-second window and Keycloak came
up 47-58 seconds later. The SDK transport's retry is BOUNDED, so each engine exhausted its
attempts against a Keycloak that had not booted and then never tried again.

Two faults, and they are genuinely separate:

    the retry was effectively startup-only    an engine that cannot mint a token at second
                                              five is not permanently unable to
    the state was invisible to Kubernetes     pods were Ready, healthy, answering, and
                                              silently unroutable for anything they would
                                              have registered

The second is why it lasted four hours instead of four minutes. The only evidence was a log
line, and the fleet's one reliable signal — a pod that is not Ready — never fired.

READINESS, NOT LIVENESS, AND THE DISTINCTION IS LOAD-BEARING. A failing readiness probe
removes the pod from Service endpoints; it does not restart it. So reporting not-ready while
still retrying is correct and costs exactly what it should. Wired to a LIVENESS probe the same
signal turns a slow dependency into a crash-loop — a cure worse than the outage. That is why
the module exposes a status rather than a bare boolean.

Run: uv run --frozen pytest tests/test_registration_retries_and_readiness_sees_it.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MOD_PATH = _REPO / "agent_fleet" / "utils" / "mesh_registration.py"
_SRC = _MOD_PATH.read_text(encoding="utf-8")


@pytest.fixture()
def mr():
    """The real module, with only the SDK transport stubbed.

    Stubbed because it lives in a sibling repo; everything under test here is this module's
    own state machine, so nothing meaningful is replaced.
    """
    pkg = types.ModuleType("iagent_mesh")
    tr = types.ModuleType("iagent_mesh.registration_transport")
    tr.register_with_mesh = lambda *a, **k: None
    sys.modules.setdefault("iagent_mesh", pkg)
    sys.modules["iagent_mesh.registration_transport"] = tr
    spec = importlib.util.spec_from_file_location("mesh_registration_under_test", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the state machine ───────────────────────────────────────────────────────

def test_an_engine_with_nothing_to_register_is_ready(mr):
    """Engine O consumes the registry; the presentation agent registers on its own path. A
    check that reported them not-ready would take two healthy services out of rotation to fix
    a problem neither has."""
    assert mr.registration_is_ready() is True


def test_a_failing_registration_makes_the_engine_NOT_ready(mr):
    """THE FOUR-HOUR SILENCE. This is the signal that did not exist."""
    mr._record("engine-x", mr._REG_RETRYING, "keycloak refused")
    assert mr.registration_is_ready() is False
    assert mr.registration_status()["status"] == mr._REG_RETRYING


def test_recovery_makes_it_ready_again_without_a_restart(mr):
    """The point of a retry that outlives startup: the pod rejoins endpoints on its own when
    the dependency arrives, rather than waiting for someone to notice and roll it."""
    mr._record("engine-x", mr._REG_RETRYING, "keycloak refused")
    mr._record("engine-x", mr._REG_OK)
    assert mr.registration_is_ready() is True
    assert mr.registration_status()["status"] == mr._REG_OK


def test_ONE_failed_component_is_enough_to_be_not_ready(mr):
    """CARDINALITY, NOT MEMBERSHIP — and this is the assertion the rest of the file exists
    around. An engine registering several verbs is not ready because SOME succeeded; a
    check reading "is a registered component present" passes while half the verbs are
    missing, which is exactly the silent-narrowing shape this repo keeps finding.
    """
    mr._record("engine-x", mr._REG_OK)
    mr._record("engine-y", mr._REG_RETRYING, "still refused")
    assert mr.registration_is_ready() is False


def test_the_status_snapshot_is_a_copy(mr):
    """A caller mutating the live dict would silently change what every later readiness probe
    reports — a shared-mutable-state defect in the one place whose whole job is to be
    trusted."""
    mr._record("engine-x", mr._REG_OK)
    snap = mr.registration_status()
    snap["components"]["engine-x"] = "tampered"
    snap["status"] = "tampered"
    assert mr.registration_status()["components"]["engine-x"] == mr._REG_OK
    assert mr.registration_status()["status"] == mr._REG_OK


# ── the retry itself ────────────────────────────────────────────────────────

def _fn(name: str) -> ast.FunctionDef:
    return next(
        n for n in ast.walk(ast.parse(_SRC))
        if isinstance(n, ast.FunctionDef) and n.name == name
    )


def test_the_retry_thread_is_a_DAEMON(mr):
    """An engine must not be held open by a retry that may never succeed, and this loop has
    no work to finish at shutdown."""
    src = ast.unparse(_fn("_start_retry"))
    assert "daemon=True" in src, "a non-daemon retry thread would block engine shutdown"


def test_the_retry_backs_off_and_is_JITTERED(mr):
    """Jitter is not decoration here. The incident was seven engines restarting inside an
    eleven-second window; an unjittered retry re-converges them into the same window on every
    subsequent attempt, which is the failure retrying its own cause."""
    src = ast.unparse(_fn("_retry_forever"))
    assert "random.uniform" in src, "the retry is unjittered — a fleet re-converges"
    assert "min(delay * 2" in src or "min(delay*2" in src, "no exponential backoff"
    assert "_RETRY_MAX_S" in src, "the backoff is uncapped"


def test_one_failed_attempt_does_not_kill_the_loop(mr):
    """A retry loop that dies on an exception is a retry that ran once."""
    fn = _fn("_retry_forever")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "an exception in one attempt would end the loop"


def test_the_failure_path_STARTS_the_retry(mr):
    """The join that makes any of this happen. Without it the state machine is correct and
    never leaves `pending`."""
    fn = _fn("_emit_to_registrar")
    calls = {
        getattr(c.func, "id", getattr(c.func, "attr", ""))
        for c in ast.walk(fn) if isinstance(c, ast.Call)
    }
    assert "_start_retry" in calls, "a failed registration no longer schedules a retry"
    assert "_record" in calls, "the outcome is not recorded, so readiness cannot see it"


def test_the_success_path_records_success(mr):
    """The positive control. A function that only ever recorded failure would report every
    healthy engine as not ready and take the fleet out of rotation."""
    i = _SRC.index("if result.registered:")
    assert "_record(urn or name, _REG_OK)" in _SRC[i:i + 300]
