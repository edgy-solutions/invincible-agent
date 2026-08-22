"""The tree-walk helper's own tests — including the property `rglob` cannot have.

The pruning test is easy. The enduring test is the one that matters, because it reproduces the
actual failure: a directory that cannot be traversed, sitting inside a tree the walk must cover.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._treewalk import DEFAULT_PRUNE, find_files


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "uv.lock").write_text("real", encoding="utf-8")
    (tmp_path / ".venv.wsl" / "lib64").mkdir(parents=True)
    (tmp_path / ".venv.wsl" / "uv.lock").write_text("vendored", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "uv.lock").write_text("vendored", encoding="utf-8")
    return tmp_path


def test_it_finds_the_real_files(tree):
    found = find_files(tree, "uv.lock")
    assert [p.parent.name for p in found] == ["a"]


def test_pruned_directories_are_NOT_DESCENDED_not_merely_filtered(tree, monkeypatch):
    """The distinction this helper exists for.

    A post-hoc filter yields the same RESULT and still walks the excluded tree — which is where
    the exception came from. So this asserts on the WALK, not the result: `os.walk` must never
    be handed a pruned directory to descend.
    """
    visited: list[str] = []
    real_walk = os.walk

    def spy(top, *a, **k):
        for dirpath, dirnames, filenames in real_walk(top, *a, **k):
            visited.append(dirpath)
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", spy)
    find_files(tree, "uv.lock")

    assert any(v.endswith("a") for v in visited), "positive control: the walk covered nothing"
    for pruned in (".venv.wsl", "node_modules"):
        assert not any(pruned in v for v in visited), (
            f"the walk DESCENDED into {pruned} — a post-hoc filter would pass this test's "
            f"result assertion while still raising on an unreadable entry inside"
        )


def test_an_unreadable_directory_is_SKIPPED_not_fatal(tmp_path, monkeypatch):
    """THE ACTUAL FAILURE, reproduced.

    `.venv.wsl/lib64` is a WSL symlink a Windows interpreter cannot traverse; the raise landed
    at import time and removed two whole test files from the run. Here the unreadable entry is
    NOT pruned, so the walk genuinely meets it — and must survive.
    """
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "uv.lock").write_text("real", encoding="utf-8")
    (tmp_path / "cursed").mkdir()

    real_walk = os.walk

    def exploding(top, *a, onerror=None, **k):
        for dirpath, dirnames, filenames in real_walk(top, *a, **k):
            if dirpath.endswith("cursed"):
                if onerror:
                    onerror(OSError(1920, "The file cannot be accessed by the system"))
                continue
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", exploding)
    # `cursed` is deliberately absent from the prune set — the walk must ENDURE it, not avoid it.
    found = find_files(tmp_path, "uv.lock", prune=frozenset({".git"}))
    assert [p.parent.name for p in found] == ["keep"]


def test_the_prune_set_names_the_directory_that_actually_broke():
    """`.venv.wsl` is listed explicitly rather than caught by a `.venv*` pattern, so a reader
    deleting it has to think about why it is there."""
    assert ".venv.wsl" in DEFAULT_PRUNE
    assert ".venv" in DEFAULT_PRUNE


def test_it_works_on_the_real_repo():
    """Positive control against the tree this was written for. If this returns nothing the
    helper is broken in a way the tmp_path tests cannot see."""
    root = Path(__file__).resolve().parents[1]
    found = find_files(root, "pyproject.toml")
    assert len(found) >= 3, f"only {len(found)} pyproject.toml found — the walk is broken"
    assert not any(".venv" in str(p) for p in found)
