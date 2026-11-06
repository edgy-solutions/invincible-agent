"""A workflow step that pipes a command into `tee` must keep that command's exit code.

A `run:` step with no `shell:` runs `bash -e {0}`, which has no pipefail. So
`pytest ... | tee log && rc=0 || rc=$?` sets rc to tee's exit, and the step cannot fail.
cross-repo-kind-drift.yml did this: its pinned gate read `1 failed` in its log and concluded
success, and its control could not see that because the control runs pytest with no pipe.

Explicit `shell: bash` runs `bash --noprofile --norc -eo pipefail {0}`, so that form is safe too.
"""
import re
from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_TEE = re.compile(r"\|\s*tee\b")
_PIPEFAIL = re.compile(r"^\s*set\s+-[a-z]*o\s+pipefail", re.M)


def _swallowing_lines(run: str) -> list[str]:
    """Lines that pipe a command's output into tee. `echo ... | tee` has no exit worth keeping, and
    a shell comment is not a pipeline (release-helm-charts.yml explains this same trap in one)."""
    return [line.strip() for line in run.splitlines()
            if _TEE.search(line) and not line.strip().startswith(("echo ", "#"))]


def _keeps_exit(run: str, shell) -> bool:
    return shell == "bash" or bool(_PIPEFAIL.search(run))


def _steps(doc: dict):
    wf_shell = ((doc.get("defaults") or {}).get("run") or {}).get("shell")
    for job_name, job in (doc.get("jobs") or {}).items():
        job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
        for step in job.get("steps") or []:
            if isinstance(step.get("run"), str):
                yield job_name, step, step.get("shell") or job_shell or wf_shell


def _census() -> list[tuple[str, str, bool]]:
    found = []
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, step, shell in _steps(doc):
            for line in _swallowing_lines(step["run"]):
                found.append((f"{path.name}::{job_name}: {line[:80]}", step["run"],
                              _keeps_exit(step["run"], shell)))
    return found


def test_every_pipeline_into_tee_keeps_its_exit_code():
    bad = [where for where, _, keeps in _census() if not keeps]
    assert not bad, f"these steps cannot fail on the piped command's exit: {bad}"


def test_the_census_reads_the_step_that_was_broken():
    # Without this the seal above is green on a census that reads nothing.
    assert any(where.startswith("cross-repo-kind-drift.yml::") and "pytest" in where
               for where, _, _ in _census())


@pytest.mark.parametrize("run, shell, keeps", [
    ('python -m pytest x | tee "$log" && rc=0 || rc=$?\nexit "$rc"\n', None, False),
    ('set -o pipefail\npython -m pytest x | tee "$log" && rc=0 || rc=$?\n', None, True),
    ('set -eo pipefail\npython -m pytest x | tee "$log"\n', None, True),
    ('python -m pytest x | tee "$log"\n', "bash", True),
])
def test_the_detector_tells_the_forms_apart(run, shell, keeps):
    assert _swallowing_lines(run)
    assert _keeps_exit(run, shell) is keeps


def test_an_echo_or_a_comment_is_not_a_finding():
    assert _swallowing_lines('echo "hello" | tee -a "$GITHUB_STEP_SUMMARY"\n') == []
    assert _swallowing_lines('  # A FILE, NOT `| tee`: no pipefail here\n') == []
