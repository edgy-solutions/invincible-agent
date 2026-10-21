"""PARALLEL SUBTASKS MUST NOT POST `/resolve` AT THE SAME MOMENT.

THE MEASUREMENT (2026-09-05, deployed engine-o, 180s client timeout so the chain is visible
rather than clipped at 30):

    N=1   median 18.4s   max 22.0s    0/3  over the 30s budget
    N=2   median 26.1s   max 27.8s    0/6  over  -- a 2.2 second margin
    N=4   median 35.7s   max 46.6s    9/12 over

Engine O's BAML calls run against one Ollama path, so concurrency adds latency to every caller
rather than throughput. At N=2 — the ordinary shape of a decomposed question — it sits 2.2s
inside the cliff, which is why it passes on a quiet cluster and dies under any other load. That
is the defect this closes, and its blast radius is a WRONG ANSWER rather than a slow one:
Contract B sends an ungrounded subject to the generalist, which then answers from the catalog
wearing the caller's persona.

TWO DESIGN POINTS THIS FILE PINS, because both are easy to undo without noticing:

1. **The wait is OUTSIDE the timed call.** Each caller's 30s starts when it ACQUIRES, so the
   second subtask sees N=1 latency instead of queue-plus-service. Putting the lock inside the
   timeout would make serialization strictly worse than contention — 18s of waiting followed by
   18s of work against a 30s budget fails every time.

2. **It degrades OPEN.** No fcntl, an unwritable path, or the wait elapsing all fall through to
   calling anyway. Serialization is an optimisation of contention; failing to obtain it must
   never be worse than the unserialized behaviour it replaces.

THE BUDGET IS DELIBERATELY NOT RAISED. Serializing moves the operating point to N=1 where 30s
has real margin. Raising it instead picks a number against a load nobody holds fixed — at N=4
the max was 46.6s.

SUPERSEDED IN PART 2026-10-20: serialized, the 30s budget still missed at 33.6s and 34.5s on
revision 199. By the architect's ruling it is now 60s interim, set from the measured p100
(52,553 ms, n=55). The serialization and both design points above are unchanged.

Run: uv run --frozen pytest tests/routing/test_resolve_is_serialized.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")


def _resolve_post_window() -> str:
    i = _SUP.index('f"{ONTOLOGY_SVC_URL}/resolve"')
    return _SUP[max(0, i - 600):i + 2200]


# ── the lock is actually around the call ────────────────────────────────────

def test_the_resolve_post_is_inside_the_lock():
    w = _resolve_post_window()
    assert "with _resolve_serialized(context):" in w, (
        "the /resolve post is no longer serialized — parallel subtasks will contend again"
    )


def test_the_lock_is_taken_BEFORE_the_timeout_starts():
    """THE POINT OF THE WHOLE THING. If the wait were inside the timed call, serialization
    would be strictly worse than contention: 18s queued plus 18s of work against a 30s
    budget fails every time, where contention at least sometimes succeeds."""
    w = _resolve_post_window()
    lock_at = w.index("with _resolve_serialized(context):")
    post_at = w.index("requests.post(")
    assert lock_at < post_at, "the lock must be acquired before the request is issued"


def _module_int(name: str) -> int | None:
    for node in ast.parse(_SUP).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)):
            return node.value.value
    return None


def test_the_budget_is_the_one_its_measurement_set():
    """SUPERSEDED 2026-10-20: the budget WAS raised, and by ruling, not by guess. The architect:
    "Supervisor limit 60s interim, measured against the model's p100, not guessed." The
    measurement: revision 199, 55 completed `ClassifyDomainIntent` calls, p100 52,553 ms. The
    old 30s missed at 33.6s and 34.5s even though the resolves were serialized, so serializing
    alone did not make 30s honest under that load. Serialization STAYS — the arms above still
    pin it. If this number changes again, the measurement it is set from must change with it."""
    assert "timeout=RESOLVE_SUBJECT_TIMEOUT_S" in _resolve_post_window(), (
        "the /resolve post no longer uses the named budget"
    )
    budget = _module_int("RESOLVE_SUBJECT_TIMEOUT_S")
    assert budget == 60, (
        f"the resolve budget is {budget}s — if this changed, the measurement it is set from "
        f"must change with it"
    )


# ── it degrades open ────────────────────────────────────────────────────────

def _lock_body() -> str:
    i = _SUP.index("def _resolve_serialized(")
    return _SUP[i:i + 4200]


def test_a_missing_fcntl_does_not_break_resolution():
    """POSIX-only, and absent on a dev machine. An ImportError here would take routing down
    on every platform that lacks it."""
    body = _lock_body()
    assert "import fcntl" in body
    assert "except Exception" in body


def test_the_wait_is_BOUNDED():
    """An unbounded flock would hang a subtask forever behind a stuck holder — trading a
    timeout for a hang, which is worse because nothing reports it."""
    body = _lock_body()
    assert "LOCK_NB" in body, "the lock must be non-blocking with an explicit bound"
    assert "_RESOLVE_LOCK_WAIT_S" in body


def test_giving_up_still_calls():
    """The elapsed-wait path must fall through to the request, not abstain. Failing to get
    the lock is exactly the old behaviour and must never be worse than it."""
    body = _lock_body()
    i = body.index("_RESOLVE_LOCK_WAIT_S,")
    window = body[max(0, i - 500):i + 200]
    assert "break" in window, "the timeout path must break out and proceed, never raise"
    assert "raise" not in window


def test_the_lock_is_always_released():
    body = _lock_body()
    assert "finally:" in body and "LOCK_UN" in body


def test_release_failures_cannot_mask_the_answer():
    """A failure while unlocking must not replace a successful resolution with an error."""
    body = _lock_body()
    tail = body[body.index("finally:"):]
    assert tail.count("except Exception") >= 2


# ── it is a context manager, not a bare function ────────────────────────────

def test_it_is_a_contextmanager():
    tree = ast.parse(_SUP)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_resolve_serialized"),
        None,
    )
    assert fn is not None, "_resolve_serialized is not defined"
    names = {
        d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
        for d in fn.decorator_list
    }
    assert "contextmanager" in names, (
        "must be a contextmanager so the lock is released on the exception path too — a "
        "resolve that raises inside the lock would otherwise hold it for the pod's lifetime"
    )


# ── the measurement is recorded where the number is set ─────────────────────

def test_the_measured_numbers_travel_with_the_code():
    """A budget with no measurement beside it is the guessed number this arc removed. The
    next person to change 30 must see what it was set from."""
    body = _lock_body()
    for figure in ("18.4", "26.1", "46.6"):
        assert figure in body, f"the N-curve figure {figure} is missing from the rationale"
