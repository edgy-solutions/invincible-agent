"""`tests/viewer_double.route_viewer_tasks_through(..., a_case_with_no_label=True)` must stand a case
up in ANY process, not only one where an earlier test happened to import the case projection.

The gateway imports `case_projection` lazily (at its first label read), so on a fresh interpreter it
is not in `sys.modules`. The double looked it up there and, finding nothing, skipped itself without a
word: the real `_case_state` then ran, asked the case runner, and answered 503 `runner_unavailable`,
which `_admit_named_on_case` turned into 503 `authorization_unavailable`. A test using it (the q2b
filing test, the first of its file) failed alone and passed after another test had loaded the module.

The seal runs in a FRESH interpreter, so the order of the tests around it cannot hide the fault:
  * claim: after the double is installed, the gateway's `_case_state` is the double and
    `case_projection.case_labels` answers no label;
  * control: without `a_case_with_no_label` nothing is replaced (a test that stands its own case up
    keeps it), so the assertion is not true of everything."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent("""
    import sys
    import pytest
    from src.iagent import gateway
    from tests.viewer_double import route_viewer_tasks_through
    assert "src.iagent.case_projection" not in sys.modules, "the fresh process must not have it"
    real = gateway._case_state
    mp = pytest.MonkeyPatch()
    try:
        route_viewer_tasks_through(mp, a_case_with_no_label={flag})
        replaced = gateway._case_state is not real
        from src.iagent import case_projection as cp
        labels = cp.case_labels({{}}, None, {{}})
    finally:
        mp.undo()
    print("replaced=%s labels=%r" % (replaced, labels))
""")


def _run(flag: bool) -> str:
    out = subprocess.run([sys.executable, "-c", _PROBE.format(flag=flag)], cwd=ROOT,
                         capture_output=True, text=True, timeout=300,
                         env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    assert out.returncode == 0, out.stderr[-600:]
    return out.stdout.strip().splitlines()[-1]


def test_the_double_stands_a_case_up_in_a_process_that_has_not_loaded_the_projection():
    assert _run(True) == "replaced=True labels=[]"


def test_control_without_the_option_the_gateways_own_case_read_is_left_alone():
    line = _run(False)
    assert line.startswith("replaced=False"), line
