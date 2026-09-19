"""A workflow `run:` block is an EXPRESSION to GitHub, capped at 21000 characters.

MEASURED 2026-09-19, and no local parser could have seen it.

    Invalid workflow file: .github/workflows/build-containers.yml
    (Line: 160, Col: 14): Exceeded max expression length 21000

The build job's `run: |` had grown to **25,577 characters** — 399 lines, 213 of them comments
(16,235 chars, 63% of the block). GitHub rejected the file before scheduling a single job, and
reported it by falling back to the FILE PATH where the workflow's `name:` would normally appear:

    success   "Build & Push Container Images"     <- name read
    failure   ".github/workflows/build-containers.yml"   <- file unreadable

PyYAML parsed it. `ruamel.yaml` in round-trip mode parsed it. There were no tabs, no anchors, no
duplicate keys, no BOM, no control characters, no unbalanced `${{ }}`, uniform indentation, and
identical parsed structure before and after. **GitHub evaluates that string as an expression
template; every local tool sees text.** Nothing in the repo could have caught it.

── WHY THE LIMIT IS 18000 HERE ─────────────────────────────────────────────────────────────────

A limit that nothing prints until it is crossed is the class this repo keeps writing rules about.
At 21,001 the workflow simply stops being a workflow; there is no warning at 20,000. So this
fails at **18000**, with the remaining 3,000 as the margin that turns a cliff into a slope — the
same reason the census reports standing gaps as state rather than as the moment they appear.

── AND WHY THE FIX WAS FILES, NOT A TRIM ───────────────────────────────────────────────────────

63% of the block was comments, so trimming would have fixed the build and destroyed the record of
why each `COPY` line exists — including the one added that day, which is itself a record of the
same defect recurring a FOURTH time. The three Dockerfiles moved into the repo with every comment
intact, verified byte-identical to what the heredoc and its `sed -i` strip produced. The block
fell from 25,577 to 3,588.

The lines that crossed the limit were lane 74's; anyone's next comment would have done it.

Run: uv run --frozen pytest tests/test_a_run_block_stays_under_the_expression_limit.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"
#: Beside the workflow that uses them, not in the repo root — they are build inputs for
#: one workflow, and the root is the fleet's front door.
_DOCKER = _REPO / ".github" / "docker"

#: GitHub's hard ceiling. Crossing it makes the file stop being a workflow, with no warning.
GITHUB_MAX_EXPRESSION = 21000

#: Ours, with the margin that makes the limit visible before it bites.
SOFT_LIMIT = 18000


def _run_blocks(path: Path) -> "list[tuple[int, int]]":
    """(line number, character count) for every `run: |` block in the file.

    Counted from the SOURCE rather than from a parsed value, because what GitHub measures is the
    literal template text — and a parsed scalar has already lost the leading indentation that
    counts toward it.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines):
        if not line.strip().startswith("run: |"):
            continue
        indent = len(line) - len(line.lstrip())
        chars, j = 0, i + 1
        while j < len(lines):
            body = lines[j]
            if body.strip() and (len(body) - len(body.lstrip())) <= indent:
                break
            chars += len(body) + 1
            j += 1
        out.append((i + 1, chars))
    return out


def test_the_scan_finds_run_blocks():
    """THE FLOOR. A scan finding nothing would pass this file forever — which is exactly the
    silence that let a block grow to 25,577 characters unnoticed."""
    found = [(f.name, n, c) for f in _WORKFLOWS.glob("*.yml") for n, c in _run_blocks(f)]
    assert len(found) >= 3, f"only {len(found)} run blocks found across the workflows: {found}"


@pytest.mark.parametrize("wf", sorted(p.name for p in _WORKFLOWS.glob("*.yml")))
def test_EVERY_RUN_BLOCK_HAS_HEADROOM(wf: str):
    """Fail at 18000, not at 21001.

    The workflow that taught this was rejected outright — no jobs scheduled, the run not even
    retryable — and the only signal was GitHub displaying the filename instead of the workflow's
    name. There is no partial failure and no warning, so the margin IS the mechanism.
    """
    over = [
        f"line {n}: {c} chars (limit {SOFT_LIMIT}, GitHub's hard ceiling {GITHUB_MAX_EXPRESSION})"
        for n, c in _run_blocks(_WORKFLOWS / wf)
        if c > SOFT_LIMIT
    ]
    assert not over, (
        f"{wf} has a `run:` block over the soft limit:\n  " + "\n  ".join(over)
        + "\n\nGitHub treats a run block as an EXPRESSION TEMPLATE and rejects the whole file "
        "above 21000 characters — no jobs scheduled, no warning, and the run reported by "
        "FILENAME instead of workflow name. Move the content into a file in the repo rather than "
        "trimming the comments: the comments are the record of why each line exists."
    )


def test_THE_DOCKERFILES_ARE_FILES_not_heredocs():
    """The fix that ended the class, asserted so it cannot be undone by convenience.

    A heredoc is invisible to a Dockerfile linter, unreadable by the image-layout seals, and
    counts against a ceiling a reviewer cannot see. Three things got better at once by moving it:
    the seals can read a Dockerfile, the next COPY is a reviewable diff, and a file has no
    run-block ceiling.
    """
    for name in ("Dockerfile.agent", "Dockerfile.dagster", "Dockerfile.dagster-server"):
        p = _DOCKER / name
        assert p.is_file(), f"{name} is missing — the build cannot reference it with -f"
        text = p.read_text(encoding="utf-8")
        assert text.lstrip().startswith("#") or "FROM" in text.splitlines()[0], (
            f"{name} does not start with a comment or FROM — content may have been mangled"
        )
        assert "FROM" in text, f"{name} carries no FROM instruction"

    wf = (_WORKFLOWS / "build-containers.yml").read_text(encoding="utf-8")
    assert "cat << 'EOF' > Dockerfile" not in wf, (
        "a Dockerfile is being generated by heredoc again — that is what crossed the expression "
        "limit and what hid the content from every linter and seal"
    )
    assert "sed -i" not in wf or "Dockerfile" not in wf.split("sed -i")[1][:80], (
        "the heredoc dedent strip is back, which only exists to undo heredoc indentation"
    )


def test_THE_COMMENTS_SURVIVED_THE_MOVE():
    """63% of the block was comments and they were the point.

    Trimming them would have fixed the build and destroyed the reason the next person does not
    add a fifth instance of the same defect — one of those comments is the record of the fourth.
    """
    total = sum(
        sum(1 for ln in (_DOCKER / n).read_text(encoding="utf-8").splitlines()
            if ln.lstrip().startswith("#"))
        for n in ("Dockerfile.agent", "Dockerfile.dagster", "Dockerfile.dagster-server")
    )
    assert total >= 150, (
        f"only {total} comment lines across the three Dockerfiles; the move carried 192 and they "
        f"are the record this fix existed to preserve"
    )
