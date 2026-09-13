"""The suite refuses a tree IT dirtied — and this proves the refusal can fire.

WHY IT EXISTS. A full run mutated `docs/BOARD.md` on 2026-09-12 and it was caught by diffing the
tree afterwards rather than by noticing. Diffing afterwards is a habit, not a check. Two
consequences, neither of which announces itself:

  1. **The run measured a tree that was moving.** A suite run measures the tree for its whole
     duration; if the run is one of the things changing it, the result belongs to no single
     state — the same defect as editing a file mid-run, with the suite as the editor.
  2. **The mutation gets staged.** `git add -A` after a green sweeps a generated change into a
     commit whose message says something else, and the message is what the next reader trusts.

THE GUARD IS IN `tests/conftest.py` AND THIS IS ITS CONTROL. A session-scoped hook that never
fires is indistinguishable from one that was deleted, and nothing in an ordinary run would tell
the difference — **the guard-that-cannot-fire shape, applied to the guard against mutation.**

HOW IT IS PROVEN. The refusal runs at `pytest_sessionfinish`, so it cannot be exercised from
inside the session it would judge. This spawns a REAL child pytest over a throwaway test that
dirties a tracked file, and asserts the child exits NON-ZERO while its own test PASSED — which is
the whole design: the tests are green and the run still fails.

Run: uv run --frozen pytest tests/test_the_suite_refuses_to_mutate_the_tree.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
#: A tracked file that is regenerated anyway, so a failed restore is cheap and visible.
_VICTIM = _REPO / "docs" / "BOARD.md"


def _run_child(body: str) -> subprocess.CompletedProcess:
    probe = _REPO / "tests" / "test_zz_mutation_probe_GENERATED.py"
    probe.write_text(body, encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-p", "no:randomly"],
            capture_output=True, text=True, cwd=str(_REPO), timeout=300,
        )
    finally:
        probe.unlink(missing_ok=True)
        subprocess.run(["git", "checkout", "--", str(_VICTIM)], cwd=str(_REPO),
                       capture_output=True, timeout=60)


def test_the_victim_file_is_tracked_and_clean_to_begin_with():
    """THE FLOOR. If it were untracked the guard ignores it by design and the proof below is
    vacuous; if it were already dirty, the child's baseline would include the change and the
    guard would correctly stay silent."""
    r = subprocess.run(["git", "status", "--porcelain", "--", str(_VICTIM)],
                       cwd=str(_REPO), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "git could not be read — this seal proves nothing here"
    assert r.stdout.strip() == "", (
        f"{_VICTIM.name} is already modified: {r.stdout.strip()!r}. The proof needs a clean "
        f"baseline, because the guard compares START to END rather than asserting cleanliness."
    )
    ls = subprocess.run(["git", "ls-files", "--error-unmatch", str(_VICTIM)],
                        cwd=str(_REPO), capture_output=True, timeout=60)
    assert ls.returncode == 0, f"{_VICTIM.name} is not tracked — the guard skips it by design"


def test_A_RUN_THAT_MUTATES_A_TRACKED_FILE_EXITS_NONZERO():
    """THE SEAL. The child's own test PASSES and the run still FAILS.

    THE PROBE BODY CARRIES NO ESCAPE SEQUENCE, DELIBERATELY. The first version appended a string
    containing a newline escape — which must be escaped for the enclosing literal too, and a
    template of a template is exactly where escapes collapse. It did: the escape became a REAL
    newline inside the child's string literal and the child died on `SyntaxError: unterminated
    string literal`.

    **The floor above caught it** — this asserts the probe PASSED before reading its exit code.
    Without that, a child that never ran would have exited non-zero and been read as the guard
    firing: the instrument's own breakage wearing the result's clothes. So the newline is NAMED
    (`chr(10)`) rather than written.
    """
    r = _run_child("\n".join([
        "from pathlib import Path",
        "MARKER = chr(10) + '<!-- tree-mutation probe -->'",
        "def test_dirties_a_tracked_file():",
        "    p = Path(__file__).resolve().parents[1] / 'docs' / 'BOARD.md'",
        "    p.write_text(p.read_text(encoding='utf-8') + MARKER, encoding='utf-8')",
        "    assert True",
        "",
    ]))
    assert "1 passed" in r.stdout, (
        f"the probe's own test did not pass, so a non-zero exit would prove nothing:\n"
        f"{r.stdout[-800:]}"
    )
    assert r.returncode != 0, (
        "the suite mutated a tracked file and still exited 0 — the guard in tests/conftest.py is "
        f"not firing:\n{r.stdout[-800:]}"
    )
    assert "MUTATED TRACKED FILES" in r.stdout, (
        f"the run failed but did not NAME the mutation, so a reader cannot act on it:\n"
        f"{r.stdout[-800:]}"
    )
    assert "BOARD.md" in r.stdout, "the guard did not name WHICH file it was"


def test_THE_CONTROL_a_run_that_touches_nothing_exits_ZERO():
    """Without this, a guard that failed EVERY run would satisfy the seal above while making the
    suite useless — trading a silent mutation for a permanent red, which is the worse trade."""
    r = _run_child("def test_touches_nothing():\n    assert True\n")
    assert "1 passed" in r.stdout, f"the control probe did not pass:\n{r.stdout[-500:]}"
    assert r.returncode == 0, (
        f"a run that changed NOTHING was refused — the guard fires on its own baseline:\n"
        f"{r.stdout[-800:]}"
    )
    assert "MUTATED TRACKED FILES" not in r.stdout


def test_THE_CONTROL_an_untracked_file_is_NOT_a_tree_mutation():
    """Scratch output is not a tree mutation. A guard that fired on it would cry wolf on every
    developer's stray file, and a guard that cries wolf is the thing this was written against."""
    r = _run_child("\n".join([
        "from pathlib import Path",
        "def test_writes_something_untracked():",
        "    p = Path(__file__).resolve().parents[1] / 'ZZ_scratch_probe.tmp'",
        "    p.write_text('x', encoding='utf-8')",
        "    try:",
        "        assert True",
        "    finally:",
        "        p.unlink(missing_ok=True)",
        "",
    ]))
    assert "1 passed" in r.stdout
    assert r.returncode == 0, (
        f"an UNTRACKED write was treated as a tree mutation:\n{r.stdout[-800:]}"
    )
