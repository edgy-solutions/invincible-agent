"""THE REVIEW-START GATE IS ON WHEN NOBODY SET IT.

`ENABLE_DISPOSITION_AUTHZ` gates who may INITIATE a review (`can_invoke(mesh:startReview)`).
It defaulted to "false", so a deploy that forgot the variable ran the gate as a no-op True: a
gate that fails open by omission. Sandbox ran it on only because someone set it by hand
(2026-07-31); the chart never rendered it. Since chart 0.4.89 the default is on, and only an
explicit false/0/no turns it off.

The flag is read once, at import, so each arm runs a FRESH interpreter with the variable
controlled, and drives the gate against a Topaz double that answers 404 (an ungranted
capability). The control differs in exactly one thing, the variable set to "false", and must
admit: it proves the probe can tell an open gate from a closed one.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_PROBE = """
import sys
sys.path.insert(0, ".")
import httpx
from agent_fleet.restate_analyst import review_starter as rs

class _NotFound:
    status_code = 404

httpx.post = lambda *a, **k: _NotFound()
print("FLAG", rs.ENABLE_DISPOSITION_AUTHZ)
print("ADMIT", rs.can_invoke_start_review("svc:never-granted"))
"""


def _probe(env_value: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "ENABLE_DISPOSITION_AUTHZ"}
    if env_value is not None:
        env["ENABLE_DISPOSITION_AUTHZ"] = env_value
    r = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=str(_REPO), env=env,
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"probe failed:\n{r.stderr[-900:]}"
    out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if line[:5] in ("FLAG ", "ADMIT"))
    assert set(out) == {"FLAG", "ADMIT"}, r.stdout[-500:]
    return out


def test_UNSET_MEANS_ON_AND_AN_UNGRANTED_INITIATOR_IS_REFUSED():
    """THE SEAL. No variable at all: the gate is armed and a 404 from Topaz denies."""
    out = _probe(None)
    assert out["FLAG"] == "True", "ENABLE_DISPOSITION_AUTHZ unset reads as OFF: the gate fails open"
    assert out["ADMIT"] == "False", "an ungranted initiator was admitted with the variable unset"


def test_CONTROL_AN_EXPLICIT_FALSE_STILL_TURNS_IT_OFF():
    """Control: the same probe with the opt-out admits, so the seal above is the default firing."""
    out = _probe("false")
    assert out["FLAG"] == "False"
    assert out["ADMIT"] == "True"
