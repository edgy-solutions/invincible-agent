"""B3 hard gate — zero Engine O changes.

Per the architect's B3 framing (2026-06-13): "Register as the third
`mesh:resolveInstance` provider through the gateway. The hard gate,
third application: zero Engine O changes — prove it with the git-diff-
empty check the way Gate 6 did, not by inspection."

This is the third application of the generality gate. Previous proofs:
  - Gate 5 (engine_d for catalog assets): no Engine O changes needed.
  - Gate 6 (engine_e for maintenance instances): no Engine O changes
    needed.
  - Gate 7 (THIS test, engine_dmc for S1000D Data Module Codes): asserted
    via git diff to be SAME.

The instance-resolution design certifies as general the moment a third
provider plugs in without touching the router. This test is the
verification — not a stylistic check, the certification itself.

How it works: read the list of files modified between B3's first
commit on this branch and master/main HEAD. If any of them are under
`agent_fleet/ontology_service/`, the gate fails — Engine O had to
change to onboard the new provider, which would mean the design isn't
general after all.

The gate is intentionally crude: it would catch even "fix a typo in a
comment in engine_o" — that's by design. If Engine O changes for ANY
reason in the same change that adds B3, the architect's claim
("zero-Engine-O-changes") would be false. The test is what proves the
claim.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
ENGINE_O_DIR = "agent_fleet/ontology_service/"


# The B3 work begins from this commit. Anything modified between this
# commit and HEAD must NOT touch agent_fleet/ontology_service/. Set as
# the commit that lands B2's close (68fc77e) — the last known-good
# state before B3 work started.
B3_BASELINE = "68fc77e"


def _git(*args: str) -> str:
    """Run git in the repo and return stdout. Errors propagate."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def test_b3_introduces_no_changes_in_engine_o():
    """ZERO Engine O changes between the B3 baseline and HEAD.

    If any file under agent_fleet/ontology_service/ has changed since
    the B3 baseline commit, this gate fails. The instance-resolution
    design's generality claim is wrong if Engine O had to change to
    onboard the DMC phone book.
    """
    # Verify the baseline commit exists. If not, the test runner is
    # in a shallow clone or detached state — skip rather than
    # mis-report.
    try:
        _git("cat-file", "-e", f"{B3_BASELINE}^{{commit}}")
    except RuntimeError:
        pytest.skip(
            f"Baseline commit {B3_BASELINE} not present in this checkout "
            f"(shallow clone?). The git-diff guard runs against the full "
            f"history; skip if not available."
        )

    # List files changed between baseline and HEAD.
    diff_output = _git("diff", "--name-only", f"{B3_BASELINE}..HEAD")
    changed = [line.strip() for line in diff_output.splitlines() if line.strip()]

    violations = [f for f in changed if f.startswith(ENGINE_O_DIR)]
    assert not violations, (
        f"ZERO ENGINE O CHANGES gate failed (B3 third generality-gate "
        f"application).\n"
        f"\n"
        f"Files in {ENGINE_O_DIR} have changed between "
        f"baseline {B3_BASELINE} and HEAD:\n"
        + "".join(f"  - {f}\n" for f in violations)
        + f"\n"
        f"This is the architect's hard gate: 'when B3's git-diff comes "
        f"back empty, that's the instance-resolution design certified "
        f"general.' Any change in Engine O — even a comment fix — "
        f"breaks that proof.\n"
        f"\n"
        f"If a real Engine O change is needed to onboard the DMC phone "
        f"book, the design ISN'T general and the architect's bet "
        f"failed. Stop B3, report the finding, do NOT relax this test."
    )
