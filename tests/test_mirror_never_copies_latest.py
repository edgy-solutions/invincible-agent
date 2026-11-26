"""The mirror never copies or writes `:latest` (issue #500).

`scripts/mirror-to-artifactory.ps1` once copied `:latest` for every iagent row, so a deployment
ran a stale mirrored `dagster-control-plane:latest`. The rule now: `-Release` is mandatory, the
iagent table carries bare repos, every copy is by release digest tagged with the chart version,
and a row the release lacks is refused (or dropped with `-SkipUnpinned`).

The static half always runs. The behavioural half runs the script with `-PlanOnly` (no network,
no docker) under pwsh or powershell.exe, and skips with a reason when neither exists.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "mirror-to-artifactory.ps1"
_VERSION = "9.9.9"
_UNPINNED_NAME = "doc-tools"


def _text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def _iagent_block() -> str:
    m = re.search(r"\$IagentImages = @\((.*?)\n\)\n", _text(), re.S)
    assert m, "could not find the $IagentImages block"
    return m.group(1)


def _rows() -> list[tuple[str, str]]:
    rows = re.findall(r"src='([^']*)';\s*dst='([^']*)'", _iagent_block())
    assert len(rows) >= 10, f"the iagent table parsed to {len(rows)} rows; regex is wrong"
    return rows


def test_iagent_rows_carry_no_tag():
    for src, dst in _rows():
        assert ":" not in src and ":" not in dst, f"row carries a tag: {src} -> {dst}"


def test_no_row_anywhere_is_latest():
    assert not re.search(r"(src|dst)='[^']*:latest'", _text())


# --------------------------------------------------------------------- behavioural

_PS = shutil.which("pwsh") or shutil.which("powershell")


def _fixture(tmp_path: Path, repos: list[str], name: str) -> Path:
    lines = [f"# Chart version {_VERSION}, release file", "global:", "  imageDigests:"]
    for i, r in enumerate(repos):
        lines.append(f'    "{r}": "sha256:{i:064x}"')
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(*args: str):
    cmd = [_PS, "-NoProfile", "-NonInteractive"]
    if Path(_PS).stem.lower() == "powershell":
        cmd += ["-ExecutionPolicy", "Bypass"]
    cmd += ["-File", str(_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)


def _plan(out: str) -> list[dict]:
    return [json.loads(ln) for ln in out.splitlines() if ln.strip().startswith("{")]


needs_ps = pytest.mark.skipif(_PS is None, reason="neither pwsh nor powershell on PATH")


def _args(fixture: Path, *extra: str) -> list[str]:
    return ["-PlanOnly", "-RepoBase", "example.invalid/base", "-Release", _VERSION,
            "-ReleaseValues", str(fixture), *extra]


def _repos_except_unpinned() -> tuple[list[str], list[str]]:
    all_repos = [src for src, _ in _rows()]
    kept = [r for r in all_repos if not r.endswith("/" + _UNPINNED_NAME)]
    assert len(kept) == len(all_repos) - 1, "expected exactly one doc-tools row"
    return all_repos, kept


@needs_ps
def test_a_row_without_a_release_digest_is_refused(tmp_path):
    _, kept = _repos_except_unpinned()
    r = _run(*_args(_fixture(tmp_path, kept, "r.yaml")))
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert _UNPINNED_NAME in r.stdout + r.stderr
    assert not _plan(r.stdout)


@needs_ps
def test_skip_unpinned_drops_it_and_everything_else_is_by_digest(tmp_path):
    _, kept = _repos_except_unpinned()
    r = _run(*_args(_fixture(tmp_path, kept, "r.yaml"), "-SkipUnpinned"))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    plan = _plan(r.stdout)
    assert len(plan) == len(kept)
    for p in plan:
        assert p["release"] is True
        assert re.fullmatch(r"[^@:]+@sha256:[0-9a-f]{64}", p["src"]), p
        assert p["dst"].endswith(f":{_VERSION}"), p
        assert _UNPINNED_NAME not in p["src"]
    assert "latest" not in (r.stdout + r.stderr).lower()


@needs_ps
def test_a_release_with_every_repo_plans_every_row(tmp_path):
    all_repos, _ = _repos_except_unpinned()
    r = _run(*_args(_fixture(tmp_path, all_repos, "r.yaml")))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert len(_plan(r.stdout)) == len(_rows())


@needs_ps
def test_release_is_mandatory(tmp_path):
    r = _run("-PlanOnly", "-RepoBase", "example.invalid/base")
    assert r.returncode != 0
    assert not _plan(r.stdout)
