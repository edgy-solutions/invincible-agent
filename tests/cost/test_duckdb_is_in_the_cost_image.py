"""duckdb must be declared, locked, AND provably importable INSIDE the built cost-agent image.

WHY THREE CHECKS AND NOT ONE. `agent_fleet/cost_agent/pyproject.toml` declaring `duckdb` only
proves uv resolved a wheel somewhere; `uv.lock` naming it only proves that resolution is
pinned. Neither proves the PUSHED image can import it — a stale cache layer, a build-arg typo,
or a platform-specific wheel miss could all leave the declaration true and the image broken.
That gap is exactly what shipped ten engine images without `iagent_mesh`
(`tests/test_lock_coherence.py`'s opening story) and it is the gap `measures.py`'s
`SourceUnavailable` refusal is a defence *in depth* against, not a substitute for closing.

So this seal reads the ARTIFACT the image is built from on both sides of that gap:

    DECLARED    agent_fleet/cost_agent/pyproject.toml names duckdb
    LOCKED      agent_fleet/cost_agent/uv.lock resolves it to a package
    SMOKE-TESTED  the cost-agent row in build-containers.yml asks CI to `docker run` the
                  pushed image and `import duckdb` inside it, not on the runner

The third is parsed from the workflow YAML rather than exercised here — actually running
`docker run` against a pushed multi-arch image is runbook §9 territory, not a local unit test.
This asserts the WORKFLOW commits to doing it, the same division test_lock_coherence.py draws
between "the tree wires it" and "a pod served under it".

Found by AGENT_DIR, never by list position: the matrix is a list of dicts in source order, and
a prior engine's insertion above cost-agent's row would silently retarget any index-based
assertion at the wrong row.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_AGENT_DIR = "agent_fleet/cost_agent"


def _cost_agent_row() -> dict:
    wf = _ROOT / ".github" / "workflows" / "build-containers.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    include = doc["jobs"]["build"]["strategy"]["matrix"]["include"]
    rows = [r for r in include if r.get("path") == _AGENT_DIR]
    assert rows, (
        f"no matrix row with path == {_AGENT_DIR!r} in build-containers.yml — the cost-agent "
        f"entry was found by its AGENT_DIR, which is now missing or renamed"
    )
    assert len(rows) == 1, f"more than one matrix row claims {_AGENT_DIR!r}: {rows}"
    return rows[0]


def _build_steps() -> list[dict]:
    wf = _ROOT / ".github" / "workflows" / "build-containers.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    return doc["jobs"]["build"]["steps"]


def test_the_cost_agent_row_declares_duckdb_as_a_smoke_import():
    row = _cost_agent_row()
    smoke = row.get("smoke_imports", "")
    assert "duckdb" in smoke.split(), (
        f"matrix row for {_AGENT_DIR!r} does not list duckdb in smoke_imports ({smoke!r}) — "
        f"the image build no longer asks CI to import-test it"
    )


def test_a_step_consumes_smoke_imports_with_docker_run():
    steps = _build_steps()
    consuming = [
        s for s in steps
        if "matrix.smoke_imports" in (s.get("run") or "") and "docker run" in (s.get("run") or "")
    ]
    assert consuming, (
        "no step in build-containers.yml's build job both reads matrix.smoke_imports and runs "
        "`docker run` — declaring smoke_imports on the matrix row is a no-op unless some step "
        "consumes it against the real, pushed image"
    )


def test_duckdb_is_a_declared_dependency_of_cost_agent():
    pp = (_ROOT / _AGENT_DIR / "pyproject.toml").read_text(encoding="utf-8")
    names = re.findall(r'"([A-Za-z0-9_.-]+)(?:[\[@<>=!\s].*)?"', pp)
    declared = {n.split("[")[0].strip().lower().replace("-", "_") for n in names}
    assert "duckdb" in declared, (
        f"{_AGENT_DIR}/pyproject.toml does not declare duckdb — the image the smoke step "
        f"checks would never have had it to begin with"
    )


def test_duckdb_is_resolved_in_cost_agent_uv_lock():
    lock = (_ROOT / _AGENT_DIR / "uv.lock").read_text(encoding="utf-8")
    assert re.search(r'^name = "duckdb"$', lock, re.M), (
        f"{_AGENT_DIR}/uv.lock never names duckdb as a resolved package — the lock is stale "
        f"against pyproject.toml and `uv sync --locked` will fail the image build on it"
    )
