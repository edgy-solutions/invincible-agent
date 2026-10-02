"""TASK GRANTS MUST EXIST WITHOUT A HUMAN HAND-RUNNING policy/sync/task_grant_sync.py.

`topaz-seed-cronjob.yaml` already runs task_grant_sync — but bundled with five OTHER syncs, and
default-disabled (`topazSeed.enabled: false`), so enabling it to get task grants also prunes
five scopes nobody asked to touch. `templates/task-grant-sync-job.yaml` is the narrow fix: a
post-install/post-upgrade helm hook Job that runs ONLY task_grant_sync.py, gated by its own
`taskGrantSync.enabled` value (default off; on in values-sandbox.yaml).

Follows the shape of test_chart_renders_on_bare_defaults.py: render with `helm template` and
assert on the real output, never on an empty string (an absence check over a failed render is a
false green — see that file's header for the LangGraph incident this guards against).

Run: uv run pytest tests/test_task_grant_startup_sync_renders.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_SCRIPT = _REPO / "scripts" / "upgrade-sandbox.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(*extra: str) -> str:
    """Render the chart, failing the test with helm's own error rather than an empty string —
    an absence assertion over a failed render's empty output passes vacuously."""
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, (
        f"helm template failed — every absence assertion below would pass vacuously on its "
        f"empty output:\n{r.stderr[-700:]}"
    )
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _sandbox_values_args() -> list[str]:
    """DERIVE the sandbox values-file list from scripts/upgrade-sandbox.sh's own VALUES array,
    rather than typing `values-sandbox.yaml` by hand here — the two must never disagree about
    which overlays a sandbox render receives (see that script's header: a render's correctness
    silently depended on a human remembering a flag, twice).

    values-sandbox.secret.yaml is untracked (real credentials; .gitignore'd) and legitimately
    absent in this checkout/CI — the script itself treats its absence as a hard stop for a REAL
    upgrade, but a chart-render test has no credentials to obtain, so files the VALUES array
    names that do not exist on disk are skipped here rather than failing the test suite. The
    file(s) that DO exist are passed exactly as the script passes them (same -f per path).
    """
    src = _SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"VALUES=\((.*?)\)", src, re.S)
    assert m, "scripts/upgrade-sandbox.sh's VALUES array is not in the recognised shape"
    paths = re.findall(r'"\$\{CHART\}/([^"]+)"', m.group(1))
    assert paths, "parsed zero paths out of upgrade-sandbox.sh's VALUES array"
    assert "values-sandbox.yaml" in paths, (
        f"values-sandbox.yaml missing from the parsed list: {paths}"
    )
    args: list[str] = []
    chart_dir = _REPO / _CHART
    for p in paths:
        f = chart_dir / p
        if f.exists():
            args += ["-f", str(f)]
    return args


@pytest.fixture(scope="module")
def bare() -> str:
    return _render()


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_sandbox_values_args())


# ── (a) bare defaults: no task-grant Job ────────────────────────────────────

def test_bare_defaults_render_no_task_grant_job(bare: str):
    assert "task-grant-sync" not in bare, (
        "taskGrantSync.enabled defaults to true, or the guard is missing — bare defaults must "
        "never surprise-run a policy sync"
    )


def test_bare_defaults_still_pass_the_existing_seal(bare: str):
    """(d) — the existing bare-defaults test must still be green; re-assert its core claim
    here too so a regression in this area is caught by this file as well."""
    assert "kind: Deployment" in bare
    assert bare.count("kind: Deployment") >= 15


# ── (b) sandbox values: exactly one Job, right hook, right command, right env ──

def test_sandbox_renders_exactly_one_task_grant_job(sandbox: str):
    assert sandbox.count("name: t-task-grant-sync\n") == 1, (
        "expected exactly one task-grant-sync Job in the sandbox render"
    )


def test_sandbox_job_carries_the_post_install_post_upgrade_hook(sandbox: str):
    i = sandbox.index("name: t-task-grant-sync")
    block = sandbox[i:i + 900]
    assert '"helm.sh/hook": post-install,post-upgrade' in block
    assert '"helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded' in block


def test_sandbox_job_runs_task_grant_sync_and_nothing_else(sandbox: str):
    i = sandbox.index("name: t-task-grant-sync")
    # The container's args block, up to the next top-level Job/other resource.
    block = sandbox[i:i + 3000]
    assert "task_grant_sync.py" in block
    # NOT substring checks: "grant_sync.py" is a substring of "task_grant_sync.py" itself, so a
    # naive `in` check self-matches on the very line this Job is supposed to run. Require a
    # word boundary (nothing alphanumeric/underscore immediately before the module name).
    other_syncs = (
        "topaz_sync.py", "datahub_topaz_sync.py", "grant_sync.py",
        "ontology_compartment_sync.py", "capability_grant_sync.py",
    )
    present = [s for s in other_syncs if re.search(r"(?<![\w])" + re.escape(s), block)]
    assert not present, f"the startup Job must run ONLY task_grant_sync, found: {present}"


def test_sandbox_job_env_has_the_grants_file_and_directory_url(sandbox: str):
    i = sandbox.index("name: t-task-grant-sync")
    block = sandbox[i:i + 3000]
    assert "TOPAZ_DIRECTORY_URL" in block
    assert "TASK_GRANTS_FILE" in block


# ── (c) image + env source match the CronJob's task-grant leg, topazSeed enabled ──

def test_image_and_grants_file_source_match_the_cronjob_leg():
    """Rendered WITH topazSeed enabled so the CronJob's task-grant container also renders.
    Both must resolve to the SAME image and the SAME TASK_GRANTS_FILE derivation (image mode:
    POLICY_DIR=/app/policy) — this template reads topazSeed.image/topazSeed.policySource
    directly rather than declaring a second copy, so drift here means someone edited only one
    template's logic."""
    out = _render(*_sandbox_values_args(), "--set", "topazSeed.enabled=true")

    def image_after(marker: str) -> str:
        i = out.index(marker)
        block = out[i:i + 4000]
        m = re.search(r'image:\s*"?([^"\s]+cortex-bff[^"\s]*)"?', block)
        assert m, f"no cortex-bff image found after {marker!r}"
        return m.group(1)

    job_image = image_after("name: t-task-grant-sync")
    cronjob_image = image_after("name: t-topaz-seed\n")
    assert job_image == cronjob_image, (
        f"image drift between the two task-grant legs: {job_image!r} vs {cronjob_image!r}"
    )

    job_block = out[out.index("name: t-task-grant-sync"):][:3000]
    cronjob_block = out[out.index("name: t-topaz-seed\n"):][:8000]
    assert "POLICY_DIR=/app/policy" in job_block
    assert "POLICY_DIR=/app/policy" in cronjob_block
    assert 'TASK_GRANTS_FILE="$POLICY_DIR/task_grants.yaml"' in job_block
    assert 'export TASK_GRANTS_FILE="$POLICY_DIR/task_grants.yaml"' in cronjob_block


# ── the flip: prove (b) actually tests something ────────────────────────────

def test_flipping_taskGrantSync_off_makes_b_go_red():
    """PROVE THE SEAL CAN FAIL. With taskGrantSync.enabled=false the sandbox render must have
    ZERO task-grant Jobs — the inverse of test_sandbox_renders_exactly_one_task_grant_job, run
    against the same sandbox overlay so only taskGrantSync.enabled differs."""
    off = _render(*_sandbox_values_args(), "--set", "taskGrantSync.enabled=false")
    assert "task-grant-sync" not in off, (
        "disabling taskGrantSync still rendered a task-grant resource — the enabled gate is "
        "not wired to the template"
    )
