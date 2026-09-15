"""No tracked text file carries a NUL byte — because one makes every grep over it silent.

WHY THIS EXISTS, and it is not hypothetical. On 2026-09-14 two NUL bytes landed in
`docs/rulings/README.md`, written by this session's own heredoc while documenting *how NUL bytes
get written by heredocs.* The escape `backslash-x-0-0` was meant to be four literal characters
naming a byte; it collapsed into the byte.

**NOTHING FAILED.** The file rendered correctly. Git stored it. The suite was green. What changed
is that `grep` stopped reporting matches and started saying:

    Binary file docs/rulings/README.md matches

— **a line that looks like an answer and contains none.** A search for kill-count citations
returned seven lines and then that, so the result was silently truncated mid-answer, and every
census sweep over that tree had been skipping the file entirely.

THE SAME HOUR, `cortex-ui-60` found the identical defect in `routing.ts`: a NUL where a space
belonged, in a de-dup key separator. Runtime was *correct* — NUL is a better separator than a
space — so nothing could ever fail on it, and the file had been invisible to every sweep.

> **A file that reads as binary does not fail a search. It leaves it.** The instrument returns a
> well-formed, confident, incomplete answer, and no caller can tell.

WHY A SWEEP IS NOT ENOUGH. A sweep is a habit, and this defect is re-introduced by the ordinary
act of writing documentation about escapes. It was found by accident, twice, on the same day. A
check runs whether or not anybody remembers the hazard — and the hazard's whole nature is that it
is invisible until you go looking for something else.

Run: uv run --frozen pytest tests/test_no_tracked_text_file_reads_as_binary.py -v
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

#: Extensions whose content is legitimately binary. Listed rather than sniffed, so that adding a
#: new binary kind is a decision someone makes rather than a file that quietly stops being
#: checked — the population is what this seal is about.
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svgz", ".webp", ".avif",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".jar", ".so", ".dll", ".dylib",
    ".pyc", ".pyd", ".xlsx", ".xls", ".docx", ".db", ".sqlite", ".sqlite3",
    ".whl", ".parquet", ".onnx", ".bin", ".mp4", ".mp3", ".wav", ".ogg",
}


def _first_nul_offset(path: Path) -> int | None:
    """Byte offset of the first NUL, or None. Streamed: some tracked files are large."""
    try:
        with open(path, "rb") as fh:
            base = 0
            while chunk := fh.read(65536):
                i = chunk.find(b"\x00")
                if i != -1:
                    return base + i
                base += len(chunk)
    except OSError:
        return None
    return None


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=str(_REPO),
        capture_output=True, text=True, timeout=120,
    )
    return [
        _REPO / rel for rel in out.stdout.split("\0")
        if rel and Path(rel).suffix.lower() not in _BINARY_EXT
    ]


def test_THE_CONTROL_the_scanner_detects_a_planted_nul(tmp_path):
    """THE POSITIVE CONTROL, AND IT IS NOT CEREMONIAL.

    The first hand-run sweep of this tree used `grep -P`, which this shell does not support: it
    matched nothing and reported CLEAN over 1199 files. `cortex-ui-60`'s used a dollar-quoted
    escape that collapsed to an EMPTY pattern and matched every line — "322 NUL-carrying lines"
    in a 321-line file. **Neither tool errored.** One produced a false all-clear, the other a
    false alarm whose arithmetic was the only tell.

    So the scanner proves itself on a planted byte, through the same code path the assertion
    below uses, before that assertion is allowed to mean anything. The byte is NAMED rather than
    written — `bytes([0])`, never an escape in a literal — which is the defect this file is about.
    """
    nul = bytes([0])
    planted = tmp_path / "planted.txt"
    planted.write_bytes(b"hello" + nul + b"world")
    assert _first_nul_offset(planted) == 5, (
        "the scanner cannot see a planted NUL — every result below is from a blind instrument"
    )
    clean = tmp_path / "clean.txt"
    clean.write_bytes(b"hello world")
    assert _first_nul_offset(clean) is None, (
        "the scanner reports a NUL in a file that has none — it would condemn the whole tree"
    )


def test_THE_POPULATION_IS_PLURAL():
    """A floor. An empty or tiny population makes the assertion below vacuously true, which is
    how this class of check reads green while quantifying over nothing."""
    files = _tracked()
    assert len(files) > 200, (
        f"only {len(files)} tracked text files found — `git ls-files` failed or the extension "
        f"filter is eating the tree, and the seal below is asserting almost nothing"
    )


def test_NO_TRACKED_TEXT_FILE_CONTAINS_A_NUL_BYTE():
    """THE SEAL. One NUL makes the whole file invisible to every text search over it."""
    offenders = []
    for p in _tracked():
        off = _first_nul_offset(p)
        if off is not None:
            rel = p.relative_to(_REPO).as_posix()
            offenders.append(f"{rel} (first NUL at byte {off})")
    assert not offenders, (
        "tracked text file(s) contain a NUL byte, so `grep` answers 'Binary file ... matches' "
        "and silently returns NO LINES for them — a search over this tree is now incomplete "
        "without saying so:\n  " + "\n  ".join(offenders) +
        "\n\nUsually a collapsed escape in a heredoc or generated file. Name the character "
        "(chr(0), bytes([0])) instead of writing an escape for it."
    )
