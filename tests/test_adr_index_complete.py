"""The ADR index has a PRODUCTION READER — this file.

WHY THIS EXISTS. `docs/adr/README.md` carries a hand-maintained table that is the entry path
to every ADR. Nothing read it. `tests/test_citation_paths.py` proves every cited `docs/…` path
RESOLVES, which is the opposite direction: it catches a row pointing at a missing file, and is
blind to a file with no row. ADR-0042 was written, every one of its eighteen citations resolved,
the board check stayed green — and it was absent from the index the whole time.

That is ADR-0040's own diagnosis one directory over: *"a record the entry path doesn't route to
is unshipped."* The board got a generator and a drift test for exactly this reason; the ADR index
got neither, and stayed correct only for as long as everyone remembered.

TWO DIRECTIONS, AND ONLY ONE WAS SEALED:

    row -> file    covered by test_citation_paths.py (rot: the row outlives the file)
    file -> row    covered by NOTHING until this file (orphan: the file never got a row)

The orphan is the quieter defect. A rotted link fails loudly the moment someone follows it. An
unindexed ADR is invisible to the person who would have followed it — they never learn it exists,
so the decision gets re-litigated from scratch by someone who had no way to know it was already
made. That is the precise failure ADRs exist to prevent, arriving through the index's back door.

Deliberately not asserting on the row's TITLE or STATUS text. Those are prose and they drift for
honest reasons (a status genuinely changes). Presence is the property that can be mechanically
true, and presence is the whole of what "the entry path routes to it" requires.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ADR_DIR / "README.md"

# `ADR-0042-some-slug.md` -> "0042". Anchored so a stray file like `minted-concepts.md`
# is not mistaken for an ADR.
_ADR_FILE = re.compile(r"^ADR-(\d{4})-.+\.md$")

# A row in the index table: `| [0042](ADR-0042-....md) | … | … |`. The NUMBER and the LINK
# TARGET are captured separately on purpose — see test_index_rows_link_to_their_own_number.
_INDEX_ROW = re.compile(r"^\|\s*\[(\d{4})\]\((ADR-(\d{4})-[^)]+\.md)\)", re.MULTILINE)


def _adr_files() -> dict[str, str]:
    """{number: filename} for every ADR file on disk."""
    out = {}
    for p in sorted(ADR_DIR.glob("ADR-*.md")):
        m = _ADR_FILE.match(p.name)
        if m:
            out[m.group(1)] = p.name
    return out


def _index_rows() -> dict[str, str]:
    """{number: link target} for every row in the index table."""
    return {m.group(1): m.group(2) for m in _INDEX_ROW.finditer(INDEX.read_text(encoding="utf-8"))}


def test_the_index_and_the_adrs_both_exist():
    """Positive control. If the directory or the table is empty, every assertion below passes
    vacuously — the guard-gone-quiet shape applied to this file's own subject."""
    assert INDEX.exists(), f"{INDEX} is missing — the ADR entry path is gone"
    files = _adr_files()
    rows = _index_rows()
    assert len(files) > 30, f"only {len(files)} ADR files found — the glob has lost its scope"
    assert len(rows) > 30, f"only {len(rows)} index rows parsed — the row pattern has drifted"


def test_every_adr_has_an_index_row():
    """THE SEAL. An ADR the index does not route to is unshipped (ADR-0040)."""
    files = _adr_files()
    rows = _index_rows()
    orphans = sorted(set(files) - set(rows))
    assert not orphans, (
        "ADR files with no row in docs/adr/README.md: "
        + ", ".join(f"{n} ({files[n]})" for n in orphans)
        + " — add a row to the index table; the file existing is not the same as it being findable"
    )


def test_every_index_row_has_an_adr_file():
    """The other direction. Kept here rather than left to test_citation_paths.py so this file
    is a complete statement about the index — a reader should not have to know that half the
    property lives in a different test to trust it."""
    files = _adr_files()
    rows = _index_rows()
    phantoms = sorted(set(rows) - set(files))
    assert not phantoms, (
        "index rows pointing at ADRs that do not exist: "
        + ", ".join(f"{n} -> {rows[n]}" for n in phantoms)
    )


def test_index_rows_link_to_their_own_number():
    """`[0041](ADR-0040-….md)` resolves, appears in the index, and is still wrong — the reader
    clicks 0041 and lands on 0040. Both other tests pass on it, because both compare SETS of
    numbers and this defect keeps the sets identical. Caught only by comparing the label to the
    target within a row."""
    mismatched = [
        (m.group(1), m.group(2))
        for m in _INDEX_ROW.finditer(INDEX.read_text(encoding="utf-8"))
        if m.group(1) != m.group(3)
    ]
    assert not mismatched, (
        "index rows whose link text and link target disagree: "
        + ", ".join(f"[{label}] -> {target}" for label, target in mismatched)
    )
