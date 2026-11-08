"""A sandbox upgrade runs from a worktree checked out at the release tag, never a working tree.

Ruled 2026-11-03 (the architect, via Chris): `upgrade-sandbox.sh` reads its chart from the tree it
lives in, so a roll from master's working tree renders whatever other lanes have merged there.

The real scripts run here, copied into a throwaway repository with `helm` and the lock stubbed, so
the wiring is measured and not only the guard. A dry run rolls nothing, so it may render any tree,
and it still prints what the tree is.
"""
from __future__ import annotations

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "require-release-tree.sh"
UPGRADE = REPO / "scripts" / "upgrade-sandbox.sh"
VERSION = "1.2.3"
TAG = f"thechart-{VERSION}"


def _bash() -> str | None:
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(p).exists():
                return p
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no bash that can run the script")


def _git(tree: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.hooksPath=", "-C", str(tree), *args],
        check=True, capture_output=True, text=True,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository at tag `thechart-1.2.3`, with the real scripts and a stubbed lock and helm."""
    root = tmp_path / "tree"
    chart = root / "helm" / "invincible-agent"
    scripts = root / "scripts"
    chart.mkdir(parents=True)
    scripts.mkdir()
    (chart / "Chart.yaml").write_text(f"name: thechart\nversion: {VERSION}\n", encoding="utf-8", newline="\n")
    (chart / "values-sandbox.yaml").write_text("a: 1\n", encoding="utf-8", newline="\n")
    (chart / "values-sandbox.secret.yaml").write_text("b: 2\n", encoding="utf-8", newline="\n")
    (root / ".gitignore").write_text("*.secret.yaml\n", encoding="utf-8", newline="\n")
    shutil.copy(GUARD, scripts / GUARD.name)
    shutil.copy(UPGRADE, scripts / UPGRADE.name)
    shutil.copy(UPGRADE.with_name("seal_image_digests.py"), scripts / "seal_image_digests.py")
    (scripts / "roll-lock.sh").write_text(
        '#!/usr/bin/env bash\necho "lock $*" >> "$CALLS"\n', encoding="utf-8", newline="\n"
    )
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "cut")
    _git(root, "tag", TAG)
    return root


def _guard(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, GUARD.as_posix(), (root / "helm" / "invincible-agent").as_posix()],
        capture_output=True, text=True, timeout=60,
    )


def _upgrade(root: Path, tmp_path: Path, *args: str, env_extra: dict | None = None) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # `helm template` is the seal's render (not a roll step): it prints one pod that is pinned by
    # digest, and is logged to a file of its own so the roll's calls stay the thing asserted on.
    (bin_dir / "helm").write_text(
        '#!/usr/bin/env bash\n'
        'if [ "$1" = "template" ]; then echo "helm $*" >> "$CALLS.template"; cat "$STUB_RENDER"; exit 0; fi\n'
        'echo "helm $*" >> "$CALLS"\n',
        encoding="utf-8", newline="\n",
    )
    # The release artifact the roll downloads (ruled 2026-11-04): the stub writes it where --dir says.
    (bin_dir / "gh").write_text(
        '#!/usr/bin/env bash\n'
        'echo "gh $*" >> "$CALLS.gh"\n'
        '[ -n "$STUB_NO_ARTIFACT" ] && exit 1\n'
        'while [ $# -gt 0 ]; do case "$1" in --dir) d="$2"; shift;; --pattern) f="$2"; shift;; esac; shift; done\n'
        'echo "global: {imageDigests: {}}" > "$d/$f"\n',
        encoding="utf-8", newline="\n",
    )
    render = tmp_path / "render.yaml"
    render.write_text(
        "kind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n"
        f"        - image: example.invalid/x@sha256:{'a' * 64}\n",
        encoding="utf-8", newline="\n",
    )
    calls = tmp_path / "calls.log"
    env = {
        **os.environ,
        "STUB_DIR": bin_dir.as_posix(),
        "CALLS": calls.as_posix(),
        "STUB_RENDER": render.as_posix(),
        "PYTHON": sys.executable,
        # Whatever else goes wrong below, a real helm finds no cluster to act on.
        "KUBECONFIG": (tmp_path / "no-such-kubeconfig").as_posix(),
        **(env_extra or {}),
    }
    for inherited in ("HELM_TIMEOUT", "HELM_KUBECONTEXT"):
        env.pop(inherited, None)
    # THE STUB IS PUT FIRST INSIDE BASH, NOT IN THE ENVIRONMENT PASSED TO IT. Git for Windows' bash
    # puts its own directories and ~/bin ahead of an inherited PATH, so a stub placed there loses to
    # an installed helm; measured when this test first ran the real one. It refuses to start
    # otherwise: this script's whole job is `helm upgrade`.
    stubbed = (
        'd="$STUB_DIR"; command -v cygpath >/dev/null && d="$(cygpath -u "$d")"; PATH="$d:$PATH"; '
        '[ "$(type -P helm)" = "$d/helm" ] || { echo "the helm stub is not first" >&2; exit 99; }; '
        'exec bash "$0" "$@"'
    )
    done = subprocess.run(
        [BASH, "-c", stubbed, (root / "scripts" / UPGRADE.name).as_posix(), *args],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return done, calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def test_the_tree_at_the_release_tag_passes(tree: Path):
    done = _guard(tree)
    assert done.returncode == 0, done.stderr
    assert TAG in done.stdout


def test_a_working_tree_past_the_tag_is_refused_and_names_both(tree: Path):
    (tree / "later.txt").write_text("merged since\n", encoding="utf-8")
    _git(tree, "add", "later.txt")
    _git(tree, "commit", "-q", "-m", "someone merged")
    done = _guard(tree)
    assert done.returncode == 4
    assert TAG in done.stderr


def test_a_version_nobody_tagged_is_refused(tree: Path):
    _git(tree, "tag", "-d", TAG)
    done = _guard(tree)
    assert done.returncode == 4
    assert "does not exist" in done.stderr


def test_another_releases_tag_on_this_commit_does_not_pass(tree: Path):
    _git(tree, "tag", "-d", TAG)
    _git(tree, "tag", "thechart-1.2.2")
    assert _guard(tree).returncode == 4


def test_a_modified_tracked_file_is_refused(tree: Path):
    (tree / ".gitignore").write_text("*.secret.yaml\n# edit\n", encoding="utf-8", newline="\n")
    done = _guard(tree)
    assert done.returncode == 4
    assert ".gitignore" in done.stderr


def test_an_untracked_file_in_the_chart_is_refused_because_helm_would_render_it(tree: Path):
    (tree / "helm" / "invincible-agent" / "extra.yaml").write_text("c: 3\n", encoding="utf-8")
    done = _guard(tree)
    assert done.returncode == 4
    assert "extra.yaml" in done.stderr


def test_an_untracked_file_outside_the_chart_does_not_matter(tree: Path):
    (tree / "notes.txt").write_text("not rendered\n", encoding="utf-8")
    assert _guard(tree).returncode == 0


def test_the_upgrade_from_a_working_tree_touches_neither_the_lock_nor_helm(tree: Path, tmp_path: Path):
    (tree / "later.txt").write_text("merged since\n", encoding="utf-8")
    _git(tree, "add", "later.txt")
    _git(tree, "commit", "-q", "-m", "someone merged")
    done, calls = _upgrade(tree, tmp_path)
    assert done.returncode == 4, done.stderr
    assert calls == []


def test_the_upgrade_from_the_tag_takes_the_lock_then_runs_helm_on_this_trees_chart(tree: Path, tmp_path: Path):
    done, calls = _upgrade(tree, tmp_path)
    assert done.returncode == 0, done.stderr
    assert [c.split()[0] for c in calls] == ["lock", "helm"]
    assert calls[0].startswith("lock acquire")
    # bash's own spelling of the path, so compare from the unique directory down.
    assert f"{tree.parent.name}/tree/helm/invincible-agent" in calls[1]


def test_a_dry_run_from_a_working_tree_renders_and_says_what_the_tree_is(tree: Path, tmp_path: Path):
    (tree / "later.txt").write_text("merged since\n", encoding="utf-8")
    _git(tree, "add", "later.txt")
    _git(tree, "commit", "-q", "-m", "someone merged")
    done, calls = _upgrade(tree, tmp_path, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert any(c.startswith("helm ") and "--dry-run" in c for c in calls)
    assert not any(c.startswith("lock acquire") for c in calls)
    assert "REFUSING" in done.stderr


def test_a_roll_downloads_the_release_artifact_and_renders_with_it_last(tree: Path, tmp_path: Path):
    done, calls = _upgrade(tree, tmp_path)
    assert done.returncode == 0, done.stderr
    gh = (tmp_path / "calls.log.gh").read_text(encoding="utf-8")
    assert f"release download invincible-agent-{VERSION}" in gh and f"values-release-{VERSION}.yaml" in gh
    helm_upgrade = next(c for c in calls if c.startswith("helm "))
    files = re.findall(r"(?:-f|--values) (\S+)", helm_upgrade)
    assert files and files[-1].endswith(f"values-release-{VERSION}.yaml"), files
    assert (tmp_path / "calls.log.template").exists(), "the seal render did not run"


def test_a_missing_release_artifact_is_a_hard_stop_that_names_the_version(tree: Path, tmp_path: Path):
    done, calls = _upgrade(tree, tmp_path, env_extra={"STUB_NO_ARTIFACT": "1"})
    assert done.returncode == 1
    assert f"values-release-{VERSION}.yaml" in done.stderr
    assert calls == []


@pytest.mark.parametrize("args", [
    ["--set", "global.imageTag=abc1234"],
    ["--set=global.imageTag=abc1234"],
    ["--set-string", "global.imageTag=abc1234"],
])
def test_global_image_tag_is_not_a_roll_argument(tree: Path, tmp_path: Path, args: list[str]):
    done, calls = _upgrade(tree, tmp_path, *args)
    assert done.returncode == 2, done.stderr
    assert "global.imageTag" in done.stderr
    assert calls == []
