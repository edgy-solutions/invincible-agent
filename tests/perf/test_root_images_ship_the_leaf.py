"""The root images must ship provenance-telemetry, or #327's spans are silent no-ops.

cortex-bff and the dagster user-code image build from the repo root and install with
``uv sync --locked --no-dev`` and no extras: the install set is exactly ``[project].dependencies``.
The leaf was only in the dev group, so ``trace_spans`` fell back to no-ops without a word.
Pure file parsing plus one offline subprocess; no network, no cluster.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LEAF = "provenance-telemetry"
WARNING = "trace spans are no-ops"
FORBIDDEN = ("--extra", "--all-extras", "--group", "--all-groups")


def _norm(req: str) -> str:
    name = re.split(r"[\s;<>=!~\[@(]", req.strip(), maxsplit=1)[0]
    return name.lower().replace("_", "-")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _sync_lines(dockerfile: str) -> list[str]:
    text = (ROOT / ".github" / "docker" / dockerfile).read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if re.search(r"\buv sync\b", ln) and not ln.lstrip().startswith("#")]


def test_root_image_installs_are_no_dev_and_no_extras():
    for df in ("Dockerfile.agent", "Dockerfile.dagster"):
        lines = _sync_lines(df)
        assert lines, f"{df}: no `uv sync` found; the install premise changed, re-examine"
        for ln in lines:
            assert "--no-dev" in ln and not any(f in ln for f in FORBIDDEN), (
                f"{df}: `{ln.strip()}` no longer installs exactly [project].dependencies. "
                f"The telemetry leaf is shipped as a main dependency on that premise; "
                f"re-examine where it must now be declared."
            )


def test_cortex_bff_and_dagster_build_from_the_root():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "build-containers.yml").read_text(encoding="utf-8"))
    entries = [e for job in wf["jobs"].values() for e in job.get("strategy", {}).get("matrix", {}).get("include", [])]
    bff = [e for e in entries if e.get("service") == "cortex-bff"]
    assert len(bff) == 1 and str(bff[0].get("path")) == "."
    raw = (ROOT / ".github" / "workflows" / "build-containers.yml").read_text(encoding="utf-8")
    assert re.search(r"-f \.github/docker/Dockerfile\.dagster(\s|\|$)", raw)


def test_leaf_is_a_main_dependency():
    deps = _pyproject()["project"]["dependencies"]
    assert LEAF in {_norm(d) for d in deps}, f"{LEAF} missing from [project].dependencies"


def test_lock_agrees_with_pyproject():
    name = _pyproject()["project"]["name"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    roots = [p for p in lock["package"] if p["name"] == name]
    assert len(roots) == 1
    src = roots[0]["source"]
    assert src.get("editable") == "." or src.get("virtual") == "."
    assert LEAF in {_norm(d["name"]) for d in roots[0].get("dependencies", [])}, (
        "uv.lock root package lacks the leaf in plain dependencies; re-run `uv lock`"
    )


_PROBE = r"""
import sys, importlib.abc
sys.path.insert(0, {root!r}); sys.path.insert(0, {src!r}); sys.path.insert(0, {shim!r})
if {block!r}:
    class _B(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "provenance_telemetry" or name.startswith("provenance_telemetry."):
                raise ImportError("blocked")
    sys.meta_path.insert(0, _B())
from iagent import trace_spans  # noqa
"""


def _run(block: bool) -> str:
    code = _PROBE.format(root=str(ROOT), src=str(ROOT / "src"), shim=str(ROOT / "baml_shared"), block=block)
    env = {"LANGFUSE_SECRET_KEY": "sk-dummy", "LANGFUSE_PUBLIC_KEY": "pk-dummy", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    p = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=120)
    return p.stderr


def test_warns_when_keys_set_and_leaf_absent():
    assert WARNING in _run(block=True)


def test_silent_when_leaf_present():
    assert WARNING not in _run(block=False)
